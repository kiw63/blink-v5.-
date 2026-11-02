"""GPU-batched AI video processing. Every output frame is inferred by Real-ESRGAN.

Chunked intermediate encoding bounds the number of upscaled PNGs held on disk.
Backend accounting/queue semantics remain in app.worker and are not modified.
"""
from pathlib import Path
import json
import subprocess
from PIL import Image
from .ai_engine import inference

OUTPUT_DIMENSIONS = {'1080p': (1920,1080),'2k':(2560,1440),'4k':(3840,2160)}


def dimensions_for(target, source_width, source_height):
    if target not in OUTPUT_DIMENSIONS: return None
    w,h=OUTPUT_DIMENSIONS[target]
    return (w,h) if source_width >= source_height else (h,w)


def automatic_video_dimensions(source_width, source_height):
    """Bound Smart Auto resolution while preserving source aspect ratio.

    Never silently turn 1080p input into 8K output.  Auto output is capped at
    1920 pixels along its long edge; smaller sources can get genuine x4 AI
    reconstruction without promising more detail than their native content.
    """
    if source_width <= 0 or source_height <= 0:
        raise ValueError('Invalid video dimensions')
    longest=max(source_width,source_height)
    side=min(1920,longest*4)
    width=round((source_width * side / longest)/2)*2
    height=round((source_height * side / longest)/2)*2
    return max(2,width),max(2,height)


def video_scale_filter(dimensions):
    if dimensions is None:
        return 'setsar=1'
    w,h=dimensions
    return (f'scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,'
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')


def upscale_video_frames(originals, up, job_id, desired_side, update_callback,
                         *, segment_size=6, image_processor=None):
    """Yield batches of processed PNG frames with bounded temporary output storage.

    `image_processor` is injectable solely for adapter unit tests. Production
    uses the real Real-ESRGAN CLI; no interpolation-only AI fallback exists.
    """
    if image_processor is None: image_processor=inference
    if not isinstance(segment_size, int) or not 1 <= segment_size <= 24:
        raise ValueError('AI frame batch size must be 1..24 to bound GPU memory')
    originals=sorted(originals)
    if not originals:
        raise ValueError('No source frames')
    up=Path(up); up.mkdir(parents=True,exist_ok=True)
    root=up.parent
    total=len(originals)
    for offset in range(0,total,segment_size):
        frames=originals[offset:offset+segment_size]
        in_dir=root/'ai-batch-input'; out_dir=root/'ai-batch-output'
        in_dir.mkdir(exist_ok=True);out_dir.mkdir(exist_ok=True)
        for frame in frames:
            # Hardlinks eliminate extra frame copies on local storage.
            # These files are ephemeral and never edited in place.
            (in_dir/frame.name).hardlink_to(frame)
        try:
            with Image.open(frames[0]) as sample:
                original_side=max(sample.size)
            scale=2 if desired_side and original_side*2>=desired_side else 4
            image_processor(in_dir,out_dir,scale=scale,
                            heartbeat=lambda: update_callback(offset/total))
            expected={frame.name for frame in frames}
            produced={f.name for f in out_dir.iterdir() if f.is_file()}
            if produced != expected:
                raise RuntimeError('AI frame batch contains missing or unexpected frames')
            paths=[]
            for frame in frames:
                out_frame=out_dir/frame.name
                if not out_frame.is_file() or out_frame.stat().st_size<=0:
                    raise RuntimeError(f'AI frame missing: {frame.name}')
                with Image.open(frame) as source_image:
                    source_size=source_image.size
                with Image.open(out_frame) as test:
                    test.verify()
                    if test.size != (source_size[0]*scale, source_size[1]*scale):
                        raise RuntimeError(f'AI frame dimensions invalid: {frame.name}')
                paths.append(out_frame)
            yield paths, (offset+len(frames))/total
        finally:
            for directory in (in_dir,out_dir):
                for item in directory.iterdir(): item.unlink()
                directory.rmdir()
            # Remove original frames as they are processed, freeing disk.
            for frame in frames:
                frame.unlink(missing_ok=True)

def probe_encoded_streams(path):
    """Verify actual encoded frame packets and whether an audio track exists.

    Counting packets avoids decoding full 4K video just to validate frame loss.
    This is a container-integrity gate, NOT a test of neural restoration.
    """
    output = subprocess.run([
        'ffprobe','-v','error','-count_packets',
        '-show_entries','stream=codec_type,nb_read_packets',
        '-of','json',str(path)
    ], capture_output=True, text=True, check=True, timeout=45)
    streams=json.loads(output.stdout).get('streams',[])
    video=next((s for s in streams if s.get('codec_type')=='video'),None)
    if not video:
        raise RuntimeError('AI export has no video stream')
    count=int(video.get('nb_read_packets') or 0)
    if count<=0:
        raise RuntimeError('AI export has no encoded video frames')
    return count, any(s.get('codec_type')=='audio' for s in streams)
