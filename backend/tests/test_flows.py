import io,subprocess,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from PIL import Image
from app.db import SessionLocal
from app.models import User,Job,Order
from app.billing import today_wib,refresh_balances,reserve_tokens,refund_tokens,activate_membership
from app.security import _totp
from app.worker import claim,process
from .conftest import with_csrf

def png():
    im=Image.new('RGB',(72,54),'#4466aa')
    buffer=io.BytesIO();im.save(buffer,format='PNG');return buffer.getvalue()

def test_register_verification_and_login_requirement(client):
    x=client.post('/api/auth/register',json={'name':'Nadia','email':'nadia@example.com','password':'verylongpassword123'})
    assert x.status_code==201
    y=client.post('/api/auth/login',json={'email':'nadia@example.com','password':'verylongpassword123'})
    assert y.status_code==403
    assert client.get('/api/me').status_code==401

def test_cookie_csrf_token_and_daily_three(user):
    client=user['client'];info=client.get('/api/me')
    assert info.status_code==200
    assert info.json()['free_tokens']==3
    assert info.json()['premium_tokens']==0
    assert client.post('/api/payments/orders').status_code==403
    r=client.post('/api/payments/orders',headers=with_csrf(client))
    assert r.status_code==201
    assert r.json()['amount']==20000
    r=client.post('/api/auth/logout',headers=with_csrf(client))
    assert r.status_code==204
    assert client.get('/api/me').status_code==401

def test_reservation_photo_failure_refunds(user):
    c=user['client']
    r=c.post('/api/jobs',headers=with_csrf(c),data={'kind':'photo','mode':'auto','target':'4k'},files={'file':('picture.png',png(),'image/png')})
    assert r.status_code==201,r.text
    jid=r.json()['id']
    assert c.get('/api/me').json()['free_tokens']==2
    assert claim()==jid
    process(jid) # actual worker fails, because no Real-ESRGAN binary; no fake result
    item=c.get('/api/jobs/'+jid).json()
    assert item['status']=='failed' and 'AI' in item['error']
    assert c.get('/api/me').json()['free_tokens']==3
    assert item['download_url'] is None

def test_invalid_file_does_not_charge(user):
    c=user['client']
    r=c.post('/api/jobs',headers=with_csrf(c),data={'kind':'photo','mode':'auto'},files={'file':('notpicture.png',b'bad payload','image/png')})
    assert r.status_code==422
    assert c.get('/api/me').json()['free_tokens']==3

def test_livephoto_two_tokens_and_video_three(user):
    c=user['client']
    x=c.post('/api/jobs',headers=with_csrf(c),data={'kind':'video','mode':'auto'},files={'file':('image.png',png(),'image/png')})
    assert x.status_code==415
    with SessionLocal.begin() as db:
        u=db.query(User).filter_by(email='customer@example.com').with_for_update().one()
        job=Job(user_id=u.id,kind='live_photo',mode='auto',input_key='fake')
        db.add(job);db.flush();reserve_tokens(db,u,job)
        assert job.reserved_free==2 and u.free_tokens==1
    assert c.get('/api/me').json()['free_tokens']==1

def test_midnight_reset_no_accumulation(user):
    with SessionLocal.begin() as db:
        u=db.query(User).filter_by(email='customer@example.com').with_for_update().one()
        u.free_tokens=1
        u.free_day='2026-10-29'
        refresh_balances(db,u,datetime(2026,11,1,1,tzinfo=timezone.utc))
        assert u.free_tokens==3
        refresh_balances(db,u,datetime(2026,11,2,1,tzinfo=timezone.utc))
        assert u.free_tokens==3
    assert user['client'].get('/api/me').json()['free_tokens']==3

