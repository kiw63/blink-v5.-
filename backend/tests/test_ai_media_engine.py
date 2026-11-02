"""AI worker integration tests. The injectable scaler is a TEST DOUBLE ONLY.

These tests verify batch/file contracts and FFmpeg output, NOT trained-model
super-resolution quality; only real GPU evaluation may assert that quality.
"""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest
from PIL import Image
from app.ai_video import dimensions_for, video_scale_filter, upscale_video_frames
from app.ai_engine import inference
from app.media import ffprobe
from app import worker


def test_real_model_is_required_even_for_batch(tmp_path, monkeypatch):
    monkeypatch.setattr('app.ai_engine.validate_model_files', lambda: (_ for _ in ()).throw(RuntimeError('missing AI model')))
    src=tmp_path/'i';src.mkdir(); Image.new('RGB',(10,10)).save(src/'000001.png')
    with pytest.raises(RuntimeError,match='missing AI model'):
        inference(src,tmp_path/'o')


def test_4k_portrait_and_landscape_filters_keep_dimensions():
    assert dimensions_for('4k',1280,720)==(3840,2160)
    assert dimensions_for('4k',720,1280)==(2160,3840)
    assert dimensions_for('2k',480,640)==(1440,2560)
    assert dimensions_for('auto',720,1280) is None
    assert '3840:2160' in video_scale_filter((3840,2160))
    assert 'force_original_aspect_ratio=decrease' in video_scale_filter((3840,2160))


def test_batched_processor_consumes_every_frame_and_cleans(tmp_path):
    frames=tmp_path/'frames';frames.mkdir()
    for i in range(7):Image.new('RGB',(32,20),(i*20,40,60)).save(frames/f'{i+1:06d}.png')
    calls=[];progress=[]
    def model_double(src,dst,scale,heartbeat):
        calls.append(scale)
        heartbeat()
        for file in src.glob('*.png'):
            with Image.open(file) as im:
                im.resize((im.width*scale,im.height*scale)).save(dst/file.name)
    for chunk,done in upscale_video_frames(list(frames.glob('*.png')),tmp_path/'up',1,64,progress.append,
                                            segment_size=3,image_processor=model_double):
        assert all(x.exists() for x in chunk)
        assert len(chunk)<=3
        assert 0<done<=1
    assert calls==[2,2,2]
    assert progress and all(0<=x<=1 for x in progress)
    assert not list(frames.glob('*.png'))
    assert not (tmp_path/'ai-batch-input').exists()
    assert not (tmp_path/'ai-batch-output').exists()


def test_batch_rejects_missing_ai_frame(tmp_path):
    src=tmp_path/'original';src.mkdir()
    for i in range(2): Image.new('RGB',(16,16)).save(src/f'{i+1:06d}.png')
    def incomplete(source,dest,scale,heartbeat):
        Image.new('RGB',(64,64)).save(dest/'000001.png')
    with pytest.raises(RuntimeError,match='missing'):
        list(upscale_video_frames(list(src.glob('*.png')),tmp_path/'up',1,0,lambda _:None,
                                  image_processor=incomplete))


def test_actual_ffmpeg_video_export_with_audio_and_chunking(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
      '-f','lavfi','-i','testsrc2=size=96x64:rate=12:duration=1.1',
      '-f','lavfi','-i','sine=frequency=440:duration=1.1',
      '-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(source)],
      check=True,timeout=30)
    stored={}
    class LocalStorage:
        def copy_to(self,key,dest):
            import shutil; shutil.copyfile(source,dest)
        def put_file(self,key,filepath):
            import shutil
            out=tmp_path/'export.mp4';shutil.copyfile(filepath,out);stored[key]=out
    def model_double(src,dst,scale,heartbeat):
        for file in src.glob('*.png'):
            with Image.open(file) as im:
                im.resize((im.width*scale,im.height*scale)).save(dst/file.name)
    monkeypatch.setattr('app.ai_video.inference',model_double)
    monkeypatch.setattr(worker,'update',lambda *_:None)
    j=SimpleNamespace(id='qa-worker',input_key='test/source.mp4',target='auto',mode='auto')
    folder=tmp_path/'job';folder.mkdir()
    key,motion,w,h=worker.video_pipeline(j,folder,LocalStorage())
    result=stored[key]
    assert result.is_file() and result.stat().st_size>0
    meta=ffprobe(result,validate_upload=False)
    assert meta['width']==w and meta['height']==h
    assert abs(meta['duration']-1.1)<.4
    audio=subprocess.run(['ffprobe','-v','error','-select_streams','a:0',
     '-show_entries','stream=codec_name','-of','default=noprint_wrappers=1',str(result)],
     capture_output=True,text=True,check=True)
    assert 'aac' in audio.stdout
    assert len(list((folder/'segments').glob('*.mp4')))>=2


