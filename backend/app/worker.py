"""PostgreSQL-backed worker. RealESRGAN executable and model weights are external assets.
No CPU-resize fallback is presented as AI. Cinematic modes use actual FFmpeg color processing.
"""
import subprocess, tempfile, time, shutil, os, math
from datetime import timedelta
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from sqlalchemy import select
from .db import SessionLocal
from .models import Job, Audit, now
from .billing import lock_user, refund_tokens
from .storage import Storage
from .config import settings
from .media import ffprobe
from .ai_engine import inference
from .ai_video import upscale_video_frames, dimensions_for, video_scale_filter, automatic_video_dimensions, probe_encoded_streams
from .ai_photo import prepare_photo, choose_inference_scale, photo_target_side

FILTERS={
 'natural': 'eq=contrast=1.04:saturation=1.04',
 'ultra-clear': 'eq=contrast=1.12:saturation=1.08,unsharp=5:5:0.6',
 'film-contrast': 'eq=contrast=1.25:saturation=0.88',
 'golden-hour': 'eq=brightness=0.025:contrast=1.07:saturation=1.15,colorbalance=rs=0.05:gs=0.02:bs=-0.04',
 'night-cinema': 'hqdn3d=1.5:1.5:4:4,eq=gamma=1.16:contrast=1.06',
}

def update(job_id,progress):
    with SessionLocal.begin() as db:
        j=db.get(Job,job_id)
        if j and j.status=='processing':
            j.progress=max(j.progress,min(99,int(progress)))
            j.heartbeat_at=now()

def run(cmd,timeout=1800):
    proc=subprocess.run([str(c) for c in cmd],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if proc.returncode!=0:
        raise RuntimeError('Pemrosesan media gagal: '+proc.stderr[-500:])

def ai_upscale(source,dest,job_id,progress_start,progress_end,target='auto',scale=4):
    # The only path that produces "AI" media: actual model inference.
    inference(source,dest,scale=scale,heartbeat=lambda: update(job_id,progress_start))
    update(job_id,progress_end)


def image_pipeline(j,folder,storage):
    # Live Photo has two genuinely processed components. Reserve progress space
    # for the subsequent AI video stage instead of reaching 94% prematurely.
    stage=lambda n: round(5+(n-5)*.44) if j.kind=='live_photo' else n
    original=folder/'original.png'; storage.copy_to(j.input_key,original)
    source=folder/'input.png'
    # Preconditioning is conservative and explicitly non-AI; the next stage
    # ALWAYS runs the genuine Real-ESRGAN model, with no silent resize fallback.
    _,input_size=prepare_photo(original,source,j.mode)
    ai=folder/'ai.png'
    update(j.id,stage(10))
    requested=photo_target_side(j.mode,j.target)
    scale=choose_inference_scale(input_size,requested)
    ai_upscale(source,ai,j.id,stage(10),stage(65),j.target,scale=scale)
    with Image.open(ai) as image:
        image.verify()
    if requested:
        with Image.open(ai) as sizecheck: sr_width,sr_height=sizecheck.size
        # Run a second GENUINE AI inference only when the first reconstruction
        # is substantially below the requested size, and bound huge outputs.
        if max(sr_width,sr_height)<requested*.8:
            next_pass=folder/'ai-second.png'
            extra_scale=2 if max(sr_width,sr_height)*2>=requested else 4
            ai_upscale(ai,next_pass,j.id,stage(65),stage(75),j.target,scale=extra_scale)
            ai=next_pass
    update(j.id,stage(75))
    with Image.open(ai) as im:
        im=im.convert('RGB')
        mode=j.mode
        if mode in {'sharp','hd'}:
            im=im.filter(ImageFilter.UnsharpMask(radius=1.0,percent=85,threshold=4))
        if mode=='night':
            im=ImageOps.autocontrast(im,preserve_tone=True)
            im=ImageEnhance.Brightness(im).enhance(1.05)
        if mode=='cinema':
            im=ImageEnhance.Contrast(im).enhance(1.07)
            im=ImageEnhance.Color(im).enhance(1.05)
        if mode=='portrait':
            # Preserve natural skin and identity: no invented face replacement.
            im=ImageEnhance.Contrast(im).enhance(1.02)
        maxside=requested
        if maxside:
            if max(im.size)>maxside:
                im.thumbnail((maxside,maxside),Image.Resampling.LANCZOS)
            elif max(im.size)<maxside:
                factor=maxside/max(im.size)
                if factor>2:
                    raise RuntimeError('Image source too small to responsibly reach this target; choose a lower resolution')
                # Minor final dimension alignment after actual trained-model SR.
                # This remaining resample does not synthesize real new details.
                im=im.resize((round(im.width*factor),round(im.height*factor)),Image.Resampling.LANCZOS)
        output=folder/'output.png'; im.save(output,optimize=True)
        width,height=im.size
    update(j.id,stage(94))
    key=f'jobs/{j.id}/output.png'
    storage.put_file(key,output)
    return key,None,width,height

def cinematic_pipeline(j,folder,storage):
    src=folder/('input'+Path(j.input_key).suffix)
    storage.copy_to(j.input_key,src)
    out=folder/'cinematic.mp4'
    update(j.id,20)
    video_filter=FILTERS[j.mode]
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',src,'-vf',video_filter,
         '-map','0:v:0','-map','0:a?','-c:v','libx264','-threads','2','-crf','18','-preset','veryfast',
         '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',out],timeout=300)
    update(j.id,90)
    metadata=ffprobe(out,validate_upload=False)
    key=f'jobs/{j.id}/cinematic.mp4'
    storage.put_file(key,out)
    return key,None,metadata['width'],metadata['height']

