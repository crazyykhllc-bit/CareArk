"""Allow cross-hospital related care without merging distinct visits."""

from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'related_encounters',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.Uuid(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('encounter_id', sa.Uuid(), sa.ForeignKey('encounters.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('document_id', 'encounter_id', name='uq_related_document_encounter'),
    )
    op.create_index('ix_related_encounters_owner_id', 'related_encounters', ['owner_id'])
    op.create_index('ix_related_encounters_document_id', 'related_encounters', ['document_id'])
    op.create_index('ix_related_encounters_encounter_id', 'related_encounters', ['encounter_id'])


def downgrade():
    op.drop_table('related_encounters')
