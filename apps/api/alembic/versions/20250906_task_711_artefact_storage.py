"""Task 7.11: Enhanced artefact storage with versioning and lifecycle

Revision ID: task_711_artefact_storage
Revises: task_57_artefacts
Create Date: 2025-09-06 10:00:00.000000

Task 7.11 Requirements:
- Add enhanced storage fields (region, etag, storage_class, etc.)
- Add content type and disposition fields
- Add deletion tracking fields
- Update unique constraint for versioning
- Add new indexes for performance
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = 'task_711_artefact_storage'
down_revision = 'task_57_artefacts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add Task 7.11 enhanced storage fields to artefacts table.
    """
    
    # Check if artefacts table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    if 'artefacts' not in inspector.get_table_names():
        logger.error("Artefacts table does not exist. Run Task 5.7 migration first.")
        raise Exception("Artefacts table must exist before running Task 7.11 migration")
    
    existing_columns = [col['name'] for col in inspector.get_columns('artefacts')]
    
    # Add new Task 7.11 columns
    
    # Region field
    if 'region' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'region', 
            sa.String(50), 
            nullable=True,
            comment="AWS region or MinIO region"
        ))
        # Set default region
        op.execute("UPDATE artefacts SET region = 'us-east-1' WHERE region IS NULL")
    
    # ETag field
    if 'etag' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'etag', 
            sa.String(255), 
            nullable=True,
            comment="S3 ETag for integrity (note: may differ from SHA256 for multipart)"
        ))
    
    # Storage class field
    if 'storage_class' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'storage_class', 
            sa.String(50), 
            nullable=True,
            server_default='STANDARD',
            comment="S3 storage class: STANDARD, STANDARD_IA, GLACIER, etc."
        ))
        # Set default storage class for existing records
        op.execute("UPDATE artefacts SET storage_class = 'STANDARD' WHERE storage_class IS NULL")
    
    # Content type field (actual from S3)
    if 'content_type' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'content_type', 
            sa.String(100), 
            nullable=True,
            comment="Actual content-type from S3 (may differ from mime_type)"
        ))
        # Copy from mime_type if available
        op.execute("UPDATE artefacts SET content_type = mime_type WHERE content_type IS NULL")
    
    # Content disposition field
    if 'content_disposition' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'content_disposition', 
            sa.String(255), 
            nullable=True,
            comment="Content-Disposition header for download behavior"
        ))
    
    # Exporter version field
    if 'exporter_version' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'exporter_version', 
            sa.String(50), 
            nullable=True,
            comment="Version of the exporter/converter used"
        ))
    
    # Request ID field for audit
    if 'request_id' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'request_id', 
            sa.String(255), 
            nullable=True,
            comment="S3 request ID for audit trail"
        ))
    
    # Deletion pending flag
    if 'deletion_pending' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'deletion_pending', 
            sa.Boolean(), 
            nullable=False,
            server_default='false',
            comment="Flag for pending deletion from storage"
        ))
    
    # Last error field
    if 'last_error' not in existing_columns:
        op.add_column('artefacts', sa.Column(
            'last_error', 
            sa.String(1024), 
            nullable=True,
            comment="Last error message if deletion/operation failed"
        ))
    
    # Drop old unique constraint if it exists
    existing_constraints = inspector.get_unique_constraints('artefacts')
    for constraint in existing_constraints:
        if constraint['name'] == 'uq_artefacts_s3_location':
            op.drop_constraint('uq_artefacts_s3_location', 'artefacts', type_='unique')
            break
    
    # Create new unique constraint with version_id for versioning support
    op.create_unique_constraint(
        'uq_artefacts_s3_location_version',
        'artefacts',
        ['s3_bucket', 's3_key', 'version_id']
    )
    
    # Add new indexes for Task 7.11
    
    # Index on etag for integrity checks
    op.create_index(
        'idx_artefacts_etag',
        'artefacts',
        ['etag'],
        postgresql_where=sa.text('etag IS NOT NULL')
    )
    
    # Index on deletion_pending for garbage collection queries
    op.create_index(
        'idx_artefacts_deletion_pending',
        'artefacts',
        ['deletion_pending'],
        postgresql_where=sa.text('deletion_pending = true')
    )
    
    # Index on storage_class for lifecycle management
    op.create_index(
        'idx_artefacts_storage_class',
        'artefacts',
        ['storage_class']
    )
    
    # Composite index for version queries
    op.create_index(
        'idx_artefacts_bucket_key_version',
        'artefacts',
        ['s3_bucket', 's3_key', 'version_id']
    )
    
    logger.info("Task 7.11 migration completed successfully")


def downgrade() -> None:
    """
    Remove Task 7.11 fields from artefacts table.
    """
    
    # Drop new indexes
    op.drop_index('idx_artefacts_bucket_key_version', 'artefacts')
    op.drop_index('idx_artefacts_storage_class', 'artefacts')
    op.drop_index('idx_artefacts_deletion_pending', 'artefacts')
    op.drop_index('idx_artefacts_etag', 'artefacts')
    
    # Drop new unique constraint
    op.drop_constraint('uq_artefacts_s3_location_version', 'artefacts', type_='unique')
    
    # Restore old unique constraint
    op.create_unique_constraint(
        'uq_artefacts_s3_location',
        'artefacts',
        ['s3_bucket', 's3_key']
    )
    
    # Drop new columns
    op.drop_column('artefacts', 'last_error')
    op.drop_column('artefacts', 'deletion_pending')
    op.drop_column('artefacts', 'request_id')
    op.drop_column('artefacts', 'exporter_version')
    op.drop_column('artefacts', 'content_disposition')
    op.drop_column('artefacts', 'content_type')
    op.drop_column('artefacts', 'storage_class')
    op.drop_column('artefacts', 'etag')
    op.drop_column('artefacts', 'region')
    
    logger.info("Task 7.11 migration rolled back successfully")