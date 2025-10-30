"""add_reconciliation_tables

Revision ID: d4a6d507b7cf
Revises: 1d1f963a8651
Create Date: 2025-10-11 21:03:16.548961

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a6d507b7cf'
down_revision: Union[str, None] = '1d1f963a8651'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create reconciliation_reports table
    op.create_table('reconciliation_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('total_local_customers', sa.Integer(), nullable=True),
        sa.Column('total_stripe_customers', sa.Integer(), nullable=True),
        sa.Column('mismatches_found', sa.Integer(), nullable=True),
        sa.Column('auto_resolved', sa.Integer(), nullable=True),
        sa.Column('manual_review_needed', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reconciliation_reports_id'), 'reconciliation_reports', ['id'], unique=False)

    # Create data_mismatches table
    op.create_table('data_mismatches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=True),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('mismatch_type', sa.String(length=50), nullable=True),
        sa.Column('field_name', sa.String(length=100), nullable=True),
        sa.Column('local_value', sa.Text(), nullable=True),
        sa.Column('stripe_value', sa.Text(), nullable=True),
        sa.Column('resolution_status', sa.String(length=20), nullable=True),
        sa.Column('resolution_action', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_mismatches_email'), 'data_mismatches', ['email'], unique=False)
    op.create_index(op.f('ix_data_mismatches_id'), 'data_mismatches', ['id'], unique=False)
    op.create_index(op.f('ix_data_mismatches_report_id'), 'data_mismatches', ['report_id'], unique=False)


def downgrade() -> None:
    # Drop data_mismatches table
    op.drop_index(op.f('ix_data_mismatches_report_id'), table_name='data_mismatches')
    op.drop_index(op.f('ix_data_mismatches_id'), table_name='data_mismatches')
    op.drop_index(op.f('ix_data_mismatches_email'), table_name='data_mismatches')
    op.drop_table('data_mismatches')
    
    # Drop reconciliation_reports table
    op.drop_index(op.f('ix_reconciliation_reports_id'), table_name='reconciliation_reports')
    op.drop_table('reconciliation_reports')
