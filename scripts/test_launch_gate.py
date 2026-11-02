import importlib.util
from pathlib import Path
from unittest.mock import patch
import json
import pytest

file=Path(__file__).with_name('launch_gate.py')
spec=importlib.util.spec_from_file_location('launch_gate',file)
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

@pytest.mark.parametrize('value,name',[
    ('http://example.com','api'),('https://user:pass@example.com','api'),
    ('https://example.com/path','api'),('https://example.com?token=x','api'),
    ('javascript:alert(1)','site')
])
def test_rejects_unsafe_urls(value,name):
    with pytest.raises(ValueError):g.require_https(value,name)

def test_flags_fake_gpu_inference():
    with pytest.raises(RuntimeError,match='not installed'):
        g.validate_ai({'services':{'ai_models_installed':False,'ai_gpu_verified':False}})
    with pytest.raises(RuntimeError,match='missing'):
        g.validate_ai({'services':{'ai_models_installed':True,'ai_gpu_verified':False}})

def test_does_not_mistake_payment_config_for_actual_payment():
    item=g.validate_payment_config({'services':{'email_configured':True},
        'premium':{'price_idr':20000,'tokens':20,'duration_days':30}})
    assert 'does NOT prove' in item['warning']

def test_go_live_fail_closed_without_real_urls(tmp_path):
    with patch.object(g,'get',side_effect=RuntimeError('No live host')):
        with patch('builtins.print'):
            rc=g.main(['--site','https://user.github.io/blink/','--api','https://api.example.com',
                       '--admin','https://admin.example.com','--report',str(tmp_path/'result.json')])
    data=json.loads((tmp_path/'result.json').read_text())
    assert rc==1 and not data['automated_smoke_passed']
    assert not data['commercial_go_live_verified']
    assert data['results']['ai_photo_video_real_quality_4k']['status']=='MANUAL_REQUIRED'
