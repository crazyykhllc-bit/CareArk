"""add optimistic versioning to receipt review state

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receipt_details') as batch:
        batch.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    raise RuntimeError('0007 protects receipt review state; restore a verified backup instead of destructive downgrade')
