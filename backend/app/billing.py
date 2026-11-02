from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select
from .models import User, TokenEvent, now
from .security import aware

WIB = ZoneInfo('Asia/Jakarta')
COST = {'photo': 1, 'live_photo': 2, 'video': 3, 'cinematic': 0}

def today_wib(at=None): return (at or now()).astimezone(WIB).date().isoformat()

def refresh_balances(db, user, at=None):
    at=at or now()
    day=today_wib(at)
    if user.free_day!=day:
        previous_free=user.free_tokens
        user.free_day=day
        user.free_tokens=3
        db.add(TokenEvent(user_id=user.id,event='daily_reset',free_delta=3-previous_free))
    if user.premium_expires and aware(user.premium_expires)<=at and user.premium_tokens:
        expired_tokens=user.premium_tokens
        user.premium_tokens=0
        db.add(TokenEvent(user_id=user.id,event='premium_expired',premium_delta=-expired_tokens))
    return user

def lock_user(db, uid):
    return db.execute(select(User).where(User.id==uid).with_for_update()).scalar_one()

def reserve_tokens(db,user,job):
    refresh_balances(db,user)
    cost=COST[job.kind]
    free=min(cost,user.free_tokens)
    left=cost-free
    premium_active=bool(user.premium_expires and aware(user.premium_expires)>now())
    if left and (not premium_active or user.premium_tokens<left):
        raise HTTPException(402,'Token tidak cukup. Upgrade Premium atau tunggu reset harian.')
    job.reserved_free=free; job.reserved_free_day=user.free_day
    job.reserved_premium=left
    job.reserved_membership_revision=user.membership_revision
    user.free_tokens-=free; user.premium_tokens-=left
    db.add(TokenEvent(user_id=user.id,job_id=job.id,event='reserve',free_delta=-free,premium_delta=-left))

def refund_tokens(db,user,job):
    if job.reserved_free and user.free_day==job.reserved_free_day:
        user.free_tokens=min(3,user.free_tokens+job.reserved_free)
        free_return=job.reserved_free
    else: free_return=0
    premium_valid=bool(user.premium_expires and aware(user.premium_expires)>now())
    if premium_valid and user.membership_revision==job.reserved_membership_revision:
        user.premium_tokens=min(20,user.premium_tokens+job.reserved_premium)
        premium_return=job.reserved_premium
    else: premium_return=0
    db.add(TokenEvent(user_id=user.id,job_id=job.id,event='refund',free_delta=free_return,premium_delta=premium_return))

def activate_membership(db,user,order):
    if user.membership_order_id==order.id: return False
    at=now()
    refresh_balances(db,user,at)
    if user.premium_tokens:
        db.add(TokenEvent(user_id=user.id,order_id=order.id,event='premium_replaced',
                          premium_delta=-user.premium_tokens))
    user.membership_revision+=1
    user.premium_starts=at
    user.premium_expires=at+timedelta(days=30)
    user.premium_tokens=20
    user.membership_order_id=order.id
    db.add(TokenEvent(user_id=user.id,order_id=order.id,event='premium_activation',premium_delta=20))
    return True

def user_summary(user):
    return {'id':user.id,'name':user.name,'email':user.email,'role':user.role,
            'verified':bool(user.email_verified_at),'free_tokens':user.free_tokens,
            'premium_tokens':user.premium_tokens,
            'premium_starts':user.premium_starts,'premium_expires':user.premium_expires,
            'premium_active':bool(user.premium_expires and aware(user.premium_expires)>now()),
            'free_day':user.free_day}
