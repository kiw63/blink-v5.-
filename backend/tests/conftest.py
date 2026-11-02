import os,tempfile
from pathlib import Path
from cryptography.fernet import Fernet

_root=Path(tempfile.mkdtemp(prefix='blink-tests-'))
os.environ['DATABASE_URL']='sqlite:///'+str(_root/'test.db')
os.environ['MEDIA_ROOT']=str(_root/'media')
os.environ['QRIS_PATH']=str(Path(__file__).resolve().parents[1]/'assets/qris-nanzera.jpg')
os.environ['APP_SECRET']='test-only-secret-must-not-be-used-in-prod-very-long'
os.environ['MFA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['PUBLIC_ORIGIN']='http://localhost:3000'
os.environ['STUDIO_ORIGIN']='https://blink-test.github.io'
os.environ['STUDIO_PUBLIC_URL']='https://blink-test.github.io/BLINK'
os.environ['BLINK_ENV']='development'
os.environ['REALESRGAN_BINARY']=str(_root/'missing-upscaler')
os.environ['REALESRGAN_MODELS']=str(_root/'missing-models')
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base,engine,SessionLocal
from app.models import User,now
from app.security import hash_password,encrypt_totp,totp_secret
from app.billing import today_wib
import pytest

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield

@pytest.fixture
def client():
    with TestClient(app) as c: yield c

@pytest.fixture
def user(client):
    result=client.post('/api/auth/register',json={'name':'Test Customer','email':'customer@example.com','password':'supersecret1234'})
    assert result.status_code==201,result.text
    with SessionLocal.begin() as db:
        u=db.query(User).filter_by(email='customer@example.com').one()
        u.email_verified_at=now()
    login=client.post('/api/auth/login',json={'email':'customer@example.com','password':'supersecret1234'})
    assert login.status_code==200,login.text
    return {'client':client,'csrf':client.cookies.get('blink_csrf')}

@pytest.fixture
def admin():
    secret=totp_secret()
    with SessionLocal.begin() as db:
        db.add(User(name='Test Admin',email='admin@example.com',password_hash=hash_password('long-admin-password-123'),
            role='admin',email_verified_at=now(),free_day=today_wib(),mfa_secret_enc=encrypt_totp(secret)))
    return secret

def with_csrf(client):return {'X-CSRF-Token':client.cookies.get('blink_csrf')}
