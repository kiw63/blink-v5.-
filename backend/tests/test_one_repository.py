"""Regression tests for one-repository publish without leaking backend assets."""
from pathlib import Path
import importlib.util
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('blink_prepare_pages', ROOT/'scripts/prepare_pages.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_only_docs_go_to_public_pages(tmp_path):
    out = tmp_path/'site'
    mod.prepare(out, 'https://api.example.com')
    assert (out/'index.html').is_file()
    assert (out/'assets/logo.png').is_file()
    assert (out/'assets/qris-nanzera.jpg').is_file()
    assert (out/'.nojekyll').is_file()
    assert 'https://api.example.com' in (out/'assets/config.js').read_text()
    assert not (out/'backend').exists()
    assert not (out/'frontend').exists()
    assert not (out/'.env').exists()
    assert not any(p.suffix in ('.py', '.key', '.pem') for p in out.rglob('*') if p.is_file())


def test_api_setting_rejects_secret_in_url():
    for value in ('http://example.org','https://user:password@api.example.com',
                  'https://api.example.com/api', 'https://api.example.com/?token=secret',
                  'https://api.example.com/#password'):
        with pytest.raises(ValueError):
            mod.validate_api_base(value)


def test_no_overwrite_source_files():
    with pytest.raises(ValueError):
        mod.prepare(ROOT/'backend', '')
    with pytest.raises(ValueError):
        mod.prepare(ROOT/'docs', '')


def test_only_one_official_deployment_workflow():
    assert [p.name for p in (ROOT/'.github/workflows').glob('*.yml')] == ['blink.yml']
    workflow = (ROOT/'.github/workflows/blink.yml').read_text()
    assert 'needs: [validate, browser]' in workflow
    assert 'path: _site' in workflow
    assert 'vars.BLINK_API_BASE_URL' in workflow
