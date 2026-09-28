"""Allow a login account to manage separate non-login health archives."""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('managed_by_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('profile_name', sa.String(100), nullable=True))
        batch.create_foreign_key('fk_users_managed_by', 'users', ['managed_by_id'], ['id'], ondelete='CASCADE')
        batch.create_index('ix_users_managed_by_id', ['managed_by_id'])
    with op.batch_alter_table('sessions') as batch:
        batch.add_column(sa.Column('active_profile_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_sessions_active_profile', 'users', ['active_profile_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_sessions_active_profile_id', ['active_profile_id'])


def downgrade():
    with op.batch_alter_table('sessions') as batch:
        batch.drop_index('ix_sessions_active_profile_id')
        batch.drop_constraint('fk_sessions_active_profile', type_='foreignkey')
        batch.drop_column('active_profile_id')
    with op.batch_alter_table('users') as batch:
        batch.drop_index('ix_users_managed_by_id')
        batch.drop_constraint('fk_users_managed_by', type_='foreignkey')
        batch.drop_column('profile_name')
        batch.drop_column('managed_by_id')
