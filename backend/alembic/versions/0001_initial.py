"""initial BLINK schema
Revision ID: 0001_initial
Revises:
"""
from alembic import op
from app.db import Base
from app import models
revision='0001_initial'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    raise RuntimeError('Destructive schema downgrade is disabled for safety')
