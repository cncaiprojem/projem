"""
Task 4.8: Add unique constraint for license notification duplicate prevention

Revision ID: task_48_notification_unique
Revises: task_46_payment_provider  
Create Date: 2025-08-19 12:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'task_48_notification_unique'
down_revision = 'task_46_payment_provider'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add unique constraint for license notification duplicate prevention."""
    
    # Add unique constraint per Task 4.8 requirements:
    # Prevent duplicates per (license_id, days_out, channel)
    # Note: Removed date(created_at) from constraint for better database portability
    # The business logic ensures only one notification per license/days_out/channel combination
    op.create_unique_constraint(
        'uq_notifications_delivery_no_duplicates',
        'notifications_delivery',
        ['license_id', 'days_out', 'channel'],
        postgresql_where=sa.text('license_id IS NOT NULL AND days_out IS NOT NULL')
    )


def downgrade() -> None:
    """Remove unique constraint for license notification duplicate prevention."""
    
    op.drop_constraint(
        'uq_notifications_delivery_no_duplicates',
        'notifications_delivery',
        type_='unique'
    )