"""Add data integrity constraints and indexes

Revision ID: 3c4d5e6f7g8h
Revises: 2b3c4d5e6f7g
Create Date: 2025-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c4d5e6f7g8h'
down_revision: Union[str, None] = '2b3c4d5e6f7g'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add unique constraint on stripe_customer_id (if not already exists)
    op.create_index('ix_customers_stripe_customer_id_unique', 'customers', ['stripe_customer_id'], unique=True, postgresql_where=sa.text('stripe_customer_id IS NOT NULL'))
    
    # Add composite index for email + is_active for faster lookups
    op.create_index('ix_customers_email_active', 'customers', ['email', 'is_active'])
    
    # Add index for active customers only
    op.create_index('ix_customers_active_only', 'customers', ['is_active'], postgresql_where=sa.text('is_active = true'))
    
    # Create integration_sync_state table for tracking sync operations
    op.create_table('integration_sync_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('integration_name', sa.String(50), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=True),
        sa.Column('sync_status', sa.String(20), nullable=False, server_default='pending'),  # pending, synced, failed, orphaned
        sa.Column('last_sync_attempt', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('customer_id', 'integration_name', name='uq_customer_integration')
    )
    
    # Add indexes for integration_sync_state
    op.create_index('ix_integration_sync_customer_id', 'integration_sync_state', ['customer_id'])
    op.create_index('ix_integration_sync_integration', 'integration_sync_state', ['integration_name'])
    op.create_index('ix_integration_sync_external_id', 'integration_sync_state', ['external_id'])
    op.create_index('ix_integration_sync_status', 'integration_sync_state', ['sync_status'])
    
    # Create idempotency_keys table for preventing duplicate operations
    op.create_table('idempotency_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('operation_type', sa.String(50), nullable=False),  # create_customer, update_customer, delete_customer
        sa.Column('resource_id', sa.String(100), nullable=True),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.Column('response_data', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='processing'),  # processing, completed, failed
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_idempotency_key')
    )
    
    # Add indexes for idempotency_keys
    op.create_index('ix_idempotency_key', 'idempotency_keys', ['key'])
    op.create_index('ix_idempotency_expires_at', 'idempotency_keys', ['expires_at'])
    op.create_index('ix_idempotency_status', 'idempotency_keys', ['status'])


def downgrade() -> None:
    # Drop tables
    op.drop_table('idempotency_keys')
    op.drop_table('integration_sync_state')
    
    # Drop indexes
    op.drop_index('ix_customers_stripe_customer_id_unique', table_name='customers')
    op.drop_index('ix_customers_email_active', table_name='customers')
    op.drop_index('ix_customers_active_only', table_name='customers')