"""Prevent reusing the same bank verification reference across orders.
Revision ID: 0002_unique_payment_reference
Revises: 0001_initial
"""
from alembic import op
revision='0002_unique_payment_reference'
down_revision='0001_initial'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_verification_ref ON orders (verification_ref)')

def downgrade():
    raise RuntimeError('Downgrade would weaken payment verification; disabled')
