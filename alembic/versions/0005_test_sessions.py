"""add explicit test sessions for OGTT and similar grouped tests

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'test_sessions',
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=True),
        sa.Column('hospital', sa.String(300), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_test_sessions_owner_id', 'test_sessions', ['owner_id'])
    op.create_index('ix_test_sessions_session_date', 'test_sessions', ['session_date'])
    op.create_table(
        'test_session_sources',
        sa.Column('test_session_id', sa.Uuid(), nullable=False),
        sa.Column('source_unit_id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['test_session_id'], ['test_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_unit_id'], ['source_units.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('test_session_id', 'source_unit_id', name='uq_test_session_source'),
    )
    op.create_index('ix_test_session_sources_owner_id', 'test_session_sources', ['owner_id'])
    op.create_index('ix_test_session_sources_test_session_id', 'test_session_sources', ['test_session_id'])
    op.create_index('ix_test_session_sources_source_unit_id', 'test_session_sources', ['source_unit_id'])
    with op.batch_alter_table('lab_results') as batch:
        batch.add_column(sa.Column('test_session_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_lab_results_test_session', 'test_sessions', ['test_session_id'], ['id'],
                                 ondelete='SET NULL')
        batch.create_index('ix_lab_results_test_session_id', ['test_session_id'])


def downgrade():
    raise RuntimeError('0005 contains explicit test grouping; restore a verified backup instead of destructive downgrade')
