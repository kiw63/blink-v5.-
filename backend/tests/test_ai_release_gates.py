"""Media-integrity regressions. Fake AI scaler checks plumbing only, NOT AI quality."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
from PIL import Image
import pytest
from app import worker
from app.ai_video import probe_encoded_streams
from app.media import ffprobe


def make_sample(path, audio_seconds, video_seconds=1.2):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
        '-f','lavfi','-i',f'testsrc2=size=112x64:rate=8:duration={video_seconds}',
        '-f','lavfi','-i',f'sine=frequency=330:duration={audio_seconds}',
        '-c:v','libx264','-preset','ultrafast','-c:a','aac',str(path)],
        check=True,timeout=25)


def fake_realesrgan(source,destination,scale,heartbeat):
    for p in Path(source).glob('*.png'):
        with Image.open(p) as im:
            im.resize((im.width*scale, im.height*scale)).save(Path(destination)/p.name)


class Store:
    def __init__(self,source,target):
        self.source=source;self.target=target
    def copy_to(self,key,dest):
        shutil.copyfile(self.source,dest)
    def put_file(self,key,filepath):
        shutil.copyfile(filepath,self.target)


def test_short_audio_does_not_truncate_enhanced_video(tmp_path,monkeypatch):
    source=tmp_path/'short_audio.mp4';result=tmp_path/'result.mp4'
    make_sample(source,audio_seconds=.25,video_seconds=1.2)
    original=ffprobe(source,validate_upload=False)
    source_frames,has_audio=probe_encoded_streams(source)
    assert has_audio and source_frames>=8
    monkeypatch.setattr('app.ai_video.inference',fake_realesrgan)
    monkeypatch.setattr(worker,'update',lambda *_:None)
    folder=tmp_path/'work';folder.mkdir()
    j=SimpleNamespace(id='short_audio',input_key='short_audio.mp4',target='auto',mode='auto')
    worker.video_pipeline(j,folder,Store(source,result))
    final=ffprobe(result,validate_upload=False)
    count,output_audio=probe_encoded_streams(result)
    assert output_audio
    assert count==source_frames
    assert abs(final['duration']-original['duration'])<.3


def test_worker_rejects_insufficient_scratch_disk_before_extracting(tmp_path,monkeypatch):
    source=tmp_path/'input.mp4';make_sample(source,.5,video_seconds=.7)
    monkeypatch.setattr(worker,'update',lambda *_:None)
    monkeypatch.setattr(worker.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    folder=tmp_path/'work';folder.mkdir()
    j=SimpleNamespace(id='no_disk',input_key='input.mp4',target='auto',mode='auto')
    with pytest.raises(RuntimeError,match='Not enough scratch disk'):
        worker.video_pipeline(j,folder,Store(source,tmp_path/'result.mp4'))
    assert not list((folder/'frames').glob('*.png'))


def test_encoded_frame_counter_rejects_invalid_video(tmp_path):
    p=tmp_path/'garbage.mp4';p.write_bytes(b'not a video')
    with pytest.raises(subprocess.CalledProcessError):
        probe_encoded_streams(p)


def test_gpu_model_preflight_expires_and_cannot_be_faked_as_current(tmp_path,monkeypatch):
    import json
    from datetime import datetime, timezone, timedelta
    from app import verify_ai_engine as v
    monkeypatch.setattr(v, 'ai_files_present', lambda: True)
    monkeypatch.setattr(v, 'artifact_fingerprint',lambda: {'binary':'unit-test-fingerprint'})
    report=tmp_path/'ai-verified.json'
    monkeypatch.setattr(v,'REPORT',report)
    payload={'status':'passed','engine':'real-esrgan-ncnn-vulkan','output_size':[512,512],
             'model_fingerprint':{'binary':'unit-test-fingerprint'}}
    for days,expected in [(0,True),(8,False),(-1,False)]:
        payload['verified_at_utc']=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        report.write_text(json.dumps(payload))
        assert v.verification_is_current() is expected


def test_ai_subprocess_timeout_really_stops_the_worker(tmp_path,monkeypatch):
    import time
    from app import ai_engine
    binary=tmp_path/'fake_ai'
    binary.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n')
    binary.chmod(0o755)
    monkeypatch.setattr(ai_engine,'validate_model_files',lambda: binary)
    photo=tmp_path/'input.png';Image.new('RGB',(12,12)).save(photo)
    started=time.monotonic()
    with pytest.raises(TimeoutError,match='configured timeout'):
        ai_engine.inference(photo,tmp_path/'output.png',timeout=.25)
    assert time.monotonic()-started<2


def test_video_without_audio_remains_valid(tmp_path,monkeypatch):
    source=tmp_path/'silent.mp4';output=tmp_path/'silent_export.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
        '-f','lavfi','-i','testsrc2=size=96x64:rate=8:duration=0.75',
        '-c:v','libx264','-preset','ultrafast',str(source)],check=True,timeout=25)
    count,has_audio=probe_encoded_streams(source)
    assert not has_audio
    monkeypatch.setattr('app.ai_video.inference',fake_realesrgan)
    monkeypatch.setattr(worker,'update',lambda *_:None)
    folder=tmp_path/'processing';folder.mkdir()
    j=SimpleNamespace(id='silent',input_key='silent.mp4',target='auto',mode='auto')
    worker.video_pipeline(j,folder,Store(source,output))
    enhanced_count,enhanced_has_audio=probe_encoded_streams(output)
    assert enhanced_count==count
    assert not enhanced_has_audio
    assert abs(ffprobe(output,validate_upload=False)['duration']-.75)<.2
