"""Allow a reviewed visit to be archived before its date is known."""

from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('encounters') as batch:
        batch.alter_column('date', existing_type=sa.Date(), nullable=True)


def downgrade():
    raise RuntimeError('就诊日期可能为空；请使用配套备份恢复，禁止直接改回必填')