def video_pipeline(j,folder,storage):
    stage=lambda n: round(45+n*.50) if getattr(j,'is_live_motion',False) else n
    src=folder/('video'+Path(j.input_key).suffix)
    storage.copy_to(j.input_key,src)
    meta=ffprobe(src)
    frames=folder/'frames'; frames.mkdir()
    # PNG extraction is a predictable source of disk exhaustion on large videos.
    # Reject an unsafe job BEFORE FFmpeg fills private worker storage. These
    # estimates are conservative; compressed PNGs can be smaller or larger.
    estimated_frames=math.ceil(meta['duration']*min(30,max(1,meta['fps'])))
    frame_bytes=meta['width']*meta['height']*4
    desired_free=int((estimated_frames*frame_bytes + 6*frame_bytes*16)*1.15)
    free=shutil.disk_usage(folder).free
    reserve_mb=int(os.getenv('BLINK_AI_FREE_DISK_RESERVE_MB','512'))
    if free < desired_free + reserve_mb*1024*1024:
        raise RuntimeError('Not enough scratch disk for AI video: use a shorter/lower-resolution input or add worker storage')
    update(j.id,stage(5))
    # Deterministic CFR for correct frame/audio timing; do not invent frames.
    # Inputs above 30fps are normalized to 30fps to bound GPU costs.
    target_fps=min(30,max(1,meta['fps']))
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',src,
         '-vf',f'fps={target_fps:.6f}',str(frames/'%06d.png')],timeout=600)
    originals=sorted(frames.glob('*.png'))
    if not originals: raise RuntimeError('Tidak ada frame video')
    if len(originals)>settings.max_video_seconds*31:
        raise RuntimeError('Terlalu banyak frame')
    update(j.id,stage(10))
    target=j.target if j.target!='auto' else j.mode
    desired_side={'1080p':1920,'2k':2560,'4k':3840}.get(target,0)
    dimensions=dimensions_for(target,meta['width'],meta['height'])
    if target == 'auto':
        dimensions=automatic_video_dimensions(meta['width'],meta['height'])
        desired_side=max(dimensions)
    vf=video_scale_filter(dimensions)
    segments=folder/'segments';segments.mkdir()
    working=folder/'ai-working';working.mkdir()
    chunklist=[]
    for index, (enhanced,completion) in enumerate(upscale_video_frames(
        originals, working, j.id, desired_side,
        lambda done: update(j.id,stage(10+round(done*65))), segment_size=6)):
        # The GPU model processes ALL frames. Only the current batch has large
        # inference outputs, which are removed immediately after encoding.
        batch_path=segments/f'{index:05d}.mp4'
        input_pattern=working/'%06d.png'
        for name,frame in enumerate(enhanced,1):
            # Prepare contiguous sequence for the frame encoder.
            (working/f'{name:06d}.png').hardlink_to(frame)
        # Avoid overwriting source frame names, which are isolated in ai-batch-output.
        try:
            run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                 '-framerate',f'{target_fps:.6f}','-i',input_pattern,
                 '-vf',vf,'-c:v','libx264','-threads','2','-crf','15','-preset','veryfast',
                 '-pix_fmt','yuv420p','-an',batch_path],timeout=900)
        finally:
            for name in range(1,len(enhanced)+1):
                (working/f'{name:06d}.png').unlink(missing_ok=True)
        chunklist.append(batch_path)
        update(j.id,stage(10+round(completion*70)))
    # Concat processed sections and apply moderate temporal denoising ACROSS
    # the whole timeline (not independently per chunk), then restore audio.
    concatfile=folder/'segments.txt'
    concatfile.write_text(''.join(f"file '{p.as_posix()}'\n" for p in chunklist))
    output=folder/'output.mp4'
    # With '-shortest', shorter source audio would truncate the enhanced video.
    # Pad audio until the processed video ends, only when audio actually exists.
    _,source_has_audio=probe_encoded_streams(src)
    audio_pad=['-af','apad'] if source_has_audio else []
    run(['ffmpeg','-hide_banner','-loglevel','error','-y',
         '-f','concat','-safe','0','-i',concatfile,'-i',src,
         '-map','0:v:0','-map','1:a?','-vf','hqdn3d=1.2:1.0:2.4:2.0',
         '-c:v','libx264','-threads','2','-crf','18','-preset','veryfast',
         '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
         *audio_pad,'-t',f'{len(originals)/target_fps:.6f}',
         '-movflags','+faststart',output],timeout=1800)
    update(j.id,stage(93))
    final=ffprobe(output,validate_upload=False)
    output_frames,output_has_audio=probe_encoded_streams(output)
    if output_frames!=len(originals):
        raise RuntimeError(f'AI video frame loss: expected {len(originals)}, got {output_frames}')
    if source_has_audio and not output_has_audio:
        raise RuntimeError('AI video export lost the source audio track')
    if dimensions and (final['width'],final['height'])!=dimensions:
        raise RuntimeError(f'AI video resolution mismatch: {final["width"]}x{final["height"]}')
    if abs(final['duration']-meta['duration'])>max(.4, 2/target_fps):
        raise RuntimeError('AI video duration mismatch; possible sync problem')
    key=f'jobs/{j.id}/output.mp4'
    storage.put_file(key,output)
    return key,None,final['width'],final['height']

