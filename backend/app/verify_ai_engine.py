"""Explicit REAL GPU inference preflight. Does not bundle or simulate AI weights.

Run in the GPU worker container after installing the official Real-ESRGAN binary
and its .bin/.param model. A successful report is a deployment readiness signal,
not a claim that every degraded photo/video can be restored perfectly.
"""
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageFilter
from .config import settings
from .capabilities import ai_files_present

REPORT = Path(os.getenv('AI_VERIFICATION_REPORT', '/data/media/ai-verified.json'))

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def artifact_fingerprint():
    base = Path(settings.realesrgan_models)
    return {key: sha256(p) for key, p in {
        'binary': Path(settings.realesrgan_binary),
        'model_bin': base / 'realesrgan-x4plus.bin',
        'model_param': base / 'realesrgan-x4plus.param',
    }.items()}

def verification_is_current():
    if not ai_files_present() or not REPORT.is_file(): return False
    try:
        obj = json.loads(REPORT.read_text())
        if obj.get('status') != 'passed' or obj.get('engine') != 'real-esrgan-ncnn-vulkan': return False
        if obj.get('model_fingerprint') != artifact_fingerprint(): return False
        if obj.get('output_size') != [512, 512]: return False
        # Revalidate real GPU access periodically. A matching binary/model hash
        # does not prove the GPU, Vulkan driver or device still works months later.
        checked=datetime.fromisoformat(obj['verified_at_utc'])
        if checked.tzinfo is None: return False
        age=datetime.now(timezone.utc)-checked.astimezone(timezone.utc)
        if age < timedelta(minutes=-5) or age > timedelta(days=7): return False
        return True
    except (ValueError, OSError, KeyError): return False

def run_preflight():
    if not ai_files_present():
        raise RuntimeError('Real-ESRGAN binary and genuine weights (.bin and .param) are required.')
    with tempfile.TemporaryDirectory(prefix='blink-real-ai-') as tmp:
        source = Path(tmp) / 'source.png'
        output = Path(tmp) / 'output.png'
        im = Image.new('RGB', (128,128), '#37364e')
        d = ImageDraw.Draw(im)
        for x in range(4,124,8):
            d.line((x,0,x,127), fill=(205,172,90),width=1)
        for y in range(0,128,16):
            d.ellipse((12,y,110,y+12),outline='white',width=2)
        d.text((20,48),'BLINK',fill='white')
        im = im.filter(ImageFilter.GaussianBlur(0.3))
        im.save(source)
        args = [str(settings.realesrgan_binary), '-i',str(source),'-o',str(output),
                '-n','realesrgan-x4plus','-s','4','-m',str(settings.realesrgan_models),'-t','128','-f','png']
        proc = subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=180)
        if proc.returncode != 0:
            raise RuntimeError('Real-ESRGAN inference failed: '+proc.stderr[-700:])
        if not output.is_file() or output.stat().st_size < 1000:
            raise RuntimeError('No usable real inference output was produced')
        with Image.open(output) as result:
            result.load()
            if result.size != (512,512):
                raise RuntimeError(f'Unexpected upscale resolution {result.size}')
            baseline = im.resize(result.size,Image.Resampling.LANCZOS)
            # Detect a stub that merely performs ordinary resizing. This is not a
            # perceptual quality score, only a basic real-inference safeguard.
            from PIL import ImageChops, ImageStat
            difference = ImageStat.Stat(ImageChops.difference(result.convert('RGB'),baseline)).mean
            if max(difference) < 0.15:
                raise RuntimeError('Output indistinguishable from conventional resize')
        report = {'status':'passed','engine':'real-esrgan-ncnn-vulkan',
                  'output_size':[512,512], 'source_size':[128,128],
                  'verified_at_utc':datetime.now(timezone.utc).isoformat(),
                  'model_fingerprint':artifact_fingerprint(),
                  'output_sha256':sha256(output), 'resize_difference_mean':difference,
                  'limitations':'Smoke test only; 4K quality requires dataset-based and device-level checks.'}
        REPORT.parent.mkdir(parents=True,exist_ok=True)
        temp = REPORT.with_suffix('.tmp')
        temp.write_text(json.dumps(report,indent=2))
        os.replace(temp,REPORT)
        return report

if __name__ == '__main__':
    print(json.dumps(run_preflight(),indent=2))
