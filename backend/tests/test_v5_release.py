"""V5 production guardrails, output metadata and readiness tests."""
import io
import json
import os
import subprocess
from pathlib import Path
import pytest
from PIL import Image
from fastapi import HTTPException
from app import verify_ai_engine
from app.media import ffprobe
from app.capabilities import public_capabilities

def test_ai_inference_cannot_be_falsely_marked_ready():
    assert not verify_ai_engine.verification_is_current()
    assert public_capabilities()['services']['ai_gpu_verified'] is False
    with pytest.raises(RuntimeError,match='Real-ESRGAN binary'):
        verify_ai_engine.run_preflight()

def test_production_refuses_unverified_ai_before_charge(user,monkeypatch):
    c=user['client']
    before=c.get('/api/me').json()['free_tokens']
    image=io.BytesIO();Image.new('RGB',(128,128),'navy').save(image,format='PNG')
    monkeypatch.setenv('BLINK_ENV','production')
    res=c.post('/api/jobs',data={'kind':'photo','mode':'auto','target':'4k'},files={'file':('input.png',image.getvalue(),'image/png')},headers={'X-CSRF-Token':c.cookies.get('blink_csrf')})
    assert res.status_code==503,res.text
    assert c.get('/api/me').json()['free_tokens']==before

def test_output_metadata_accepts_real_4k_but_upload_limit_does_not(tmp_path):
    path=tmp_path/'sample.mp4'
    # Tiny encoded 4K frame: output QA, not an AI upscale quality claim.
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y',
         '-f','lavfi','-i','color=c=blue:s=3840x2160:r=1:d=1',
         '-frames:v','1','-c:v','libx264','-preset','ultrafast',str(path)]
    subprocess.run(cmd,check=True,timeout=70)
    info=ffprobe(path,validate_upload=False)
    assert (info['width'],info['height'])==(3840,2160)
    with pytest.raises(HTTPException) as e: ffprobe(path,validate_upload=True)
    assert e.value.status_code==422

def test_static_uses_inference_verified_not_installed():
    source=(Path(__file__).resolve().parents[2]/'docs/assets/app.js').read_text()
    assert 'services?.ai_gpu_verified' in source
    assert 'setInterval(pollPaymentState,4000)' in source
    assert 'observedOrders' in source

def test_animated_intro_and_bug_support():
    root=Path(__file__).resolve().parents[2]/'docs'
    html=(root/'index.html').read_text()
    css=(root/'assets/intro.css').read_text()
    assert 'Selamat' in html and 'Datang' in html
    assert 'logo.png' in html
    assert 'https://t.me/Marvel_sh' in html
    assert 'welcome-emerge' in css and 'intro-load' in css

def test_customer_admin_approval_visible_to_studio_without_refresh_auth(user,admin):
    """Real DB integration: user polls with Bearer while admin approves with MFA cookie."""
    import time
    from fastapi.testclient import TestClient
    from app.main import app
    from app.security import _totp
    c=user['client']
    t=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'}).json()['access_token']
    c.cookies.clear()
    h={'Authorization':f'Bearer {t}'}
    o=c.post('/api/studio/payments/orders',headers=h).json()
    img=io.BytesIO();Image.new('RGB',(96,96),'#224488').save(img,format='PNG')
    r=c.post(f"/api/studio/payments/orders/{o['id']}/proof",headers=h,files={'proof':('proof.png',img.getvalue(),'image/png')})
    assert r.status_code==200
    assert c.get('/api/studio/me',headers=h).json()['premium_tokens']==0
    with TestClient(app) as a:
        code=_totp(admin,int(time.time()//30))
        r=a.post('/api/auth/admin/login',json={'email':'admin@example.com','password':'long-admin-password-123','totp':code})
        assert r.status_code==200,r.text
        assert a.get('/api/admin/overview').json()['pending_payments']==1
        r=a.post(f"/api/admin/payments/{o['id']}/approve",json={'funds_verified':True,'verification_ref':'LIVE-GATE-2026-001'},headers={'X-CSRF-Token':a.cookies.get('blink_csrf')})
        assert r.status_code==200,r.text
        assert a.get('/api/admin/overview').json()['pending_payments']==0
    visible=c.get('/api/studio/payments/orders',headers=h).json()
    assert any(x['id']==o['id'] and x['status']=='approved' for x in visible)
    assert c.get('/api/studio/me',headers=h).json()['premium_tokens']==20

def test_high_fps_input_detected_for_normalization(tmp_path):
    path=tmp_path/'high-fps.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                   '-f','lavfi','-i','testsrc2=size=160x90:rate=60:duration=1',
                   '-c:v','libx264','-preset','ultrafast',str(path)],check=True,timeout=30)
    meta=ffprobe(path)
    assert meta['fps']==60


def test_qris_is_hidden_until_authenticated_order():
    root=Path(__file__).resolve().parents[2]/'docs'
    html=(root/'index.html').read_text()
    js=(root/'assets/app.js').read_text()
    assert 'id="premium-qris" class="qris-image" hidden' in html
    assert "$('premium-qris').hidden=!premiumOrder" in js
