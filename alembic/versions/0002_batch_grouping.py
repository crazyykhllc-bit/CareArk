"""add mixed upload batches and traceable sources"""
from pathlib import Path
import runpy

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

TABLES = ['upload_batches', 'batch_files', 'source_units', 'encounters', 'document_sources', 'medication_packages']


def upgrade():
    metadata = runpy.run_path(str(Path(__file__).parents[1] / 'schema_v2.py'))['Base'].metadata
    metadata.create_all(op.get_bind(), tables=[metadata.tables[name] for name in TABLES])
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('encounter_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
        batch.create_foreign_key('fk_document_encounter', 'encounters', ['encounter_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_documents_encounter_id', ['encounter_id'])
    with op.batch_alter_table('medications') as batch:
        batch.add_column(sa.Column('manufacturer', sa.String(300), nullable=True))
        batch.add_column(sa.Column('approval_number', sa.String(200), nullable=True))


def downgrade():
    raise RuntimeError('批次包含多来源数据，请使用配套备份恢复；禁止直接删除新关系表')
