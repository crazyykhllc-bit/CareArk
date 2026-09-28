"""Add source-backed care events and user-organized topics.

Existing encounter IDs, dates, and document links are preserved. Existing dates
remain labeled as previously confirmed dates until a user reviews their meaning.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(JSONB(), "postgresql")


def common_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    ]


def upgrade():
    with op.batch_alter_table("encounters") as batch:
        batch.add_column(sa.Column("event_kind", sa.String(24), nullable=False, server_default="other"))
        batch.add_column(sa.Column("department", sa.String(200)))
        batch.add_column(sa.Column("date_end", sa.Date()))
        batch.add_column(sa.Column("date_basis", sa.String(24), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("date_sources", json_type, nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("summary_facts", json_type, nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("milestones", json_type, nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("user_note", sa.Text()))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_encounters_deleted_at", ["deleted_at"])
    op.execute("UPDATE encounters SET date_basis = 'user_confirmed' WHERE date IS NOT NULL")
    op.create_table("care_topics", *common_columns(),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_care_topics_owner_id", "care_topics", ["owner_id"])
    op.create_index("ix_care_topics_deleted_at", "care_topics", ["deleted_at"])
    op.create_table("care_topic_encounters", *common_columns(),
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("care_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encounter_id", sa.Uuid(), sa.ForeignKey("encounters.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("topic_id", "encounter_id", name="uq_care_topic_encounter"))
    for column in ("owner_id", "topic_id", "encounter_id"):
        op.create_index(f"ix_care_topic_encounters_{column}", "care_topic_encounters", [column])
    op.create_table("care_suggestions", *common_columns(),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("source_versions", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("owner_id", "dedupe_key", name="uq_care_suggestion_owner_key"))
    op.create_index("ix_care_suggestions_owner_id", "care_suggestions", ["owner_id"])
    op.create_index("ix_care_suggestions_status", "care_suggestions", ["status"])
    op.create_table("care_revisions", *common_columns(),
        sa.Column("object_kind", sa.String(20), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("snapshot", json_type, nullable=False),
        sa.Column("changed_fields", json_type, nullable=False),
        sa.Column("changed_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    for column in ("owner_id", "object_kind", "object_id"):
        op.create_index(f"ix_care_revisions_{column}", "care_revisions", [column])


def downgrade():
    for table in ("care_revisions", "care_suggestions", "care_topic_encounters", "care_topics"):
        op.drop_table(table)
    with op.batch_alter_table("encounters") as batch:
        batch.drop_index("ix_encounters_deleted_at")
        for column in ("deleted_at", "user_note", "milestones", "summary_facts", "date_sources", "date_basis", "date_end", "department", "event_kind"):
            batch.drop_column(column)
