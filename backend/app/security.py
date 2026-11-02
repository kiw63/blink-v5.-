import base64, hashlib, hmac, os, secrets, struct, time
from datetime import timedelta, timezone, datetime
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from cryptography.fernet import Fernet
import jwt
from fastapi import HTTPException, Request, Depends
from sqlalchemy.orm import Session as DBSession
from .models import User, Session, AuthToken, now
from .db import get_db
from .config import settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

def hash_password(value): return password_hasher.hash(value)
def verify_password(value, digest):
    try: return password_hasher.verify(digest, value)
    except (VerifyMismatchError, VerificationError, Exception): return False

def digest_token(raw): return hashlib.sha256(raw.encode()).hexdigest()
def make_auth_token(db, user, purpose, minutes):
    raw = secrets.token_urlsafe(36)
    db.add(AuthToken(user_id=user.id, digest=digest_token(raw), purpose=purpose, expires_at=now()+timedelta(minutes=minutes)))
    return raw

def aware(d):
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d

def totp_secret(): return base64.b32encode(os.urandom(20)).decode().rstrip('=')
def _totp(secret, interval):
    key = base64.b32decode(secret + '=' * ((8-len(secret)%8)%8), casefold=True)
    msg = struct.pack('>Q', interval)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = (struct.unpack('>I',digest[offset:offset+4])[0] & 0x7fffffff) % 1000000
    return f'{number:06d}'
def verify_totp(secret, code, instant=None):
    if not isinstance(code,str) or not(code.isdecimal() and len(code)==6): return False
    counter = int((instant if instant is not None else time.time())//30)
    return any(hmac.compare_digest(_totp(secret,counter+i),code) for i in (-1,0,1))
def encrypt_totp(secret):
    if not settings.mfa_encryption_key: raise RuntimeError('Set MFA_ENCRYPTION_KEY')
    return Fernet(settings.mfa_encryption_key.encode()).encrypt(secret.encode()).decode()
def decrypt_totp(data): return Fernet(settings.mfa_encryption_key.encode()).decrypt(data.encode()).decode()

def issue_session(db, user):
    session = Session(user_id=user.id, expires_at=now()+timedelta(days=settings.cookie_days))
    db.add(session); db.flush()
    bearer = jwt.encode({'sub':user.id,'sid':session.id,'scope':'session','exp':session.expires_at},settings.app_secret,algorithm='HS256')
    return bearer

def attach_session(response, bearer):
    response.set_cookie('blink_session',bearer,httponly=True,secure=settings.secure_cookies,samesite='strict',max_age=86400*settings.cookie_days,path='/')
    csrf = secrets.token_urlsafe(32)
    response.set_cookie('blink_csrf',csrf,httponly=False,secure=settings.secure_cookies,samesite='strict',max_age=86400*settings.cookie_days,path='/')

def current_user(request: Request, db: DBSession=Depends(get_db)):
    # Static GitHub Pages Studio does not possess first-party cookies.
    # Require a short-lived JWT with the exact studio scope for Studio URLs.
    # A studio token is NEVER accepted by cookie-authenticated or admin routes.
    if request.url.path.startswith('/api/studio/'):
        header=request.headers.get('authorization','')
        if not header.startswith('Bearer '):
            raise HTTPException(401,'Token Studio dibutuhkan')
        try:
            claims=jwt.decode(header[7:],settings.app_secret,algorithms=['HS256'],
                              options={'require':['sub','sid','exp','scope']})
        except jwt.PyJWTError:
            raise HTTPException(401,'Token Studio telah berakhir atau tidak valid')
        if claims.get('scope')!='studio':
            raise HTTPException(401,'Token tidak memiliki izin Studio')
        session=db.get(Session,claims['sid'])
        if not session or session.user_id!=claims['sub'] or session.revoked_at or aware(session.expires_at)<=now():
            raise HTTPException(401,'Sesi Studio sudah dicabut atau berakhir')
        user=db.get(User,claims['sub'])
        if not user or user.role=='admin' or not user.email_verified_at:
            raise HTTPException(403,'Akses Studio ditolak')
        return user
    raw = request.cookies.get('blink_session','')
    try: claims=jwt.decode(raw,settings.app_secret,algorithms=['HS256'],options={'require':['sub','sid','exp']})
    except jwt.PyJWTError: raise HTTPException(401,'Silakan masuk terlebih dahulu')
    if claims.get('scope')!='session':
        raise HTTPException(401,'Token tidak diizinkan sebagai cookie sesi')
    session=db.get(Session,claims['sid'])
    if not session or session.user_id!=claims['sub'] or session.revoked_at or aware(session.expires_at)<=now():
        raise HTTPException(401,'Sesi telah berakhir')
    user=db.get(User,claims['sub'])
    if not user: raise HTTPException(401,'Akun tidak ditemukan')
    return user

def require_csrf(request: Request):
    # Studio routes authenticate using bearer headers, not ambient browser cookies.
    # current_user validates the signed scoped token before this dependency completes.
    if request.url.path.startswith('/api/studio/'):
        if not request.headers.get('authorization','').startswith('Bearer '):
            raise HTTPException(403,'Bearer token diperlukan')
        return
    origin=request.headers.get('origin')
    if origin and origin != settings.public_origin:
        raise HTTPException(403,'Origin tidak diizinkan')
    cookie=request.cookies.get('blink_csrf')
    header=request.headers.get('x-csrf-token')
    if not cookie or not header or not hmac.compare_digest(cookie,header):
        raise HTTPException(403,'CSRF token tidak valid')

def authed_mutation(user: User=Depends(current_user), _:None=Depends(require_csrf)):
    return user

def admin_mutation(user:User=Depends(authed_mutation)):
    if user.role!='admin' or not user.mfa_secret_enc: raise HTTPException(403,'Hanya administrator dengan MFA')
    return user

def admin_read(user:User=Depends(current_user)):
    if user.role!='admin' or not user.mfa_secret_enc: raise HTTPException(403,'Akses administrator diperlukan')
    return user