def process(job_id):
    with SessionLocal() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='processing': return
        kind=j.kind
    key=None; motion_key=None; storage=None
    try:
        with tempfile.TemporaryDirectory(prefix='blink-worker-') as dirname:
            folder=Path(dirname);storage=Storage()
            if kind in {'photo','live_photo'}: result=image_pipeline(j,folder,storage)
            elif kind=='video': result=video_pipeline(j,folder,storage)
            else: result=cinematic_pipeline(j,folder,storage)
            key,motion_key,w,h=result
            if kind=='live_photo' and j.motion_key:
                # Live Photo enhancement must process BOTH the still and motion clip.
                # Never pass through the original video while claiming AI enhanced motion.
                from types import SimpleNamespace
                motion_job=SimpleNamespace(id=j.id, input_key=j.motion_key, target=j.target,
                                           mode='auto',kind='video',is_live_motion=True)
                motion_key,_,motion_w,motion_h=video_pipeline(motion_job,folder,storage)
                motion_final=f'jobs/{j.id}/live-motion.mp4'
                storage.copy_to(motion_key,folder/'enhanced-live-motion.mp4')
                storage.put_file(motion_final,folder/'enhanced-live-motion.mp4')
                storage.remove(motion_key)
                motion_key=motion_final
        with SessionLocal.begin() as db:
            locked=db.execute(select(Job).where(Job.id==job_id).with_for_update()).scalar_one()
            if locked.status!='processing': return
            locked.output_key=key;locked.output_motion_key=motion_key
            locked.output_width=w;locked.output_height=h
            locked.progress=100;locked.status='completed';locked.finished_at=now()
    except Exception as exc:
        if key and storage:
            try: storage.remove(key)
            except Exception: pass  # Preserve original failure and token refund.
        if motion_key and storage:
            try: storage.remove(motion_key)
            except Exception: pass
        with SessionLocal.begin() as db:
            job=db.execute(select(Job).where(Job.id==job_id).with_for_update()).scalar_one_or_none()
            if job and job.status=='processing':
                user=lock_user(db,job.user_id)
                job.status='failed';job.error=str(exc)[:500];job.finished_at=now()
                refund_tokens(db,user,job)
                db.add(Audit(event='job_failed',target_id=job.id,data='{}'))

def claim():
    with SessionLocal.begin() as db:
        job=db.execute(select(Job).where(Job.status=='queued').order_by(Job.priority.desc(),Job.created_at.asc()).with_for_update(skip_locked=True).limit(1)).scalar_one_or_none()
        if not job: return None
        job.status='processing';job.started_at=now();job.heartbeat_at=now();job.progress=1
        return job.id

def reap_stale():
    cutoff=now()-timedelta(hours=3)
    with SessionLocal() as db:
        stale=list(db.scalars(select(Job.id).where(Job.status=='processing',Job.heartbeat_at<cutoff).limit(20)))
    for jid in stale:
        with SessionLocal.begin() as db:
            job=db.execute(select(Job).where(Job.id==jid).with_for_update()).scalar_one_or_none()
            if job and job.status=='processing' and job.heartbeat_at and job.heartbeat_at<cutoff:
                user=lock_user(db,job.user_id)
                job.status='failed';job.error='Worker timeout';job.finished_at=now()
                refund_tokens(db,user,job)

def main():
    print('BLINK worker started. No mocked AI processing.',flush=True)
    while True:
        try:
            reap_stale()
            job_id=claim()
            if job_id: process(job_id)
            else: time.sleep(2)
        except Exception as exc:
            print('Worker error:',type(exc).__name__,str(exc)[:150],flush=True)
            time.sleep(5)

if __name__=='__main__':main()
