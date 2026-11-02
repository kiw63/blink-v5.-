"""GitHub Pages Studio must use scoped bearer tokens, never a public password."""
import io, jwt
from PIL import Image
from app.config import settings
from app.models import User
from app.db import SessionLocal
from app.models import now

def test_studio_login_job_and_download_access(user):
    c=user['client']
    session=c.post('/api/studio/login', json={'email':'customer@example.com','password':'supersecret1234'})
    assert session.status_code==200,session.text
    token=session.json()['access_token']
    headers={'Authorization':f'Bearer {token}'}
    assert session.json()['expires_in']==2700
    assert c.get('/api/studio/me',headers=headers).json()['free_tokens']==3
    image=Image.new('RGB',(80,60),'#334466');out=io.BytesIO();image.save(out,format='PNG')
    job=c.post('/api/studio/jobs',headers=headers,data={'kind':'photo','mode':'hd','target':'4k'},
               files={'file':('photo.png',out.getvalue(),'image/png')})
    assert job.status_code==201,job.text
    jid=job.json()['id']
    assert c.get(f'/api/studio/jobs/{jid}',headers=headers).status_code==200
    assert c.get('/api/studio/jobs',headers=headers).status_code==200
    assert c.get(f'/api/studio/jobs/{jid}/download',headers=headers).status_code==404
    assert c.post('/api/studio/jobs',data={'kind':'photo','mode':'hd'},files={'file':('photo.png',out.getvalue(),'image/png')}).status_code in (401,403)

def test_studio_token_scope_and_admin_restriction(user,admin):
    c=user['client']
    session=c.post('/api/studio/login',json={'email':'admin@example.com','password':'long-admin-password-123'})
    assert session.status_code==401  # admin MUST use MFA on full backend, never static frontend
    normal=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'})
    token=normal.json()['access_token']
    assert c.get('/api/admin/overview',headers={'Authorization':f'Bearer {token}'}).status_code==403  # existing normal-user cookie cannot authorize admin
    assert c.get('/api/me',headers={'Authorization':f'Bearer {token}'}).status_code==200  # because cookie fixture persists
    c.cookies.clear()
    assert c.get('/api/me',headers={'Authorization':f'Bearer {token}'}).status_code==401
    bad=jwt.encode({'sub':'missing','scope':'other','exp':int(now().timestamp())+100},settings.app_secret,algorithm='HS256')
    assert c.get('/api/studio/me',headers={'Authorization':f'Bearer {bad}'}).status_code==401

def test_studio_unverified_account_cannot_log_in(client):
    r=client.post('/api/auth/register',json={'name':'Unverified','email':'unverified@example.com','password':'a-long-password-here'})
    assert r.status_code==201
    result=client.post('/api/studio/login',json={'email':'unverified@example.com','password':'a-long-password-here'})
    assert result.status_code==401

def test_studio_cors_allowed_and_disallowed(user):
    c=user['client']
    okay=c.options('/api/studio/login',headers={
        'Origin':'https://blink-test.github.io',
        'Access-Control-Request-Method':'POST',
        'Access-Control-Request-Headers':'authorization,content-type'})
    assert okay.status_code==200,okay.text
    assert okay.headers.get('access-control-allow-origin')=='https://blink-test.github.io'
    bad=c.post('/api/studio/login',headers={'Origin':'https://evil.example'},
               json={'email':'customer@example.com','password':'supersecret1234'})
    assert bad.status_code==403

def test_studio_verify_email_link_uses_github_subpath(client,monkeypatch):
    from app import main
    from app.db import SessionLocal
    from app.models import User
    captured=[]
    monkeypatch.setattr(main,'send_email',lambda who,subject,body:captured.append(body) or True)
    created=client.post('/api/auth/register',json={'name':'Static User','email':'new_static@example.com',
                                                  'password':'password-long-enough'})
    assert created.status_code==201
    assert captured and 'https://blink-test.github.io/BLINK/?verify=' in captured[0]
