"""Checks for real AI adapter safety and media integrity.

Any injected fake model in these tests checks plumbing ONLY, not visual AI quality.
"""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import shutil
from PIL import Image
import pytest
from app import ai_engine, worker
from app.ai_video import automatic_video_dimensions, upscale_video_frames
from app.media import ffprobe


def test_auto_video_never_accidentally_exports_8k():
    assert automatic_video_dimensions(1920,1080)==(1920,1080)
    assert automatic_video_dimensions(1080,1920)==(1080,1920)
    assert automatic_video_dimensions(96,64)==(384,256)
    assert automatic_video_dimensions(640,480)==(1920,1440)
    with pytest.raises(ValueError):automatic_video_dimensions(0,1080)


def test_ai_adapter_rejects_stale_output(tmp_path,monkeypatch):
    src=tmp_path/'input.png';Image.new('RGB',(24,24)).save(src)
    dst=tmp_path/'output.png';Image.new('RGB',(48,48)).save(dst)
    monkeypatch.setattr(ai_engine,'validate_model_files',lambda:Path('/bin/true'))
    with pytest.raises(FileExistsError,match='not empty'):
        ai_engine.inference(src,dst,scale=2)
    with pytest.raises(ValueError,match='separate'):
        ai_engine.inference(src,src)


def test_ai_adapter_kills_gpu_child_if_heartbeat_crashes(tmp_path,monkeypatch):
    src=tmp_path/'in.png';Image.new('RGB',(16,16)).save(src)
    monkeypatch.setattr(ai_engine,'validate_model_files',lambda:Path('/bin/true'))
    class DummyProcess:
        killed=False
        def __init__(self,*_,**__):pass
        def poll(self):return None if not self.killed else -9
        def wait(self,timeout=None):
            if not self.killed:raise subprocess.TimeoutExpired('ai',timeout)
            return -9
        def kill(self):self.killed=True
    proc=DummyProcess()
    monkeypatch.setattr(ai_engine.subprocess,'Popen',lambda *a,**kw:proc)
    def broken_heartbeat():raise RuntimeError('Lost database heartbeat')
    with pytest.raises(RuntimeError,match='Lost database heartbeat'):
        ai_engine.inference(src,tmp_path/'up.png',scale=2,heartbeat=broken_heartbeat)
    assert proc.killed


def test_batch_requires_expected_ai_dimensions_and_bounded_size(tmp_path):
    src=tmp_path/'original';src.mkdir()
    Image.new('RGB',(22,14)).save(src/'000001.png')
    def invalid_model(indir,outdir,scale,heartbeat):
        Image.new('RGB',(21,14)).save(outdir/'000001.png')
    with pytest.raises(RuntimeError,match='dimensions invalid'):
        list(upscale_video_frames(list(src.glob('*.png')),tmp_path/'up',123,0,lambda v:None,image_processor=invalid_model))
    assert not (tmp_path/'ai-batch-output').exists()
    with pytest.raises(ValueError,match='batch size'):
        list(upscale_video_frames([],tmp_path/'up2',123,0,lambda v:None,segment_size=0))


@pytest.mark.parametrize('has_audio', [True,False])
def test_video_preserves_full_duration_even_when_input_audio_ends_early(tmp_path, monkeypatch, has_audio):
    src=tmp_path/'source.mp4'
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi',
         '-i','testsrc2=size=96x64:rate=8:duration=1.0']
    if has_audio:
        cmd+=['-f','lavfi','-i','sine=frequency=440:duration=0.16']
    cmd+=['-c:v','libx264','-preset','ultrafast']
    if has_audio:cmd+=['-c:a','aac']
    cmd.append(str(src))
    subprocess.run(cmd,check=True,timeout=30)
    out=tmp_path/'saved.mp4'
    class Store:
        def copy_to(self,key,dest):shutil.copyfile(src,dest)
        def put_file(self,key,srcfile):shutil.copyfile(srcfile,out)
    def model_double(indir,outdir,scale,heartbeat):
        for frame in indir.glob('*.png'):
            with Image.open(frame) as im:im.resize((im.width*scale,im.height*scale)).save(outdir/frame.name)
    monkeypatch.setattr('app.ai_video.inference',model_double)
    monkeypatch.setattr(worker,'update',lambda *_:None)
    job=SimpleNamespace(id='short-audio-qa',input_key='source.mp4',target='auto',mode='auto')
    jobdir=tmp_path/'job';jobdir.mkdir()
    worker.video_pipeline(job,jobdir,Store())
    meta=ffprobe(out,validate_upload=False)
    assert abs(meta['duration']-1.0)<0.15
    assert (meta['width'],meta['height'])==(384,256)
    audio=subprocess.run(['ffprobe','-v','error','-select_streams','a:0',
        '-show_entries','stream=codec_name','-of','csv=p=0',str(out)],
        capture_output=True,text=True,check=True).stdout.strip()
    assert bool(audio)==has_audio
