"""API/UI contract, replay-safe order flow, privacy and media compatibility."""
import io
from pathlib import Path
from PIL import Image
from app.capabilities import COSTS, PHOTO_MODES, VIDEO_MODES
from app.db import SessionLocal
from app.models import User, Order
from .conftest import with_csrf

def sample(fmt='JPEG'):
    out=io.BytesIO(); Image.new('RGB',(160,100),'navy').save(out,format=fmt)
    return out.getvalue()

def test_public_capabilities_match_server_billing(client):
    from app.billing import COST as BILLING
    r=client.get('/api/public/capabilities')
    assert r.status_code==200
    c=r.json()
    assert c['api_version']==client.get('/api/health').json()['api_version']==2
    assert c['timezone']=='Asia/Jakarta'
    assert c['costs']==COSTS==BILLING
    assert set(c['modes']['photo'])==set(PHOTO_MODES)
    assert set(c['modes']['video'])==set(VIDEO_MODES)
    assert c['free_tokens_per_day']==3
    assert c['premium']=={'price_idr':20000,'duration_days':30,'tokens':20}
    assert c['services']['payment_verification']=='manual_bank_confirmation'
    assert c['services']['ai_gpu_verified'] is False
    assert 'smtp_password' not in str(c).lower()

def test_repeat_checkout_reuses_pending_order(user):
    c=user['client']; header=with_csrf(c)
    first=c.post('/api/payments/orders',headers=header).json()
    second=c.post('/api/payments/orders',headers=header).json()
    assert first['id']==second['id'] and first['status']=='created'
    proof=c.post(f"/api/payments/orders/{first['id']}/proof",headers=header,
                 files={'proof':('real-check.jpg',sample(),'image/jpeg')})
    assert proof.status_code==200,proof.text
    third=c.post('/api/payments/orders',headers=header).json()
    assert third['id']==first['id'] and third['status']=='submitted'
    assert len(c.get('/api/payments/orders').json())==1
    with SessionLocal() as db:
        order=db.query(Order).filter_by(id=first['id']).one()
        assert order.proof_key.endswith('.png')
    result=c.get(f"/api/payments/orders/{first['id']}/proof")
    assert result.status_code==200
    assert result.headers['content-type'].startswith('image/png')
    im=Image.open(io.BytesIO(result.content)); assert im.format=='PNG'
    assert c.get('/api/me').json()['premium_tokens']==0

def test_user_cannot_read_another_users_proof(user):
    c=user['client'];order=c.post('/api/payments/orders',headers=with_csrf(c)).json()
    c.post(f"/api/payments/orders/{order['id']}/proof",headers=with_csrf(c),
           files={'proof':('proof.png',sample('PNG'),'image/png')})
    c.post('/api/auth/logout',headers=with_csrf(c))
    from app.security import hash_password
    from app.billing import today_wib
    from app.models import now
    with SessionLocal.begin() as db:
        db.add(User(email='someoneelse@example.com',name='Other user',password_hash=hash_password('otheruserpassword123'),
                    role='user',email_verified_at=now(),free_day=today_wib()))
    login=c.post('/api/auth/login',json={'email':'someoneelse@example.com','password':'otheruserpassword123'})
    assert login.status_code==200
    assert c.get(f"/api/payments/orders/{order['id']}/proof").status_code==404
    assert c.get('/api/admin/settings').status_code==403

def test_invalid_csrf_and_bad_origin_do_not_create_orders(user):
    c=user['client']
    assert c.post('/api/payments/orders',headers={'X-CSRF-Token':'invalid'}).status_code==403
    assert c.post('/api/payments/orders',headers={**with_csrf(c),'Origin':'https://attacker.invalid'}).status_code==403
    assert c.get('/api/payments/orders').json()==[]

def test_proof_validation_rejects_nondisplayable_files(user):
    c=user['client'];h=with_csrf(c)
    order=c.post('/api/payments/orders',headers=h).json()
    result=c.post(f"/api/payments/orders/{order['id']}/proof",headers=h,
                  files={'proof':('fake.jpg',b'NOT ACTUALLY AN IMAGE','image/jpeg')})
    assert result.status_code==422
    assert c.get('/api/payments/orders').json()[0]['status']=='created'
    assert c.get('/api/me').json()['premium_tokens']==0

def test_payment_reference_cannot_be_reused_across_orders(user,admin):
    """Database uniqueness and app checks prevent a single receipt funding two accounts."""
    import time
    from app.security import _totp
    c=user['client']; h=with_csrf(c)
    order1=c.post('/api/payments/orders',headers=h).json()
    c.post(f"/api/payments/orders/{order1['id']}/proof",headers=h,
           files={'proof':('receipt1.png',sample('PNG'),'image/png')})
    with SessionLocal.begin() as db:
        from app.security import hash_password
        from app.models import now
        from app.billing import today_wib
        db.add(User(email='anotherpayer@example.com',name='Another payer',password_hash=hash_password('anotherpayerpassword123'),
                    role='user',email_verified_at=now(),free_day=today_wib()))
    c.post('/api/auth/logout',headers=with_csrf(c))
    assert c.post('/api/auth/login',json={'email':'anotherpayer@example.com','password':'anotherpayerpassword123'}).status_code==200
    order2=c.post('/api/payments/orders',headers=with_csrf(c)).json()
    c.post(f"/api/payments/orders/{order2['id']}/proof",headers=with_csrf(c),
           files={'proof':('receipt2.png',sample('PNG'),'image/png')})
    c.post('/api/auth/logout',headers=with_csrf(c))
    code=_totp(admin,int(time.time()//30))
    assert c.post('/api/auth/admin/login',json={'email':'admin@example.com','password':'long-admin-password-123','totp':code}).status_code==200
    h=with_csrf(c)
    request={'funds_verified':True,'verification_ref':'BANK-UNIQUE-123'}
    approved=c.post(f"/api/admin/payments/{order1['id']}/approve",headers=h,json=request)
    assert approved.status_code==200, approved.text
    replay=c.post(f"/api/admin/payments/{order2['id']}/approve",headers=h,json=request)
    assert replay.status_code==409, replay.text
    with SessionLocal() as db:
        a=db.query(User).filter_by(email='customer@example.com').one()
        b=db.query(User).filter_by(email='anotherpayer@example.com').one()
        assert a.premium_tokens==20 and b.premium_tokens==0
        assert db.query(Order).filter_by(id=order2['id']).one().status=='submitted'

def test_premium_renewal_replaces_tokens_not_accumulates(user):
    from app.billing import activate_membership
    from app.models import TokenEvent
    with SessionLocal.begin() as db:
        u=db.query(User).filter_by(email='customer@example.com').with_for_update().one()
        first=Order(user_id=u.id,status='approved'); db.add(first);db.flush()
        assert activate_membership(db,u,first)
        u.premium_tokens=6
        second=Order(user_id=u.id,status='approved');db.add(second);db.flush()
        assert activate_membership(db,u,second)
        assert u.premium_tokens==20
        assert u.membership_revision==2
        assert not activate_membership(db,u,second)
    with SessionLocal() as db:
        events=list(db.query(TokenEvent).filter_by(order_id=second.id).all())
        assert sum(e.premium_delta for e in events)==14
        assert {e.event for e in events}=={'premium_replaced','premium_activation'}
