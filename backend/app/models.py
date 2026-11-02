from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey, Text, UniqueConstraint, Index
from .db import Base

def uid(): return str(uuid4())
def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(120), nullable=False)
    email = Column(String(254), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    role = Column(String(16), default='user', nullable=False)
    email_verified_at = Column(DateTime(timezone=True))
    mfa_secret_enc = Column(Text)
    free_tokens = Column(Integer, default=3, nullable=False)
    free_day = Column(String(10), nullable=False)
    premium_tokens = Column(Integer, default=0, nullable=False)
    premium_starts = Column(DateTime(timezone=True))
    premium_expires = Column(DateTime(timezone=True))
    membership_revision = Column(Integer, default=0, nullable=False)
    membership_order_id = Column(String(36))
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)

class AuthToken(Base):
    __tablename__ = 'auth_tokens'
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    digest = Column(String(64), unique=True, nullable=False, index=True)
    purpose = Column(String(30), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    mode = Column(String(40), nullable=False)
    target = Column(String(20), nullable=False, default='auto')
    input_key = Column(String(300), nullable=False)
    motion_key = Column(String(300))
    output_key = Column(String(300))
    output_motion_key = Column(String(300))
    status = Column(String(20), default='queued', nullable=False, index=True)
    priority = Column(Integer, default=0, nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    error = Column(Text)
    reserved_free = Column(Integer, default=0, nullable=False)
    reserved_premium = Column(Integer, default=0, nullable=False)
    reserved_free_day = Column(String(10))
    reserved_membership_revision = Column(Integer)
    input_width = Column(Integer)
    input_height = Column(Integer)
    output_width = Column(Integer)
    output_height = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    heartbeat_at = Column(DateTime(timezone=True))

class Order(Base):
    __tablename__ = 'orders'
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    amount = Column(Integer, default=20000, nullable=False)
    status = Column(String(20), default='created', nullable=False, index=True)
    proof_key = Column(String(300))
    verification_ref = Column(String(120))
    submitted_at = Column(DateTime(timezone=True))
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(String(36), ForeignKey('users.id'))
    rejection_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)

# Bank/provider reference cannot authorize more than one Premium activation.
# NULL values are permitted for orders awaiting manual verification.
Index('ux_orders_verification_ref', Order.verification_ref, unique=True)

class Audit(Base):
    __tablename__ = 'audits'
    id = Column(String(36), primary_key=True, default=uid)
    actor_id = Column(String(36), ForeignKey('users.id'))
    event = Column(String(80), nullable=False)
    target_id = Column(String(36))
    data = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)

class TokenEvent(Base):
    __tablename__ = 'token_events'
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey('jobs.id'))
    order_id = Column(String(36), ForeignKey('orders.id'))
    event = Column(String(30), nullable=False)
    free_delta = Column(Integer, default=0, nullable=False)
    premium_delta = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
