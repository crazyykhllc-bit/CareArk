"""add typed document details and traceable lab context

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('type_specific_data', json_type, nullable=False, server_default='{}'))
        batch.add_column(sa.Column('patient_scope', sa.String(20), nullable=False, server_default='unconfirmed'))
        batch.create_index('ix_documents_patient_scope', ['patient_scope'])
    with op.batch_alter_table('lab_results') as batch:
        batch.add_column(sa.Column('analyte_key', sa.String(200), nullable=True))
        batch.add_column(sa.Column('specimen', sa.String(200), nullable=True))
        batch.add_column(sa.Column('condition', sa.String(200), nullable=True))
        batch.add_column(sa.Column('observed_date', sa.Date(), nullable=True))
        batch.add_column(sa.Column('timepoint_minutes', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('test_session_key', sa.String(200), nullable=True))
        batch.add_column(sa.Column('source_unit_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('result_type', sa.String(20), nullable=False, server_default='unknown'))
        batch.add_column(sa.Column('review_status', sa.String(20), nullable=False, server_default='pending'))
        batch.create_foreign_key('fk_lab_results_source_unit', 'source_units', ['source_unit_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_lab_results_analyte_key', ['analyte_key'])
        batch.create_index('ix_lab_results_observed_date', ['observed_date'])
        batch.create_index('ix_lab_results_test_session_key', ['test_session_key'])
        batch.create_index('ix_lab_results_source_unit_id', ['source_unit_id'])
        batch.create_index('ix_lab_results_review_status', ['review_status'])
    op.create_table('receipt_details',
        sa.Column('document_id', sa.Uuid(), nullable=False),
        sa.Column('receipt_number', sa.String(300), nullable=True),
        sa.Column('receipt_identity', sa.String(128), nullable=True),
        sa.Column('total_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('insurance_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('personal_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='CNY'),
        sa.Column('settlement_time', sa.String(200), nullable=True),
        sa.Column('payment_method', sa.String(200), nullable=True),
        sa.Column('line_items', json_type, nullable=False, server_default='[]'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('duplicate_of_id', sa.Uuid(), nullable=True),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['duplicate_of_id'], ['receipt_details.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('document_id'))
    op.create_index('ix_receipt_details_document_id', 'receipt_details', ['document_id'], unique=True)
    op.create_index('ix_receipt_details_receipt_identity', 'receipt_details', ['receipt_identity'])
    op.create_index('ix_receipt_details_status', 'receipt_details', ['status'])
    op.create_index('ix_receipt_details_duplicate_of_id', 'receipt_details', ['duplicate_of_id'])
    op.create_index('ix_receipt_details_owner_id', 'receipt_details', ['owner_id'])


def downgrade():
    raise RuntimeError('0003 contains user data; restore a verified backup instead of destructive downgrade')
