#!/usr/bin/env python3
"""Guardrails for the single-repository distribution and GitHub Pages publishing."""
import ast
from pathlib import Path
import importlib.util
root = Path(__file__).resolve().parents[1]
required = [
    'docs/index.html','docs/assets/config.js','docs/assets/app.js',
    'docs/assets/logo.png','docs/assets/qris-nanzera.jpg',
    'backend/app/main.py','backend/app/worker.py','backend/alembic.ini',
    'frontend/app/platform.tsx','frontend/next.config.js',
    'docker-compose.yml','.github/workflows/blink.yml',
    'scripts/prepare_pages.py','.env.example'
]
for name in required:
    assert (root/name).is_file(), f'Missing package component: {name}'
assert not (root/'index.html').exists(), 'Do not duplicate the GitHub Pages homepage at repository root'
assert not (root/'assets').exists(), 'Do not duplicate docs/assets at repository root'
assert not (root/'.env').exists(), 'The private .env must never be included in the release'
assert len(list((root/'.github/workflows').glob('*.yml'))) == 1, 'Use only one official CI/deploy workflow'
workflow = (root/'.github/workflows/blink.yml').read_text()
for token in ('scripts/check_unified_repo.py','scripts/check_static.py','scripts/check_contract.py','backend/requirements.txt','pytest','scripts/prepare_pages.py','upload-pages-artifact','deploy-pages','needs:'):
    assert token in workflow, f'Missing deploy/test contract: {token}'
assert 'path: _site' in workflow, 'Only the curated static output may be uploaded to GitHub Pages'
contents = (root/'docs/index.html').read_text()
assert 'https://t.me/Marvel_sh' in contents, 'Developer support link missing'
assert '<script type="module" src="./assets/app.js"></script>' in contents
mod = importlib.util.spec_from_file_location('pages_build', root/'scripts/prepare_pages.py')
module = importlib.util.module_from_spec(mod); mod.loader.exec_module(module)
for invalid in ['http://example.com','https://user:password@example.com','https://example.com/api','https://example.com/?key=x','javascript:alert(1)']:
    try: module.validate_api_base(invalid)
    except ValueError: pass
    else: raise AssertionError('Unsafe public API URL was accepted: '+invalid)
assert module.validate_api_base('https://api.example.com/') == 'https://api.example.com'
print('UNIFIED REPO PASS: one publish root, one workflow, secure API-origin config and all services present.')
