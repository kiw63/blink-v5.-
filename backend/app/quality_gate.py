"""Real AI super-resolution acceptance gate (requires model, Vulkan GPU and source photo).

Usage, from backend environment with valid REAL weights:
  python qa/ai_quality_gate.py --reference /path/to/clean_4k_reference.png

It creates a degraded 960x540 input from a 3840x2160 reference, runs genuine
Real-ESRGAN NCNN Vulkan and compares with an interpolation-only baseline.
Do not use this gate to claim all unseen phone photos will become perfect.
"""
import argparse, hashlib, json, math, os, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter

ROOT=Path('/data/media')
from .config import settings
from .verify_ai_engine import run_preflight

def metrics(a,b):
    if a.size!=b.size: raise ValueError('Reference dimensions differ')
    diff=ImageChops.difference(a.convert('RGB'),b.convert('RGB'))
    hist=diff.histogram()
    mse=sum((i%256)**2 * v for i,v in enumerate(hist))/(a.width*a.height*3)
    psnr=float('inf') if mse==0 else 10*math.log10(255*255/mse)
    return {'mse':round(mse,4),'psnr_db':round(psnr,3)}

def main():
    p=argparse.ArgumentParser(description='Run actual trained-model inference and compare to interpolated 4K baseline')
    p.add_argument('--reference',required=True,help='Sharp independent 3840x2160 reference photo (not a resized/degraded input)')
    p.add_argument('--min-psnr-gain',type=float,default=0.0)
    p.add_argument('--report',default=str(ROOT/'qa/AI_REAL_4K_REPORT.json'))
    a=p.parse_args()
    preflight=run_preflight() # FAIL CLOSED when GPU/model absent
    with Image.open(a.reference) as clean:
        reference=clean.convert('RGB')
    if reference.size!=(3840,2160):
        raise SystemExit(f'Reference must be 3840x2160 landscape; got {reference.size}')
    with tempfile.TemporaryDirectory(prefix='blink-quality-gate-') as folder:
        folder=Path(folder)
        degraded=reference.resize((960,540),Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(.35))
        inp=folder/'degraded.png';degraded.save(inp)
        up=folder/'ai-4k.png'
        cmd=[settings.realesrgan_binary,'-i',str(inp),'-o',str(up),'-n','realesrgan-x4plus',
             '-s','4','-m',settings.realesrgan_models,'-t','256','-f','png']
        subprocess.run(cmd,check=True,timeout=3600)
        with Image.open(up) as result:
            result.load()
            if result.size!=(3840,2160):raise SystemExit(f'Invalid AI resolution {result.size}')
            ai=metrics(reference,result)
            baseline=metrics(reference,degraded.resize(reference.size,Image.Resampling.LANCZOS))
        gain=round(ai['psnr_db']-baseline['psnr_db'],3)
        report={'model':'Real-ESRGAN x4plus real Vulkan','ai_output_px':[3840,2160],
                'reference_px':[3840,2160],'baseline_lanczos':baseline,'ai':ai,
                'psnr_gain_db':gain,'requested_min_gain_db':a.min_psnr_gain,
                'gate_passed':gain>=a.min_psnr_gain,'preflight':preflight,
                'caveat':'A synthetic degradation benchmark; also assess real low-light, motion blur, faces and video temporal consistency manually.'}
        Path(a.report).write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        if not report['gate_passed']:raise SystemExit('FAIL: Real AI reconstruction did not beat the interpolation baseline on this reference')
if __name__=='__main__':main()
