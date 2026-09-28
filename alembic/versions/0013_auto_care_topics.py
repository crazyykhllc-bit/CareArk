"""Record automatic topic provenance and explicit membership overrides."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade():
    with op.batch_alter_table("care_topics") as batch:
        batch.add_column(sa.Column("origin", sa.String(16), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("analysis_fingerprint", sa.String(64)))
    with op.batch_alter_table("care_topic_encounters") as batch:
        batch.add_column(sa.Column("origin", sa.String(16), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("evidence", json_type, nullable=False, server_default=sa.text("'{}'")))
    op.create_table("care_topic_exclusions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("care_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encounter_id", sa.Uuid(), sa.ForeignKey("encounters.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("topic_id", "encounter_id", name="uq_care_topic_exclusion"))
    for column in ("owner_id", "topic_id", "encounter_id"):
        op.create_index(f"ix_care_topic_exclusions_{column}", "care_topic_exclusions", [column])


def downgrade():
    op.drop_table("care_topic_exclusions")
    with op.batch_alter_table("care_topic_encounters") as batch:
        batch.drop_column("evidence")
        batch.drop_column("origin")
    with op.batch_alter_table("care_topics") as batch:
        batch.drop_column("analysis_fingerprint")
        batch.drop_column("origin")
