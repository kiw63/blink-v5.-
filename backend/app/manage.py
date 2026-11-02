"""Admin bootstrap via protected environment, never embedded in source or frontend.
Usage: BLINK_ADMIN_EMAIL=... BLINK_ADMIN_PASSWORD=... python -m app.manage create-admin
       python -m app.manage init-db
       python -m app.manage verify-dev-email <email>   # development only
"""
import os,sys
from datetime import datetime
from sqlalchemy import select
from .config import settings
from .db import Base,engine,SessionLocal
from .models import User,now
from .security import hash_password,encrypt_totp,totp_secret
from .billing import today_wib

def cli():
    command=sys.argv[1] if len(sys.argv)>1 else ''
    if command=='init-db':
        Base.metadata.create_all(engine)
        print('Schema initialized; do not use create_all as a migration system.')
    elif command=='create-admin':
        email=os.environ.get('BLINK_ADMIN_EMAIL','').lower().strip()
        password=os.environ.get('BLINK_ADMIN_PASSWORD','')
        name=os.environ.get('BLINK_ADMIN_NAME','Reza')
        if not email or not password or not settings.mfa_encryption_key:
            raise SystemExit('Provide BLINK_ADMIN_EMAIL, BLINK_ADMIN_PASSWORD, MFA_ENCRYPTION_KEY privately')
        if len(password)<12:
            raise SystemExit('Admin password needs at least 12 characters; replace any previously shared short password.')
        with SessionLocal.begin() as db:
            user=db.scalar(select(User).where(User.email==email).with_for_update())
            if user:
                raise SystemExit('An account already exists; refusing to overwrite credentials or MFA.')
            secret=totp_secret()
            user=User(name=name,email=email,password_hash=hash_password(password),role='admin',
                 email_verified_at=now(),free_day=today_wib(),mfa_secret_enc=encrypt_totp(secret))
            db.add(user)
        print('Administrator provisioned. Add this TOTP key to an authenticator privately (shown once):')
        print(secret)
    elif command=='verify-dev-email':
        if os.getenv('BLINK_ENV','development')=='production':raise SystemExit('Not allowed in production')
        if len(sys.argv)<3:raise SystemExit('Missing email')
        with SessionLocal.begin() as db:
            u=db.scalar(select(User).where(User.email==sys.argv[2].lower()))
            if not u: raise SystemExit('Account not found')
            u.email_verified_at=now()
        print('Development email verified (does not send email).')
    else:raise SystemExit('Valid commands: init-db | create-admin | verify-dev-email')

if __name__=='__main__':cli()
