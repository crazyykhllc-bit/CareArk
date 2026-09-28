"""add versioned document revision audit

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table(
        'document_revisions',
        sa.Column('document_id', sa.Uuid(), nullable=False),
        sa.Column('changed_by_id', sa.Uuid(), nullable=False),
        sa.Column('from_version', sa.Integer(), nullable=False),
        sa.Column('snapshot', json_type, nullable=False),
        sa.Column('changed_fields', json_type, nullable=False, server_default='[]'),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_revisions_document_id', 'document_revisions', ['document_id'])
    op.create_index('ix_document_revisions_changed_by_id', 'document_revisions', ['changed_by_id'])
    op.create_index('ix_document_revisions_owner_id', 'document_revisions', ['owner_id'])


def downgrade():
    raise RuntimeError('0006 contains audit history; restore a verified backup instead of destructive downgrade')