def test_incomplete_gpu_output_is_not_mistaken_for_a_success(tmp_path,monkeypatch):
    from app import ai_engine
    # Output validation only. This subprocess double is never a real AI model.
    binary=tmp_path/'fake'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o700)
    monkeypatch.setattr(ai_engine,'validate_model_files',lambda:binary)
    src=tmp_path/'s.png';Image.new('RGB',(24,24)).save(src)
    with pytest.raises(RuntimeError,match='no usable output'):
        ai_engine.inference(src,tmp_path/'out.png')


def test_photo_planning_avoids_excessive_output_and_preserves_aspect(tmp_path):
    from app.ai_photo import prepare_photo,choose_inference_scale,photo_target_side,analyze_photo
    src=tmp_path/'raw.png';dst=tmp_path/'prepared.png'
    Image.new('RGB',(480,320),(12,15,18)).save(src)
    before,sz=prepare_photo(src,dst,'night')
    assert before['luminance']<58
    assert sz==(480,320)
    with Image.open(dst) as processed:
        assert processed.size==(480,320)
        assert processed.getpixel((4,4))[0]>12
    assert choose_inference_scale((2000,1200),3840)==2
    assert choose_inference_scale((480,320),3840)==4
    assert photo_target_side('4k','auto')==3840
    assert photo_target_side('auto','2k')==2560


def test_photo_input_is_bounded_before_model_inference(tmp_path):
    from app.ai_photo import prepare_photo
    src=tmp_path/'large.png';dest=tmp_path/'limited.png'
    Image.new('RGB',(4200,1800),'#224466').save(src)
    _,dims=prepare_photo(src,dest,'auto')
    assert max(dims)==4096
    assert dims[0]/dims[1]==pytest.approx(4200/1800,rel=.002)


def test_production_worker_refuses_ai_unverified(monkeypatch,tmp_path):
    from app import ai_engine
    binary=tmp_path/'realesrgan';binary.write_text('binary');binary.chmod(0o700)
    monkeypatch.setattr(ai_engine,'ai_files_present',lambda: True)
    monkeypatch.setattr(ai_engine.settings,'realesrgan_binary',str(binary))
    monkeypatch.setenv('BLINK_ENV','production')
    monkeypatch.setattr('app.verify_ai_engine.verification_is_current',lambda: False)
    with pytest.raises(RuntimeError,match='not verified'):
        ai_engine.validate_model_files()


@pytest.mark.parametrize('size,expected', [('96x64',(3840,2160)),('64x96',(2160,3840))])
def test_4k_video_export_dimensions_and_audio_with_codec_double(size,expected,tmp_path,monkeypatch):
    """4K ENCODING test only; the test double is NOT trained super-resolution."""
    source=tmp_path/'short.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
      '-f','lavfi','-i',f'testsrc2=size={size}:rate=4:duration=0.5',
      '-f','lavfi','-i','sine=frequency=330:duration=0.5',
      '-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(source)],
      check=True,timeout=20)
    output=tmp_path/'output.mp4'
    class Store:
        def copy_to(self,k,d):
            import shutil;shutil.copyfile(source,d)
        def put_file(self,k,d):
            import shutil;shutil.copyfile(d,output)
    def double(src,dst,scale,heartbeat):
        for f in src.glob('*.png'):
            with Image.open(f) as im:
                im.resize((im.width*scale,im.height*scale)).save(dst/f.name)
    monkeypatch.setattr('app.ai_video.inference',double)
    monkeypatch.setattr(worker,'update',lambda *_:None)
    d=tmp_path/'job';d.mkdir()
    j=SimpleNamespace(id='4k-smoke',input_key='short.mp4',target='4k',mode='auto')
    _,_,w,h=worker.video_pipeline(j,d,Store())
    assert (w,h)==expected
    assert output.stat().st_size>0
    meta=ffprobe(output,validate_upload=False)
    assert (meta['width'],meta['height'])==expected
    assert abs(meta['duration']-0.5)<.4
