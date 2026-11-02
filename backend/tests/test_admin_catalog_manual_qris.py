"""Payment stays entirely manual; admin catalogue cannot mistake a receipt for a paid account."""
import io,time
from datetime import timedelta
from PIL import Image
from app.db import SessionLocal
from app.models import User, Order, now
from app.security import _totp
from .conftest import with_csrf


def test_catalog_is_admin_only(client, user):
    assert client.get('/api/admin/account-catalog').status_code == 403
    assert client.get('/api/admin/account-catalog?status=invalid').status_code == 403


def test_manual_qris_fake_receipt_rejected_and_catalog_correct(user, admin):
    c=user['client']
    receipt=io.BytesIO()
    Image.new('RGB',(64,64),'white').save(receipt,format='PNG')
    receipt=receipt.getvalue() # plausible image, not evidence money was transferred
    created=c.post('/api/payments/orders',headers=with_csrf(c))
    assert created.status_code==201,created.text
    order=created.json()['id']
    submitted=c.post('/api/payments/orders/'+order+'/proof',headers=with_csrf(c),files={'proof':('screenshot.png',receipt,'image/png')})
    assert submitted.status_code==200,submitted.text
    assert c.get('/api/me').json()['premium_active'] is False
    assert c.get('/api/me').json()['premium_tokens']==0

    c.post('/api/auth/logout',headers=with_csrf(c))
    login=c.post('/api/auth/admin/login',json={'email':'admin@example.com',
                  'password':'long-admin-password-123','totp':_totp(admin,int(time.time()//30))})
    assert login.status_code==200,login.text
    before=c.get('/api/admin/account-catalog').json()
    assert before['counts']=={'premium':0,'former':0,'free':1},before
    assert before['items'][0]['paid_order_count']==0
    assert before['items'][0]['plan_status']=='free'
    assert c.get('/api/admin/account-catalog?status=invalid').status_code == 422
    rejected=c.post(f'/api/admin/payments/{order}/reject',headers=with_csrf(c),json={'reason':'Bukti tidak cocok dengan mutasi rekening'})
    assert rejected.status_code==200,rejected.text
    after=c.get('/api/admin/account-catalog?status=free').json()
    assert after['total']==1 and after['items'][0]['premium_tokens']==0
    assert after['items'][0]['paid_order_count']==0
    assert c.get('/api/admin/account-catalog?status=premium').json()['total']==0
    assert c.post(f'/api/admin/payments/{order}/approve',headers=with_csrf(c),json={'funds_verified':True,'verification_ref':'BANK-FAKE'}).status_code==409


def test_verified_payment_account_catalog_and_expiration(user,admin):
    c=user['client']
    receipt=io.BytesIO()
    Image.new('RGB',(64,64),'white').save(receipt,format='PNG')
    order=c.post('/api/payments/orders',headers=with_csrf(c)).json()['id']
    assert c.post(f'/api/payments/orders/{order}/proof',headers=with_csrf(c),files={'proof':('image.png',receipt.getvalue(),'image/png')}).status_code==200
    c.post('/api/auth/logout',headers=with_csrf(c))
    assert c.post('/api/auth/admin/login',json={'email':'admin@example.com','password':'long-admin-password-123','totp':_totp(admin,int(time.time()//30))}).status_code==200
    no_funds=c.post(f'/api/admin/payments/{order}/approve',headers=with_csrf(c),json={'funds_verified':False,'verification_ref':'TRANSFER-42'})
    assert no_funds.status_code==422
    ready=c.post(f'/api/admin/payments/{order}/approve',headers=with_csrf(c),json={'funds_verified':True,'verification_ref':'TRANSFER-42'})
    assert ready.status_code==200,ready.text
    active=c.get('/api/admin/account-catalog?status=premium').json()
    assert active['total']==1 and active['counts']=={'premium':1,'former':0,'free':0},active
    assert active['items'][0]['paid_order_count']==1
    assert active['items'][0]['premium_tokens']==20
    assert c.get('/api/admin/account-catalog?status=free').json()['total']==0
    with SessionLocal.begin() as db:
        person=db.query(User).filter(User.email=='customer@example.com').one()
        person.premium_expires=now()-timedelta(days=1)
    former=c.get('/api/admin/account-catalog?status=former').json()
    assert former['total']==1 and former['counts']=={'premium':0,'former':1,'free':0},former
    assert former['items'][0]['paid_order_count']==1
    assert former['items'][0]['plan_status']=='former'
