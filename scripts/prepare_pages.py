#!/usr/bin/env python3
"""Publish only the static BLINK customer UI. Never copy private backend files.

BLINK_API_BASE_URL is a PUBLIC HTTPS origin only. No credentials/secrets are read.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs'


def validate_api_base(value: str) -> str:
    value = value.strip()
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.netloc
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('BLINK_API_BASE_URL must be an HTTPS origin only, e.g. https://api.example.com (no path, credentials or query)')
    return f'https://{parsed.netloc}'


def prepare(destination: Path, api_base: str) -> None:
    destination = destination.resolve()
    if destination == ROOT or destination == SOURCE:
        raise ValueError('Refusing to overwrite project source')
    if ROOT in destination.parents:
        relative = destination.relative_to(ROOT)
        if relative.parts[0] not in ('_site', 'dist', 'build'):
            raise ValueError('Publish output must be under _site/, dist/ or build/; never overwrite source')
    base = validate_api_base(api_base)
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError('Invalid output directory')
        shutil.rmtree(destination)
    shutil.copytree(SOURCE, destination, symlinks=False)
    (destination / 'assets/config.js').write_text(
        '// Public API origin only; no credentials or secrets.\n'
        f'window.BLINK_PUBLIC_CONFIG = Object.freeze({{ apiBase: {json.dumps(base)} }});\n',
        encoding='utf-8')
    allowed = {'.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.svg', '.webp', '.ico', '.md', '.txt'}
    public_model = destination / 'assets/tiny-restore-v1.json'
    for path in destination.rglob('*'):
        if path.is_file() and path.suffix.lower() not in allowed and path.name != '.nojekyll' and path != public_model:
            raise RuntimeError(f'Unexpected public file: {path.relative_to(destination)}')
    if not (destination / 'index.html').is_file():
        raise RuntimeError('Missing index.html')
    print(f'BLINK Pages site prepared at: {destination}; API: {base or "not connected (local only)"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / '_site'))
    parser.add_argument('--api-base', default=os.getenv('BLINK_API_BASE_URL', ''))
    args = parser.parse_args()
    prepare(Path(args.output), args.api_base)
