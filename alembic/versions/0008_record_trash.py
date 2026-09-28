"""Recoverable document and medication removal.

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_index('ix_documents_deleted_at', ['deleted_at'])
    with op.batch_alter_table('medications') as batch:
        batch.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_index('ix_medications_deleted_at', ['deleted_at'])
    op.create_table(
        'medication_revisions',
        sa.Column('medication_id', sa.Uuid(), nullable=False),
        sa.Column('changed_by_id', sa.Uuid(), nullable=False),
        sa.Column('from_version', sa.Integer(), nullable=False),
        sa.Column('snapshot', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('changed_fields', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['medication_id'], ['medications.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_medication_revisions_medication_id', 'medication_revisions', ['medication_id'])
    op.create_index('ix_medication_revisions_owner_id', 'medication_revisions', ['owner_id'])
    op.create_table(
        'metric_entry_revisions',
        sa.Column('metric_entry_id', sa.Uuid(), nullable=False),
        sa.Column('changed_by_id', sa.Uuid(), nullable=False),
        sa.Column('from_version', sa.Integer(), nullable=False),
        sa.Column('snapshot', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('changed_fields', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['metric_entry_id'], ['metric_entries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_metric_entry_revisions_metric_entry_id', 'metric_entry_revisions', ['metric_entry_id'])
    op.create_index('ix_metric_entry_revisions_owner_id', 'metric_entry_revisions', ['owner_id'])


def downgrade():
    raise RuntimeError('0008 protects recoverable health data; restore a verified backup instead of dropping trash state')
