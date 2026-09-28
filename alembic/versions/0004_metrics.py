"""add per-user metric catalog and daily metric entries

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table(
        'metric_definitions',
        sa.Column('key', sa.String(200), nullable=False),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('group_name', sa.String(100), nullable=False),
        sa.Column('record_type', sa.String(20), nullable=False),
        sa.Column('unit', sa.String(100), nullable=True),
        sa.Column('aliases', json_type, nullable=False, server_default='[]'),
        sa.Column('component_labels', json_type, nullable=False, server_default='[]'),
        sa.Column('followed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('preset', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'key', name='uq_metric_owner_key'),
    )
    op.create_index('ix_metric_definitions_owner_id', 'metric_definitions', ['owner_id'])
    op.create_index('ix_metric_definitions_followed', 'metric_definitions', ['followed'])

    op.create_table(
        'metric_entries',
        sa.Column('metric_id', sa.Uuid(), nullable=False),
        sa.Column('record_date', sa.Date(), nullable=False),
        sa.Column('raw_value', sa.String(500), nullable=False),
        sa.Column('value1', sa.Numeric(18, 6), nullable=True),
        sa.Column('value2', sa.Numeric(18, 6), nullable=True),
        sa.Column('text_value', sa.String(500), nullable=True),
        sa.Column('unit', sa.String(100), nullable=True),
        sa.Column('condition', sa.String(200), nullable=True),
        sa.Column('review_status', sa.String(20), nullable=False, server_default='confirmed'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['metric_id'], ['metric_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'idempotency_key', name='uq_metric_entry_owner_idempotency'),
    )
    op.create_index('ix_metric_entries_metric_id', 'metric_entries', ['metric_id'])
    op.create_index('ix_metric_entries_record_date', 'metric_entries', ['record_date'])
    op.create_index('ix_metric_entries_voided_at', 'metric_entries', ['voided_at'])
    op.create_index('ix_metric_entries_owner_id', 'metric_entries', ['owner_id'])


def downgrade():
    raise RuntimeError('0004 contains user metric data; restore a verified backup instead of destructive downgrade')
