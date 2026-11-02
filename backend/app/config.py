import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./blink-dev.db'
    app_secret: str = 'MUST_CHANGE_FOR_PRODUCTION'
    mfa_encryption_key: str = ''
    public_origin: str = 'http://localhost:3000'
    # Optional extra browser origin for a GitHub Pages static Studio, e.g. https://owner.github.io
    studio_origin: str = ''
    studio_public_url: str = ''  # Full GitHub Pages URL including repository subpath; links only
    secure_cookies: bool = False
    media_root: str = '/data/media'
    qris_path: str = '/app/assets/qris-nanzera.jpg'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    s3_bucket: str = ''
    s3_endpoint_url: str = ''
    s3_region: str = 'ap-southeast-1'
    s3_access_key: str = ''
    s3_secret_key: str = ''
    realesrgan_binary: str = '/usr/local/bin/realesrgan-ncnn-vulkan'
    realesrgan_models: str = '/opt/realesrgan/models'
    max_photo_mb: int = 16
    max_video_mb: int = 80
    max_video_seconds: int = 20
    cookie_days: int = 14
    enable_docs: bool = False

settings = Settings()

def assert_production_config():
    if os.getenv('BLINK_ENV', 'development') == 'production':
        if len(settings.app_secret) < 48 or settings.app_secret == 'MUST_CHANGE_FOR_PRODUCTION':
            raise RuntimeError('APP_SECRET must be a unique secure secret')
        if not settings.mfa_encryption_key:
            raise RuntimeError('MFA_ENCRYPTION_KEY is required')
        if not settings.secure_cookies:
            raise RuntimeError('SECURE_COOKIES must be true in production')
        if settings.database_url.startswith('sqlite'):
            raise RuntimeError('Use PostgreSQL in production')
        if not settings.public_origin.startswith('https://'):
            raise RuntimeError('PUBLIC_ORIGIN must use HTTPS')
        if not (settings.smtp_host and settings.smtp_from):
            raise RuntimeError('SMTP required for real production email verification and recovery')
        if not settings.s3_bucket:
            raise RuntimeError('S3_BUCKET is required for production private media')