def test_admin_mfa_required_and_idempotent_payment(user,admin):
    c=user['client']
    order=c.post('/api/payments/orders',headers=with_csrf(c)).json()
    r=c.post('/api/payments/orders/'+order['id']+'/proof',headers=with_csrf(c),files={'proof':('proof.png',png(),'image/png')})
    assert r.status_code==200,r.text
    assert c.get('/api/me').json()['premium_tokens']==0
    assert c.post('/api/admin/payments/'+order['id']+'/approve',headers=with_csrf(c),json={'funds_verified':True,'verification_ref':'BANK-1'}).status_code==403
    c.post('/api/auth/logout',headers=with_csrf(c))
    bad=c.post('/api/auth/login',json={'email':'admin@example.com','password':'long-admin-password-123'})
    assert bad.status_code==403
    wrong=c.post('/api/auth/admin/login',json={'email':'admin@example.com','password':'long-admin-password-123','totp':'000000'})
    assert wrong.status_code==401
    code=_totp(admin,int(time.time()//30))
    login=c.post('/api/auth/admin/login',json={'email':'admin@example.com','password':'long-admin-password-123','totp':code})
    assert login.status_code==200,login.text
    hdr=with_csrf(c)
    missing=c.post('/api/admin/payments/'+order['id']+'/approve',headers=hdr,json={'funds_verified':False,'verification_ref':'X'})
    assert missing.status_code==422
    ok=c.post('/api/admin/payments/'+order['id']+'/approve',headers=hdr,json={'funds_verified':True,'verification_ref':'BANK-1'})
    assert ok.status_code==200,ok.text
    repeat=c.post('/api/admin/payments/'+order['id']+'/approve',headers=hdr,json={'funds_verified':True,'verification_ref':'BANK-1'})
    assert repeat.status_code==200
    with SessionLocal() as db:
        u=db.query(User).filter_by(email='customer@example.com').one()
        assert u.premium_tokens==20 and u.membership_revision==1
        assert u.premium_expires-u.premium_starts==timedelta(days=30)
        assert db.query(Order).filter_by(id=order['id']).one().status=='approved'

def test_premium_mixed_token_and_expiry(user):
    with SessionLocal.begin() as db:
        u=db.query(User).filter_by(email='customer@example.com').with_for_update().one()
        order=Order(user_id=u.id,status='approved',proof_key='proof.png')
        db.add(order);db.flush()
        activate_membership(db,u,order)
        u.free_tokens=2
        j=Job(user_id=u.id,kind='video',mode='auto',input_key='fake')
        db.add(j);db.flush();reserve_tokens(db,u,j)
        assert (j.reserved_free,j.reserved_premium)==(2,1)
        assert (u.free_tokens,u.premium_tokens)==(0,19)
        refund_tokens(db,u,j)
        assert (u.free_tokens,u.premium_tokens)==(2,20)
        u.premium_expires=datetime.now(timezone.utc)-timedelta(seconds=1)
        refresh_balances(db,u)
        assert u.premium_tokens==0

def test_qris_asset_is_supplied_image(client):
    res=client.get('/api/public/qris')
    assert res.status_code==200 and res.headers['content-type'].startswith('image/jpeg')
    assert len(res.content)>100_000

def test_real_cinematic_ffmpeg_with_download(user):
    c=user['client']
    from shutil import which
    if not which('ffmpeg') or not which('ffprobe'):pytest.skip('ffmpeg not installed')
    import tempfile
    with tempfile.TemporaryDirectory() as dirname:
        clip=Path(dirname)/'real.mp4'
        proc=subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=160x120:rate=15',
                             '-f','lavfi','-i','sine=frequency=300:sample_rate=44100',
                             '-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(clip)],timeout=40)
        assert proc.returncode==0
        x=c.post('/api/jobs',headers=with_csrf(c),data={'kind':'cinematic','mode':'golden-hour'},files={'file':('real.mp4',clip.read_bytes(),'video/mp4')})
        assert x.status_code==201,x.text
        jid=x.json()['id']
        assert c.get('/api/me').json()['free_tokens']==3
        assert claim()==jid
        process(jid)
        obj=c.get('/api/jobs/'+jid).json()
        assert obj['status']=='completed',obj
        output=c.get('/api/jobs/'+jid+'/download')
        assert output.status_code==200 and len(output.content)>10_000
        assert output.content[:4]!=b'FAKE'
        assert c.get('/api/me').json()['free_tokens']==3
