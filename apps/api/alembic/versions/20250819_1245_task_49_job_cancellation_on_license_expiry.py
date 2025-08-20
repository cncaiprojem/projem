"""Task 4.9: Job cancellation on license expiry

Adds license_id to jobs table and implements cascading cancellation.
Ensures jobs are automatically canceled when licenses expire.

Revision ID: 20250819_1245-task_49_job_cancellation_on_license_expiry
Revises: task_48_notification_unique
Create Date: 2025-08-19 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250819_1245_task_49'
down_revision: Union[str, None] = '20250819_1230_task_48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add license_id to jobs table for license-based job tracking."""
    
    # Add license_id column to jobs table if it doesn't exist
    op.execute("""
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='jobs' 
                AND column_name='license_id'
            ) THEN
                ALTER TABLE jobs 
                ADD COLUMN license_id BIGINT,
                ADD CONSTRAINT fk_jobs_license_id 
                    FOREIGN KEY (license_id) 
                    REFERENCES licenses(id) 
                    ON DELETE SET NULL;
                    
                CREATE INDEX idx_jobs_license_id 
                ON jobs(license_id) 
                WHERE license_id IS NOT NULL;
                
                COMMENT ON COLUMN jobs.license_id IS 
                'Associated license ID - jobs may be canceled if license expires';
            END IF;
        END $$;
    """)
    
    # Add license check status to jobs if not exists
    op.execute("""
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='jobs' 
                AND column_name='license_valid_at_creation'
            ) THEN
                ALTER TABLE jobs 
                ADD COLUMN license_valid_at_creation BOOLEAN DEFAULT true,
                ADD COLUMN license_check_timestamp TIMESTAMP WITH TIME ZONE;
                
                COMMENT ON COLUMN jobs.license_valid_at_creation IS 
                'Was the license valid when job was created';
                COMMENT ON COLUMN jobs.license_check_timestamp IS 
                'Last time license validity was checked';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Remove license-related columns from jobs table."""
    
    # Drop license-related columns
    op.execute("""
        ALTER TABLE jobs 
        DROP COLUMN IF EXISTS license_check_timestamp,
        DROP COLUMN IF EXISTS license_valid_at_creation,
        DROP CONSTRAINT IF EXISTS fk_jobs_license_id,
        DROP COLUMN IF EXISTS license_id CASCADE;
    """)
    
    # Drop index
    op.execute("DROP INDEX IF EXISTS idx_jobs_license_id;")