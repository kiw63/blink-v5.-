"""Public, non-secret capabilities shared with the browser and admin diagnostics."""
import shutil
from pathlib import Path
from .config import settings

COSTS = {'photo': 1, 'live_photo': 2, 'video': 3, 'cinematic': 0}
PHOTO_MODES = ['auto', 'hd', 'sharp', '4k', 'portrait', 'night', 'cinema']
VIDEO_MODES = ['auto', '1080p', '2k', '4k']
CINEMA_MODES = ['natural', 'ultra-clear', 'film-contrast', 'golden-hour', 'night-cinema']

def ai_files_present():
    binary = Path(settings.realesrgan_binary)
    models = Path(settings.realesrgan_models)
    return (binary.is_file() and binary.stat().st_size > 0
            and (models / 'realesrgan-x4plus.bin').is_file()
            and (models / 'realesrgan-x4plus.param').is_file())

def public_capabilities():
    ffmpeg = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    ai = ai_files_present()
    from .verify_ai_engine import verification_is_current
    ai_verified = verification_is_current()
    return {
        'api_version': 2,
        'timezone': 'Asia/Jakarta',
        'currency': 'IDR',
        'free_tokens_per_day': 3,
        'premium': {'price_idr': 20000, 'duration_days': 30, 'tokens': 20},
        'costs': COSTS,
        'modes': {'photo': PHOTO_MODES, 'video': VIDEO_MODES, 'cinematic': CINEMA_MODES},
        'limits': {'photo_mb': settings.max_photo_mb, 'video_mb': settings.max_video_mb,
                   'video_seconds': settings.max_video_seconds, 'video_max_input': '1920x1080@30fps'},
        'services': {
            'ai_models_installed': ai,
            'ai_gpu_verified': ai_verified,  # Verified by real model inference with matching binary/model hashes.
            'cinematic_ffmpeg_available': ffmpeg,
            'camera': 'browser_permission_required',
            'live_photo': 'still_plus_recorded_clip',
            'qris_image_configured': Path(settings.qris_path).is_file(),
            'payment_verification': 'manual_bank_confirmation',
            'email_configured': bool(settings.smtp_host and settings.smtp_from),
        },
    }
