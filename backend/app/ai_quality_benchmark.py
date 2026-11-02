"""Fail-closed image quality benchmark for genuine Real-ESRGAN inference.

Requires high-quality independent reference images; downsampling is a controlled
experiment, not a promise to restore arbitrary out-of-focus photos.
No fake inference, interpolation-as-AI, or quality success fallback is permitted.
"""
from __future__ import annotations
import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter, ImageStat
from .ai_engine import inference
from .verify_ai_engine import run_preflight, artifact_fingerprint


def psnr(reference: Image.Image, candidate: Image.Image) -> float:
    if reference.size != candidate.size:
        raise ValueError('Reference and candidate resolutions must match')
    hist = ImageChops.difference(reference.convert('RGB'), candidate.convert('RGB')).histogram()
    total = sum(((idx % 256) ** 2) * n for idx, n in enumerate(hist))
    if not total:
        return float('inf')
    mse = total / (reference.width * reference.height * 3)
    return 10 * math.log10(255 ** 2 / mse)


def evaluate_references(references: list[Path], *, minimum_gain_db: float = 0.1,
                        minimum_pass_fraction: float = 0.8, verify_engine=True,
                        run_inference=inference) -> dict:
    if not references:
        raise ValueError('At least one independent high-resolution reference is required')
    if minimum_gain_db <= 0:
        raise ValueError('Minimum PSNR gain must be positive')
    if not (0 < minimum_pass_fraction <= 1):
        raise ValueError('Minimum pass fraction must be within (0,1]')
    preflight = run_preflight() if verify_engine else None
    samples = []
    for item in references:
        path = Path(item)
        with Image.open(path) as img:
            clean = img.convert('RGB')
        w, h = clean.size
        if w < 512 or h < 512 or w % 4 or h % 4:
            raise ValueError(f'Reference {path.name} requires dimensions >=512 and divisible by four')
        with tempfile.TemporaryDirectory(prefix='blink-real-quality-') as tmp:
            tmp = Path(tmp)
            degraded = clean.resize((w // 4, h // 4), Image.Resampling.LANCZOS)
            degraded = degraded.filter(ImageFilter.GaussianBlur(0.35))
            src, dst = tmp / 'input.png', tmp / 'ai.png'
            degraded.save(src)
            run_inference(src, dst, scale=4)
            if not dst.is_file():
                raise RuntimeError('Genuine AI inference did not produce an output')
            with Image.open(dst) as result:
                result.load()
                if result.size != clean.size:
                    raise RuntimeError(f'AI output size mismatch: {result.size}, expected {clean.size}')
                candidate = result.convert('RGB')
            baseline = degraded.resize(clean.size, Image.Resampling.LANCZOS)
            model_score, baseline_score = psnr(clean, candidate), psnr(clean, baseline)
            gain = model_score - baseline_score
            changed = ImageStat.Stat(ImageChops.difference(candidate, baseline)).mean
            passed = math.isfinite(gain) and gain >= minimum_gain_db and max(changed) >= 0.15
            samples.append({'reference': path.name, 'dimensions': [w, h],
                            'baseline_psnr_db': round(baseline_score, 3),
                            'ai_psnr_db': round(model_score, 3),
                            'gain_db': round(gain, 3), 'changed_pixels_mean': [round(x, 3) for x in changed],
                            'passed': passed})
    success_count = sum(s['passed'] for s in samples)
    fraction = success_count / len(samples)
    return {'status': 'passed' if fraction >= minimum_pass_fraction else 'failed',
            'tested_at_utc': datetime.now(timezone.utc).isoformat(),
            'engine': 'real-esrgan-ncnn-vulkan',
            'genuine_inference_requested': True,
            'gpu_preflight': preflight,
            'model_fingerprint': artifact_fingerprint() if verify_engine else None,
            'min_gain_db': minimum_gain_db,
            'required_pass_fraction': minimum_pass_fraction,
            'passed_samples': success_count, 'total_samples': len(samples),
            'samples': samples,
            'limitations': 'Controlled image super-resolution only; verify faces, low-light and motion separately.'}


def write_report(report: dict, path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False, ensure_ascii=False))
    temporary.replace(path)
