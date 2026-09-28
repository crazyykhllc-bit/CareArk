"""Give a care event one explicit primary container without copying sources."""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('encounters') as batch:
        batch.add_column(sa.Column('primary_topic_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_encounters_primary_topic', 'care_topics', ['primary_topic_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_encounters_primary_topic_id', ['primary_topic_id'])
    # Count only valid memberships belonging to the same owner. Ambiguous old
    # references stay references; never select an arbitrary parent.
    op.execute(sa.text('''UPDATE encounters SET primary_topic_id = (
        SELECT cte.topic_id FROM care_topic_encounters cte
        JOIN care_topics ct ON ct.id = cte.topic_id
        WHERE cte.encounter_id = encounters.id AND cte.owner_id = encounters.owner_id
          AND ct.owner_id = encounters.owner_id AND ct.deleted_at IS NULL
    ) WHERE 1 = (SELECT COUNT(*) FROM care_topic_encounters cte
        JOIN care_topics ct ON ct.id = cte.topic_id
        WHERE cte.encounter_id = encounters.id AND cte.owner_id = encounters.owner_id
          AND ct.owner_id = encounters.owner_id AND ct.deleted_at IS NULL)'''))


def downgrade():
    with op.batch_alter_table('encounters') as batch:
        batch.drop_index('ix_encounters_primary_topic_id')
        batch.drop_constraint('fk_encounters_primary_topic', type_='foreignkey')
        batch.drop_column('primary_topic_id')
