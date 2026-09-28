"""create initial empty schema"""

from alembic import op

from pathlib import Path
import runpy

# Freeze revision 0001: future ORM tables must not appear in a historical migration.
Base = runpy.run_path(str(Path(__file__).parents[1] / "schema_v1.py"))["Base"]

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
