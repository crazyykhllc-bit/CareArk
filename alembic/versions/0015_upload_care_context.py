"""Share explicit care intent across auto-split upload batches."""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('upload_care_contexts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('intent_key', sa.String(100), nullable=False),
        sa.Column('mode', sa.String(24), nullable=False),
        sa.Column('name', sa.String(300), nullable=True),
        sa.Column('topic_id', sa.Uuid(), sa.ForeignKey('care_topics.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('event_id', sa.Uuid(), sa.ForeignKey('encounters.id', ondelete='RESTRICT'), nullable=True),
        sa.UniqueConstraint('owner_id', 'intent_key', name='uq_upload_care_intent'))
    for column in ['owner_id', 'topic_id', 'event_id']:
        op.create_index('ix_upload_care_contexts_' + column, 'upload_care_contexts', [column])
    with op.batch_alter_table('upload_batches') as batch:
        batch.add_column(sa.Column('care_context_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_batch_care_context', 'upload_care_contexts', ['care_context_id'], ['id'], ondelete='RESTRICT')
        batch.create_index('ix_upload_batches_care_context_id', ['care_context_id'])


def downgrade():
    with op.batch_alter_table('upload_batches') as batch:
        batch.drop_index('ix_upload_batches_care_context_id')
        batch.drop_constraint('fk_batch_care_context', type_='foreignkey')
        batch.drop_column('care_context_id')
    op.drop_table('upload_care_contexts')
