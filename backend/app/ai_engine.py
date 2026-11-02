"""Isolated REAL Real-ESRGAN NCNN/Vulkan inference adapter.

This module does not provide a non-AI fallback. Batch mode is supported by the
real realesrgan-ncnn-vulkan CLI, which accepts input/output directories.
"""
import os
import subprocess
import time
import tempfile
from pathlib import Path
from .config import settings
from .capabilities import ai_files_present
from PIL import Image

MODEL_NAME = 'realesrgan-x4plus'


def validate_model_files():
    if not ai_files_present():
        raise RuntimeError('Mesin AI belum tersedia. Pasang binary dan model Real-ESRGAN (.bin dan .param).')
    if os.getenv('BLINK_ENV', 'development') == 'production':
        from .verify_ai_engine import verification_is_current
        if not verification_is_current():
            raise RuntimeError('AI GPU not verified against the deployed model binaries; run real inference preflight first.')
    binary = Path(settings.realesrgan_binary)
    if not os.access(binary, os.X_OK):
        raise RuntimeError('Binary Real-ESRGAN tidak dapat dieksekusi.')
    return binary


def inference(source, destination, *, scale=4, tile=256, timeout=3600, heartbeat=None):
    """Run actual inference on a file OR a directory, without fabricating progress.

    Heartbeat runs periodically while the real executable is alive, so DB worker
    leases are not lost during long GPU operations. The caller validates output.
    """
    binary = validate_model_files()
    if scale not in (2, 3, 4):
        raise ValueError('Invalid Real-ESRGAN output scale')
    if not (1 <= tile <= 1024) or timeout <= 0:
        raise ValueError('Invalid AI tile size or timeout')
    src, dst = Path(source), Path(destination)
    if not src.exists():
        raise FileNotFoundError(src)
    is_batch = src.is_dir()
    if src.resolve() == dst.resolve():
        raise ValueError('AI input and output must be separate')
    # A stale result must never be accepted as proof that the current AI run worked.
    if dst.exists() and (not dst.is_dir() or any(dst.iterdir())):
        raise FileExistsError('AI output path is not empty')
    if is_batch: dst.mkdir(parents=True, exist_ok=True)
    else: dst.parent.mkdir(parents=True, exist_ok=True)
    args = [str(binary), '-i', str(src), '-o', str(dst), '-n', MODEL_NAME,
            '-s', str(scale), '-m', str(settings.realesrgan_models),
            '-t', str(tile), '-f', 'png']
    # Guarantee cleanup if a heartbeat raises, a timeout occurs, or the model
    # itself crashes.  Popen's implicit context manager waits rather than kills
    # an active child when an exception escapes, which could stall the worker.
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            started = time.monotonic()
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError('Real-ESRGAN inference exceeded its configured timeout')
                try:
                    rc = proc.wait(timeout=min(10, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if heartbeat: heartbeat()
            errors.seek(0, os.SEEK_END)
            errors.seek(max(0, errors.tell()-1200))
            error = errors.read().decode('utf-8', errors='replace')
            if rc:
                raise RuntimeError('Real-ESRGAN inference failed: ' + error[-700:])
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    if is_batch:
        originals = sorted(f for f in src.iterdir() if f.suffix.lower() == '.png')
        if not originals:
            raise RuntimeError('No PNG frames supplied to the AI batch')
        expected = {p.name for p in originals}
        produced = {p.name for p in dst.iterdir() if p.is_file() and p.suffix.lower()=='.png' and p.stat().st_size>0}
        if expected != produced:
            raise RuntimeError(f'AI batch incomplete: expected {len(expected)} frames, got {len(produced & expected)}')
        for source_frame in originals:
            with Image.open(source_frame) as original:
                source_size = original.size
            with Image.open(dst/source_frame.name) as result:
                result.verify()
                if result.size != (source_size[0]*scale,source_size[1]*scale):
                    raise RuntimeError('AI returned a frame with unexpected inferred dimensions')
    elif not dst.is_file() or dst.stat().st_size==0:
        raise RuntimeError('Real-ESRGAN returned no usable output file')
    if not is_batch:
        with Image.open(src) as original:
            source_size=original.size
        with Image.open(dst) as result:
            result.verify()
            if result.size!=(source_size[0]*scale,source_size[1]*scale):
                raise RuntimeError('AI photo inference returned unexpected dimensions')
    return dst
