"""Account-specific overview metric selection.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('dashboard_customized', sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    with op.batch_alter_table('metric_definitions') as batch:
        batch.add_column(sa.Column('dashboard_visible', sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('metric_definitions') as batch:
        batch.drop_column('dashboard_visible')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('dashboard_customized')
