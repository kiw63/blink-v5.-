"""Important real cross-origin auth / QRIS verification contracts for v4."""
import io
from PIL import Image

def png():
    f=io.BytesIO();Image.new('RGB',(128,96),'#3927aa').save(f,format='PNG');return f.getvalue()

def test_cross_origin_studio_bearer_without_any_cookies(user):
    c=user['client'];token=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'}).json()['access_token']
    c.cookies.clear();auth={'Authorization':'Bearer '+token}
    me=c.get('/api/studio/me',headers=auth)
    assert me.status_code==200,me.text
    assert me.json()['free_tokens']==3
    assert c.get('/api/me',headers=auth).status_code==401
    created=c.post('/api/studio/jobs',headers=auth,data={'kind':'photo','mode':'auto','target':'4k'},files={'file':('source.png',png(),'image/png')})
    assert created.status_code==201,created.text
    assert created.json()['status']=='queued'
    assert c.get('/api/studio/jobs',headers=auth).status_code==200
    assert c.get('/api/admin/users',headers=auth).status_code==401

def test_payment_creation_and_proof_with_bearer(user):
    c=user['client'];token=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'}).json()['access_token']
    c.cookies.clear();auth={'Authorization':'Bearer '+token}
    noauth=c.post('/api/studio/payments/orders')
    assert noauth.status_code in (401,403)
    order=c.post('/api/studio/payments/orders',headers=auth)
    assert order.status_code==201,order.text
    assert order.json()['amount']==20000
    order_id=order.json()['id']
    assert c.post('/api/studio/payments/orders',headers=auth).json()['id']==order_id
    proof=c.post(f'/api/studio/payments/orders/{order_id}/proof',headers=auth,files={'proof':('pay.png',png(),'image/png')})
    assert proof.status_code==200,proof.text
    assert proof.json()['order']['status']=='submitted'
    orders=c.get('/api/studio/payments/orders',headers=auth)
    assert orders.status_code==200 and orders.json()[0]['status']=='submitted'
    second=c.post(f'/api/studio/payments/orders/{order_id}/proof',headers=auth,files={'proof':('pay.png',png(),'image/png')})
    assert second.status_code==409

def test_studio_token_cannot_be_used_as_cookie_or_admin(user):
    c=user['client'];token=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'}).json()['access_token']
    c.cookies.clear()
    c.cookies.set('blink_session',token)
    assert c.get('/api/me').status_code==401
    assert c.get('/api/admin/overview').status_code==401
    assert c.get('/api/studio/me').status_code==401

def test_studio_logout_revokes_session_on_server(user):
    c=user['client'];session=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'})
    assert session.status_code==200
    token=session.json()['access_token'];auth={'Authorization':'Bearer '+token};c.cookies.clear()
    assert c.get('/api/studio/me',headers=auth).status_code==200
    assert c.post('/api/studio/logout',headers=auth).status_code==204
    assert c.get('/api/studio/me',headers=auth).status_code==401

def test_studio_session_revoked_after_password_change(user):
    c=user['client'];session=c.post('/api/studio/login',json={'email':'customer@example.com','password':'supersecret1234'})
    token=session.json()['access_token']
    assert c.get('/api/studio/me',headers={'Authorization':'Bearer '+token}).status_code==200
    csrf={'X-CSRF-Token':c.cookies.get('blink_csrf')}
    changed=c.post('/api/account/password',json={'current_password':'supersecret1234','new_password':'brand-new-long-password-2026'},headers=csrf)
    assert changed.status_code==200,changed.text
    assert c.get('/api/studio/me',headers={'Authorization':'Bearer '+token}).status_code==401
