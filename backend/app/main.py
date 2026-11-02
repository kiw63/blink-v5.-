import hashlib, json, os, secrets, smtplib, time
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel, EmailStr, Field
from .config import settings, assert_production_config
from .db import Base, engine, get_db
from .models import User, Session, AuthToken, Order, Job, Audit, TokenEvent, now
from .security import (hash_password, verify_password, current_user, authed_mutation, admin_read, admin_mutation,
                       issue_session, attach_session, verify_totp, decrypt_totp, digest_token, make_auth_token,
                       require_csrf, aware)
from .billing import refresh_balances, lock_user, reserve_tokens, user_summary, activate_membership, today_wib
from .storage import Storage
from .media import receive_upload, PHOTO_MODES, VIDEO_MODES, CINEMA_MODES
from .capabilities import public_capabilities, ai_files_present

assert_production_config()
app=FastAPI(title='BLINK API',docs_url='/docs' if settings.enable_docs else None,redoc_url=None,openapi_url='/openapi.json' if settings.enable_docs else None)
ALLOWED_ORIGINS={settings.public_origin, *([settings.studio_origin] if settings.studio_origin else [])}
app.add_middleware(CORSMiddleware,allow_origins=sorted(ALLOWED_ORIGINS),allow_credentials=True,
                   allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Content-Type','X-CSRF-Token','Authorization'])

@app.on_event('startup')
def startup():
    if os.getenv('BLINK_ENV','development')!='production':
        Base.metadata.create_all(engine)
    # In production, schema must be created via migrations/setup, never automatic drop.

@app.middleware('http')
async def safe_headers(request:Request, call_next):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if origin and origin not in ALLOWED_ORIGINS:
            return Response('Forbidden origin',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'private, max-age=300'
    response.headers['Content-Security-Policy']="default-src 'none'; frame-ancestors 'none'"
    if settings.secure_cookies: response.headers['Strict-Transport-Security']='max-age=63072000; includeSubDomains'
    return response

class Register(BaseModel):
    name: str=Field(min_length=2,max_length=120)
    email: EmailStr
    password: str=Field(min_length=12,max_length=256)
class Login(BaseModel):
    email: EmailStr
    password: str
class AdminLogin(Login):
    totp: str=Field(min_length=6,max_length=6)
class TokenPayload(BaseModel):
    token: str
class ResetRequest(BaseModel):
    email: EmailStr
class ResetPassword(BaseModel):
    token: str
    new_password: str=Field(min_length=12,max_length=256)
class Profile(BaseModel):
    name: str=Field(min_length=2,max_length=120)
class ChangePassword(BaseModel):
    current_password: str
    new_password: str=Field(min_length=12,max_length=256)
class Decision(BaseModel):
    funds_verified: bool=False
    verification_ref: str=Field(default='',max_length=120)
    reason: str=Field(default='',max_length=500)

def audit(db,event,actor=None,target=None,data=None):
    db.add(Audit(event=event,actor_id=actor,target_id=target,data=json.dumps(data or {})))

def send_email(recipient,subject,body):
    if not (settings.smtp_host and settings.smtp_from): return False
    message=EmailMessage()
    message['To']=recipient; message['From']=settings.smtp_from; message['Subject']=subject
    message.set_content(body)
    if settings.smtp_port==465:
        with smtplib.SMTP_SSL(settings.smtp_host,settings.smtp_port,timeout=15) as smtp:
            if settings.smtp_username: smtp.login(settings.smtp_username,settings.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_username: smtp.login(settings.smtp_username,settings.smtp_password)
            smtp.send_message(message)
    return True

def email_token(db,user,purpose,subject,path,minutes):
    token=make_auth_token(db,user,purpose,minutes)
    if settings.studio_public_url and purpose in {'verify','reset'}:
        # Use full GitHub Pages project path for verification and reset links.
        link=f"{settings.studio_public_url.rstrip('/')}/?{purpose}={token}"
    else:
        link=f'{settings.public_origin}{path}?token={token}'
    db.flush()
    # Missing SMTP leaves account unverified, never masquerades as mail delivered.
    return send_email(user.email,subject,f'BLINK\n\nBuka tautan berikut:\n{link}\n\nJika Anda tidak meminta ini, abaikan email ini.')

def rate_limit(db,request,action,limit=8,identifier=''):
    ip=request.client.host if request.client else 'unknown'
    # Key by account/email as well as peer IP, avoiding shared reverse-proxy throttling.
    key=hashlib.sha256(f'{action}:{ip}:{identifier.strip().lower()}'.encode()).hexdigest()[:32]
    recent=now()-timedelta(minutes=15)
    number=db.scalar(select(func.count(Audit.id)).where(Audit.event==f'rate:{action}',Audit.target_id==key,Audit.created_at>=recent)) or 0
    if number>=limit: raise HTTPException(429,'Terlalu banyak percobaan. Coba kembali nanti.')
    audit(db,f'rate:{action}',target=key); db.commit()

def create_session_response(db,user):
    bearer=issue_session(db,user)
    db.commit()
    response=Response(content=json.dumps({'user':user_summary(user)}),media_type='application/json')
    attach_session(response,bearer)
    return response

@app.get('/api/health')
def health(): return {'status':'ok','service':'BLINK API','api_version':2}

@app.get('/api/public/capabilities')
def capabilities():
    return public_capabilities()

@app.post('/api/studio/login')
def studio_login(payload:Login,request:Request,db:DBSession=Depends(get_db)):
    """Issue a 45-minute memory-only browser token for GPU jobs from static hosting."""
    import jwt
    rate_limit(db,request,'studio-login',limit=8,identifier=str(payload.email))
    user=db.scalar(select(User).where(User.email==str(payload.email).lower()))
    if (not user or user.role=='admin' or not user.email_verified_at
            or not verify_password(payload.password,user.password_hash)):
        raise HTTPException(401,'Akun belum diverifikasi atau kredensial tidak valid')
    expiry=now()+timedelta(minutes=45)
    studio_session=Session(user_id=user.id,expires_at=expiry)
    db.add(studio_session);db.commit()
    token=jwt.encode({'sub':user.id,'sid':studio_session.id,'scope':'studio','exp':expiry},
                     settings.app_secret,algorithm='HS256')
    return {'access_token':token,'token_type':'Bearer','expires_in':2700,
            'user':user_summary(user)}

@app.post('/api/studio/logout',status_code=204)
def studio_logout(request:Request,db:DBSession=Depends(get_db),_:User=Depends(current_user)):
    import jwt
    claims=jwt.decode(request.headers['authorization'][7:],settings.app_secret,algorithms=['HS256'])
    session=db.get(Session,claims['sid'])
    if session: session.revoked_at=now();db.commit()
    return Response(status_code=204)

@app.post('/api/auth/register',status_code=201)
def register(payload:Register,request:Request,db:DBSession=Depends(get_db)):
    rate_limit(db,request,'register',limit=12,identifier=str(payload.email))
    email=str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email==email)):
        raise HTTPException(409,'Email sudah terdaftar')
    user=User(name=payload.name.strip(),email=email,password_hash=hash_password(payload.password),free_day=today_wib())
    db.add(user)
    try:
        db.flush()
        sent=email_token(db,user,'verify','Verifikasi Email BLINK','/verify-email',60*24)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(503,'Pendaftaran belum dapat diselesaikan karena layanan email bermasalah')
    return {'message':'Akun dibuat. Verifikasi email untuk dapat masuk.','verification_email_sent':sent}

@app.post('/api/auth/verify-email')
def verify_email(payload:TokenPayload,db:DBSession=Depends(get_db)):
    db_token=db.execute(select(AuthToken).where(AuthToken.digest==digest_token(payload.token),AuthToken.purpose=='verify').with_for_update()).scalar_one_or_none()
    if not db_token or db_token.used_at or aware(db_token.expires_at)<=now(): raise HTTPException(400,'Link verifikasi tidak berlaku')
    user=lock_user(db,db_token.user_id)
    user.email_verified_at=now(); db_token.used_at=now()
    db.commit()
    return {'message':'Email telah terverifikasi. Silakan masuk.'}

@app.post('/api/auth/login')
def login(payload:Login,request:Request,db:DBSession=Depends(get_db)):
    rate_limit(db,request,'login',limit=12,identifier=str(payload.email))
    user=db.scalar(select(User).where(User.email==str(payload.email).lower()))
    if not user or not verify_password(payload.password,user.password_hash): raise HTTPException(401,'Email atau sandi salah')
    if user.role=='admin': raise HTTPException(403,'Admin harus masuk melalui halaman admin dengan MFA')
    if not user.email_verified_at: raise HTTPException(403,'Email belum diverifikasi')
    refresh_balances(db,user)
    return create_session_response(db,user)

@app.post('/api/auth/admin/login')
def admin_login(payload:AdminLogin,request:Request,db:DBSession=Depends(get_db)):
    rate_limit(db,request,'admin-login',limit=7,identifier=str(payload.email))
    user=db.scalar(select(User).where(User.email==str(payload.email).lower()))
    if not user or user.role!='admin' or not user.mfa_secret_enc or not verify_password(payload.password,user.password_hash):
        raise HTTPException(401,'Kredensial admin atau kode MFA tidak valid')
    try: valid=verify_totp(decrypt_totp(user.mfa_secret_enc),payload.totp)
    except Exception: valid=False
    if not valid: raise HTTPException(401,'Kredensial admin atau kode MFA tidak valid')
    refresh_balances(db,user)
    audit(db,'admin_login',actor=user.id)
    return create_session_response(db,user)

@app.post('/api/auth/logout')
def logout(request:Request,db:DBSession=Depends(get_db),user:User=Depends(authed_mutation)):
    raw=request.cookies.get('blink_session')
    import jwt
    token=jwt.decode(raw,settings.app_secret,algorithms=['HS256'])
    session=db.get(Session,token['sid'])
    if session: session.revoked_at=now()
    db.commit()
    res=Response(status_code=204)
    res.delete_cookie('blink_session',path='/'); res.delete_cookie('blink_csrf',path='/')
    return res

@app.get('/api/studio/me')
@app.get('/api/me')
def me(db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    locked=lock_user(db,user.id)
    refresh_balances(db,locked)
    db.commit()
    return user_summary(locked)

@app.patch('/api/account/profile')
def edit_profile(payload:Profile,db:DBSession=Depends(get_db),user:User=Depends(authed_mutation)):
    user.name=payload.name.strip(); db.commit()
    return {'message':'Profil diperbarui'}

@app.post('/api/account/password')
def change_password(payload:ChangePassword,db:DBSession=Depends(get_db),user:User=Depends(authed_mutation)):
    if not verify_password(payload.current_password,user.password_hash): raise HTTPException(403,'Kata sandi saat ini salah')
    user.password_hash=hash_password(payload.new_password)
    db.execute(select(Session).where(Session.user_id==user.id).with_for_update())
    # Revokes all sessions; user needs to login again.
    for s in db.scalars(select(Session).where(Session.user_id==user.id)):
        s.revoked_at=now()
    db.commit()
    return {'message':'Kata sandi diubah. Silakan masuk kembali.'}

@app.post('/api/auth/request-reset')
def request_reset(payload:ResetRequest,request:Request,db:DBSession=Depends(get_db)):
    rate_limit(db,request,'reset',limit=6,identifier=str(payload.email))
    user=db.scalar(select(User).where(User.email==str(payload.email).lower()))
    if user and user.role!='admin':
        try:
            email_token(db,user,'reset','Reset Kata Sandi BLINK','/reset-password',30)
            db.commit()
        except Exception: db.rollback()
    return {'message':'Jika email terdaftar dan layanan email tersedia, tautan pemulihan akan dikirim.'}

@app.post('/api/auth/reset-password')
def reset_password(payload:ResetPassword,db:DBSession=Depends(get_db)):
    item=db.execute(select(AuthToken).where(AuthToken.digest==digest_token(payload.token),AuthToken.purpose=='reset').with_for_update()).scalar_one_or_none()
    if not item or item.used_at or aware(item.expires_at)<=now(): raise HTTPException(400,'Tautan reset tidak berlaku')
    user=lock_user(db,item.user_id)
    if user.role=='admin': raise HTTPException(403,'Reset admin harus melalui proses operator')
    user.password_hash=hash_password(payload.new_password); item.used_at=now()
    for s in db.scalars(select(Session).where(Session.user_id==user.id)): s.revoked_at=now()
    db.commit()
    return {'message':'Kata sandi telah diubah.'}

@app.get('/api/public/qris')
def qris():
    path=Path(settings.qris_path)
    if not path.is_file(): raise HTTPException(503,'QRIS belum dikonfigurasi')
    return FileResponse(path,media_type='image/jpeg')

@app.post('/api/studio/payments/orders',status_code=201)
@app.post('/api/payments/orders',status_code=201)
def create_order(db:DBSession=Depends(get_db),user:User=Depends(authed_mutation)):
    lock_user(db,user.id)
    outstanding=db.scalar(select(Order).where(Order.user_id==user.id,Order.status.in_(['created','submitted']))
                          .order_by(Order.created_at.desc()).limit(1))
    if outstanding:
        db.commit()
        return order_public(outstanding)
    order=Order(user_id=user.id,amount=20000)
    db.add(order); db.commit()
    return order_public(order)

def order_public(o):
    return {'id':o.id,'amount':o.amount,'status':o.status,'created_at':o.created_at,'submitted_at':o.submitted_at,'reviewed_at':o.reviewed_at,'rejection_reason':o.rejection_reason}

@app.get('/api/studio/payments/orders')
@app.get('/api/payments/orders')
def list_orders(db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    return [order_public(o) for o in db.scalars(select(Order).where(Order.user_id==user.id).order_by(Order.created_at.desc()).limit(100))]

@app.post('/api/studio/payments/orders/{order_id}/proof')
@app.post('/api/payments/orders/{order_id}/proof')
async def submit_proof(order_id:str,proof:UploadFile=File(...),db:DBSession=Depends(get_db),user:User=Depends(authed_mutation)):
    order=db.execute(select(Order).where(Order.id==order_id,Order.user_id==user.id).with_for_update()).scalar_one_or_none()
    if not order: raise HTTPException(404,'Pesanan tidak ditemukan')
    if order.status!='created': raise HTTPException(409,'Pesanan sudah diproses atau dikirim')
    local=None; key=None
    try:
        local,extension,_=await receive_upload(proof,'image')
        key=f'payments/{order.id}/proof{extension}'
        Storage().put_file(key,local)
        order.proof_key=key; order.status='submitted'; order.submitted_at=now()
        audit(db,'payment_submitted',actor=user.id,target=order.id)
        db.commit()
        return {'message':'Menunggu Verifikasi Admin','order':order_public(order)}
    except Exception:
        db.rollback()
        if key:
            try: Storage().remove(key)
            except Exception: pass
        raise
    finally:
        if local and os.path.exists(local): os.unlink(local)

@app.get('/api/payments/orders/{order_id}/proof')
def view_proof(order_id:str,db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    order=db.get(Order,order_id)
    if not order or (order.user_id!=user.id and user.role!='admin'): raise HTTPException(404,'Bukti tidak ditemukan')
    if not order.proof_key: raise HTTPException(404,'Bukti belum ada')
    return media_response(order.proof_key,'payment-proof'+Path(order.proof_key).suffix,inline=True)

def media_response(key,filename,inline=False,proxy_remote=False):
    # Studio fetches with a bearer header from GitHub Pages. Streaming S3 through
    # the authenticated API avoids cross-origin presigned redirects and bucket CORS.
    if proxy_remote and settings.s3_bucket:
        storage=Storage()
        obj=storage.s3.get_object(Bucket=settings.s3_bucket,Key=key)
        body=obj['Body']
        def chunks():
            try:
                for chunk in body.iter_chunks(chunk_size=256*1024):
                    if chunk: yield chunk
            finally: body.close()
        mime={'png':'image/png','jpg':'image/jpeg','webp':'image/webp','mp4':'video/mp4',
              'mov':'video/quicktime','webm':'video/webm'}.get(Path(filename).suffix.lstrip('.').lower(),'application/octet-stream')
        return StreamingResponse(chunks(),media_type=mime,headers={'Content-Disposition':f'attachment; filename="{filename}"'})
    ref=Storage().get_download(key,filename,inline=inline)
    if 'url' in ref: return RedirectResponse(ref['url'],status_code=302)
    if not os.path.exists(ref['path']): raise HTTPException(404,'File tidak ditemukan')
    mime={'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp','mp4':'video/mp4','mov':'video/quicktime','webm':'video/webm','mkv':'video/x-matroska'}.get(Path(filename).suffix.lstrip('.').lower(),'application/octet-stream')
    return FileResponse(ref['path'],filename=None if inline else filename,media_type=mime,content_disposition_type='inline' if inline else 'attachment')

@app.post('/api/studio/jobs',status_code=201)
@app.post('/api/jobs',status_code=201)
async def submit_job(file:UploadFile=File(...),kind:str=Form(...),mode:str=Form('auto'),target:str=Form('auto'),
                     motion:UploadFile|None=File(default=None),db:DBSession=Depends(get_db),user:User=Depends(authed_mutation)):
    if kind not in {'photo','video','live_photo','cinematic'}: raise HTTPException(422,'Jenis pekerjaan tidak berlaku')
    allowed={'photo':PHOTO_MODES,'video':VIDEO_MODES,'live_photo':PHOTO_MODES,'cinematic':CINEMA_MODES}[kind]
    if mode not in allowed: raise HTTPException(422,'Mode tidak berlaku')
    if target not in {'auto','1080p','2k','4k'}: raise HTTPException(422,'Resolusi tidak berlaku')
    if kind=='live_photo' and not motion: raise HTTPException(422,'Live Photo memerlukan klip gerak asli')
    if kind in {'photo','live_photo','video'} and os.getenv('BLINK_ENV') == 'production':
        from .verify_ai_engine import verification_is_current
        if not verification_is_current():
            raise HTTPException(503,'AI GPU belum lulus pemeriksaan inferensi sungguhan. Token belum dipotong.')
    if kind!='live_photo' and motion: raise HTTPException(422,'Klip gerak tidak diharapkan')
    if kind=='cinematic':
        count=db.scalar(select(func.count(Job.id)).where(Job.user_id==user.id,Job.kind=='cinematic',Job.created_at>=now()-timedelta(days=1))) or 0
        if count>=10: raise HTTPException(429,'Batas ekspor sinematik gratis: 10 setiap 24 jam')
    primary=None; secondary=None; keys=[]
    try:
        primary,extension,metadata=await receive_upload(file,'image' if kind in {'photo','live_photo'} else 'video')
        if motion:
            secondary,motion_ext,_=await receive_upload(motion,'video')
        user=lock_user(db,user.id)
        job=Job(user_id=user.id,kind=kind,mode=mode,target=target,input_key='',input_width=metadata['width'],input_height=metadata['height'],priority=1 if user.premium_expires and aware(user.premium_expires)>now() else 0)
        db.add(job); db.flush()
        job.input_key=f'jobs/{job.id}/input{extension}'; keys.append(job.input_key)
        if secondary:
            job.motion_key=f'jobs/{job.id}/motion{motion_ext}'; keys.append(job.motion_key)
        reserve_tokens(db,user,job)
        storage=Storage()
        storage.put_file(job.input_key,primary)
        if secondary: storage.put_file(job.motion_key,secondary)
        db.commit()
        return job_public(job)
    except Exception:
        db.rollback()
        for key in keys:
            try: Storage().remove(key)
            except Exception: pass
        raise
    finally:
        for path in [primary,secondary]:
            if path and os.path.exists(path): os.unlink(path)

def job_public(job):
    return {'id':job.id,'kind':job.kind,'mode':job.mode,'target':job.target,'status':job.status,'progress':job.progress,
            'error':job.error,'input_width':job.input_width,'input_height':job.input_height,
            'output_width':job.output_width,'output_height':job.output_height,
            'created_at':job.created_at,'finished_at':job.finished_at,'cost_free':job.reserved_free,'cost_premium':job.reserved_premium,
            'download_url':f'/api/jobs/{job.id}/download' if job.status=='completed' else None,
            'motion_download_url':f'/api/jobs/{job.id}/download?part=motion' if job.output_motion_key and job.status=='completed' else None}

@app.get('/api/studio/jobs')
@app.get('/api/jobs')
def list_jobs(db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    return [job_public(j) for j in db.scalars(select(Job).where(Job.user_id==user.id).order_by(Job.created_at.desc()).limit(100))]

@app.get('/api/studio/jobs/{job_id}')
@app.get('/api/jobs/{job_id}')
def get_job(job_id:str,db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    job=db.get(Job,job_id)
    if not job or (job.user_id!=user.id and user.role!='admin'): raise HTTPException(404,'Pekerjaan tidak ditemukan')
    return job_public(job)

@app.get('/api/studio/jobs/{job_id}/download')
@app.get('/api/jobs/{job_id}/download')
def download_job(job_id:str,request:Request,part:str='output',db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    job=db.get(Job,job_id)
    if not job or (job.user_id!=user.id and user.role!='admin') or job.status!='completed':
        raise HTTPException(404,'Hasil tidak ditemukan')
    if part not in {'output','motion'}: raise HTTPException(422,'Bagian tidak tersedia')
    key=job.output_key if part=='output' else job.output_motion_key
    if not key: raise HTTPException(404,'Bagian tidak tersedia')
    extension=Path(key).suffix
    return media_response(key,f'BLINK-{job.id[:8]}-{part}{extension}',inline=False,
                          proxy_remote=request.url.path.startswith('/api/studio/'))

@app.get('/api/studio/jobs/{job_id}/preview')
@app.get('/api/jobs/{job_id}/preview')
def preview_job(job_id:str,part:str='output',db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    job=db.get(Job,job_id)
    if not job or (job.user_id!=user.id and user.role!='admin'): raise HTTPException(404,'File tidak ditemukan')
    if part not in {'output','original','motion'}: raise HTTPException(422,'Bagian tidak valid')
    if part=='output' and job.status!='completed': raise HTTPException(404,'Belum selesai')
    key={'output':job.output_key,'original':job.input_key,'motion':job.output_motion_key}[part]
    if not key: raise HTTPException(404,'File tidak tersedia')
    return media_response(key,'preview'+Path(key).suffix,inline=True)

@app.get('/api/tokens/history')
def token_history(db:DBSession=Depends(get_db),user:User=Depends(current_user)):
    items=db.scalars(select(TokenEvent).where(TokenEvent.user_id==user.id).order_by(TokenEvent.created_at.desc()).limit(100))
    return [{'event':x.event,'free_delta':x.free_delta,'premium_delta':x.premium_delta,'date':x.created_at,'job_id':x.job_id,'order_id':x.order_id} for x in items]

@app.get('/api/admin/overview')
def admin_overview(db:DBSession=Depends(get_db),_:User=Depends(admin_read)):
    return {'users':db.scalar(select(func.count(User.id))), 'pending_payments':db.scalar(select(func.count(Order.id)).where(Order.status=='submitted')),
            'verified_revenue_idr':db.scalar(select(func.coalesce(func.sum(Order.amount),0)).where(Order.status=='approved')),
            'processing':db.scalar(select(func.count(Job.id)).where(Job.status=='processing')),
            'failed':db.scalar(select(func.count(Job.id)).where(Job.status=='failed'))}

@app.get('/api/admin/payments')
def admin_payments(db:DBSession=Depends(get_db),_:User=Depends(admin_read)):
    records=db.execute(select(Order,User).join(User,User.id==Order.user_id).order_by(Order.created_at.desc()).limit(200)).all()
    return [dict(**order_public(o),name=u.name,email=u.email,user_id=u.id,has_proof=bool(o.proof_key),verification_ref=o.verification_ref) for o,u in records]

@app.post('/api/admin/payments/{order_id}/approve')
def approve_payment(order_id:str,payload:Decision,db:DBSession=Depends(get_db),admin:User=Depends(admin_mutation)):
    if not payload.funds_verified or not payload.verification_ref.strip():
        raise HTTPException(422,'Admin wajib verifikasi dana pada rekening penerima dan mencatat referensi transaksi')
    order=db.execute(select(Order).where(Order.id==order_id).with_for_update()).scalar_one_or_none()
    if not order: raise HTTPException(404,'Pesanan tidak ditemukan')
    if order.status=='approved': return {'message':'Sudah disetujui sebelumnya (tidak ada token tambahan)','order':order_public(order)}
    if order.status!='submitted' or not order.proof_key: raise HTTPException(409,'Hanya pembayaran dengan bukti dapat diverifikasi')
    reference=payload.verification_ref.strip().upper()
    used=db.scalar(select(Order.id).where(Order.verification_ref==reference,Order.id!=order.id))
    if used: raise HTTPException(409,'Referensi transfer sudah dipakai untuk pesanan lain. Periksa mutasi rekening.')
    user=lock_user(db,order.user_id)
    order.status='approved'; order.reviewed_at=now(); order.reviewed_by=admin.id
    order.verification_ref=reference
    activate_membership(db,user,order)
    audit(db,'payment_approved',actor=admin.id,target=order.id,data={'verification_ref':order.verification_ref})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Referensi transfer telah digunakan oleh pesanan lain')
    try: send_email(user.email,'Premium BLINK Aktif',f'Pembayaran {order.id} telah diverifikasi. BLINK Premium aktif 30 hari dengan 20 token. Terima kasih.')
    except Exception: pass
    return {'message':'Premium diaktifkan','order':order_public(order)}

@app.post('/api/admin/payments/{order_id}/reject')
def reject_payment(order_id:str,payload:Decision,db:DBSession=Depends(get_db),admin:User=Depends(admin_mutation)):
    if not payload.reason.strip(): raise HTTPException(422,'Alasan penolakan wajib diisi')
    order=db.execute(select(Order).where(Order.id==order_id).with_for_update()).scalar_one_or_none()
    if not order: raise HTTPException(404,'Pesanan tidak ditemukan')
    if order.status!='submitted': raise HTTPException(409,'Status pesanan tidak bisa ditolak')
    order.status='rejected'; order.rejection_reason=payload.reason
    order.reviewed_at=now();order.reviewed_by=admin.id
    audit(db,'payment_rejected',actor=admin.id,target=order.id)
    db.commit()
    return {'message':'Bukti pembayaran ditolak'}

@app.get('/api/admin/users')
def admin_users(db:DBSession=Depends(get_db),_:User=Depends(admin_read)):
    return [user_summary(u) for u in db.scalars(select(User).order_by(User.created_at.desc()).limit(200))]

@app.get('/api/admin/account-catalog')
def admin_account_catalog(
    status: str = Query('all', pattern='^(all|premium|former|free)$'),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=100),
    db: DBSession = Depends(get_db),
    _: User = Depends(admin_read),
):
    """Admin-only catalogue: current paid vs previous paid vs never-paid.

    No schema migrations or changes to existing /api/admin/users contract.
    A submitted receipt is NEVER counted as a payment.
    """
    active = and_(User.premium_expires.is_not(None), User.premium_expires > now())
    paid = select(Order.id).where(Order.user_id == User.id, Order.status == 'approved').exists()
    only_members = User.role == 'user'
    categories = {
        'premium': active,
        'former': and_(~active, paid),
        'free': and_(~active, ~paid),
    }
    counts = {
        category: db.scalar(select(func.count(User.id)).where(only_members, clause)) or 0
        for category, clause in categories.items()
    }
    condition = only_members if status == 'all' else and_(only_members, categories[status])
    total = db.scalar(select(func.count(User.id)).where(condition)) or 0
    payment_count = (select(func.count(Order.id))
                     .where(Order.user_id == User.id, Order.status == 'approved')
                     .correlate(User).scalar_subquery())
    last_paid = (select(func.max(Order.reviewed_at))
                 .where(Order.user_id == User.id, Order.status == 'approved')
                 .correlate(User).scalar_subquery())
    rows = db.execute(
        select(User, payment_count.label('paid_order_count'), last_paid.label('last_paid_at'))
        .where(condition)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    result = []
    for user, paid_order_count, last_paid_at in rows:
        info = user_summary(user)
        info['plan_status'] = ('premium' if info['premium_active']
                               else 'former' if paid_order_count else 'free')
        info['paid_order_count'] = int(paid_order_count)
        info['last_paid_at'] = last_paid_at
        info['registered_at'] = user.created_at
        result.append(info)
    return {'items': result, 'counts': counts, 'total': total,
            'page': page, 'page_size': page_size, 'status': status}

@app.get('/api/admin/jobs')
def admin_jobs(db:DBSession=Depends(get_db),_:User=Depends(admin_read)):
    return [dict(**job_public(j),user_id=j.user_id) for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(200))]

@app.get('/api/admin/audit')
def admin_audit(db:DBSession=Depends(get_db),_:User=Depends(admin_read)):
    return [{'event':a.event,'actor':a.actor_id,'target':a.target_id,'data':a.data,'at':a.created_at} for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(200))]

@app.get('/api/admin/events')
async def admin_events(_:User=Depends(admin_read)):
    # SSE causes real server push when new submissions or approvals are visible.
    import asyncio
    async def stream():
        prev=None
        while True:
            try:
                with __import__('app.db',fromlist=['SessionLocal']).SessionLocal() as db:
                    value=db.scalar(select(func.count(Order.id)).where(Order.status=='submitted'))
                    newest=db.scalar(select(func.max(Order.submitted_at)))
                    signature=f'{value}:{newest}'
                if signature!=prev:
                    yield f'event: payments\ndata: {json.dumps({"pending":value})}\n\n'
                    prev=signature
                else: yield ': heartbeat\n\n'
                await asyncio.sleep(3)
            except asyncio.CancelledError: break
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.get('/api/admin/tokens')
def admin_tokens(db:DBSession=Depends(get_db),_:User=Depends(admin_read)):
    return [{'user_id':e.user_id,'event':e.event,'free_delta':e.free_delta,'premium_delta':e.premium_delta,'at':e.created_at}
            for e in db.scalars(select(TokenEvent).order_by(TokenEvent.created_at.desc()).limit(300))]

@app.get('/api/admin/settings')
def admin_settings(_:User=Depends(admin_read)):
    return {**public_capabilities(), 'private_s3_configured':bool(settings.s3_bucket),
            'ai_model_files_configured':ai_files_present()}
