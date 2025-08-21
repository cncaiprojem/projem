"""Task 5.7: Artefact persistence with S3 tagging and audit logging

Revision ID: task_57_artefacts
Revises: 20250120_add_file_metadata_tables
Create Date: 2025-08-21 10:00:00.000000

Task 5.7 Requirements:
- Create/update artefacts table with all required fields
- Add foreign keys to jobs, users, and machines tables
- Create indexes for performance
- Add unique constraint on s3_bucket + s3_key
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = 'task_57_artefacts'
down_revision = '20250120_add_file_metadata_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create/update artefacts table for Task 5.7.
    """
    
    # Check if artefacts table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    if 'artefacts' in inspector.get_table_names():
        # Table exists, update it with new columns
        
        # Add new columns if they don't exist
        existing_columns = [col['name'] for col in inspector.get_columns('artefacts')]
        
        if 's3_bucket' not in existing_columns:
            op.add_column('artefacts', sa.Column('s3_bucket', sa.String(255), nullable=True))
            # Update existing records with default bucket
            op.execute("UPDATE artefacts SET s3_bucket = 'artefacts' WHERE s3_bucket IS NULL")
            op.alter_column('artefacts', 's3_bucket', nullable=False)
        
        if 's3_key' not in existing_columns:
            # Rename s3_key from old column if exists
            if 'key' in existing_columns:
                op.alter_column('artefacts', 'key', new_column_name='s3_key')
            else:
                op.add_column('artefacts', sa.Column('s3_key', sa.String(1024), nullable=True))
                # Update from existing data if available
                op.execute("UPDATE artefacts SET s3_key = COALESCE(s3_key, CONCAT('legacy/', id::text)) WHERE s3_key IS NULL")
                op.alter_column('artefacts', 's3_key', nullable=False)
        
        if 'sha256' not in existing_columns:
            op.add_column('artefacts', sa.Column('sha256', sa.String(64), nullable=True))
            # Set a placeholder for existing records
            op.execute("UPDATE artefacts SET sha256 = REPEAT('0', 64) WHERE sha256 IS NULL")
            op.alter_column('artefacts', 'sha256', nullable=False)
        
        if 'mime_type' not in existing_columns:
            # Rename from mime if exists
            if 'mime' in existing_columns:
                op.alter_column('artefacts', 'mime', new_column_name='mime_type')
            else:
                op.add_column('artefacts', sa.Column('mime_type', sa.String(100), nullable=True))
                op.execute("UPDATE artefacts SET mime_type = 'application/octet-stream' WHERE mime_type IS NULL")
                op.alter_column('artefacts', 'mime_type', nullable=False)
        
        if 'created_by' not in existing_columns:
            op.add_column('artefacts', sa.Column('created_by', sa.Integer(), nullable=True))
            # Check if we have any users in the database
            result = op.get_bind().execute("SELECT COUNT(*) FROM users").scalar()
            if result > 0:
                # Set to first user (preferably admin)
                op.execute("""
                    UPDATE artefacts 
                    SET created_by = COALESCE(
                        (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1),
                        (SELECT id FROM users ORDER BY id LIMIT 1)
                    ) 
                    WHERE created_by IS NULL
                """)
            else:
                # Create a system user if no users exist
                op.execute("""
                    INSERT INTO users (email, full_name, role, is_active, created_at, updated_at)
                    VALUES ('system@localhost', 'System User', 'admin', true, NOW(), NOW())
                    ON CONFLICT (email) DO NOTHING
                """)
                op.execute("""
                    UPDATE artefacts 
                    SET created_by = (SELECT id FROM users WHERE email = 'system@localhost' LIMIT 1)
                    WHERE created_by IS NULL
                """)
            op.alter_column('artefacts', 'created_by', nullable=False)
        
        if 'machine_id' not in existing_columns:
            op.add_column('artefacts', sa.Column('machine_id', sa.Integer(), nullable=True))
        
        if 'post_processor' not in existing_columns:
            op.add_column('artefacts', sa.Column('post_processor', sa.String(100), nullable=True))
        
        if 'version_id' not in existing_columns:
            op.add_column('artefacts', sa.Column('version_id', sa.String(255), nullable=True))
        
        # Add foreign key constraints if they don't exist
        existing_fks = [fk['name'] for fk in inspector.get_foreign_keys('artefacts')]
        
        if 'fk_artefacts_created_by' not in existing_fks:
            op.create_foreign_key(
                'fk_artefacts_created_by',
                'artefacts', 'users',
                ['created_by'], ['id'],
                ondelete='RESTRICT'
            )
        
        if 'fk_artefacts_machine_id' not in existing_fks:
            op.create_foreign_key(
                'fk_artefacts_machine_id',
                'artefacts', 'machines',
                ['machine_id'], ['id'],
                ondelete='SET NULL'
            )
        
        # Add unique constraint if it doesn't exist
        existing_constraints = [const['name'] for const in inspector.get_unique_constraints('artefacts')]
        if 'uq_artefacts_s3_location' not in existing_constraints:
            op.create_unique_constraint(
                'uq_artefacts_s3_location',
                'artefacts',
                ['s3_bucket', 's3_key']
            )
        
        # Add new indexes if they don't exist
        existing_indexes = [idx['name'] for idx in inspector.get_indexes('artefacts')]
        
        if 'idx_artefacts_created_by_type' not in existing_indexes:
            op.create_index(
                'idx_artefacts_created_by_type',
                'artefacts',
                ['created_by', 'type']
            )
        
        if 'idx_artefacts_machine_post' not in existing_indexes:
            op.create_index(
                'idx_artefacts_machine_post',
                'artefacts',
                ['machine_id', 'post_processor'],
                postgresql_where=sa.text('machine_id IS NOT NULL')
            )
        
    else:
        # Create new artefacts table from scratch
        op.create_table(
            'artefacts',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('job_id', sa.Integer(), nullable=False),
            sa.Column('s3_bucket', sa.String(255), nullable=False),
            sa.Column('s3_key', sa.String(1024), nullable=False),
            sa.Column('size_bytes', sa.BigInteger(), nullable=False),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('mime_type', sa.String(100), nullable=False),
            sa.Column('type', sa.String(50), nullable=False, comment='Type: model, gcode, report, invoice, log, simulation, etc.'),
            sa.Column('created_by', sa.Integer(), nullable=False),
            sa.Column('machine_id', sa.Integer(), nullable=True),
            sa.Column('post_processor', sa.String(100), nullable=True),
            sa.Column('version_id', sa.String(255), nullable=True),
            sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Additional metadata: tags, retention, compliance info, etc.'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name='fk_artefacts_job_id', ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_artefacts_created_by', ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], name='fk_artefacts_machine_id', ondelete='SET NULL'),
            sa.UniqueConstraint('s3_bucket', 's3_key', name='uq_artefacts_s3_location')
        )
        
        # Create indexes
        op.create_index('idx_artefacts_job_id', 'artefacts', ['job_id'])
        op.create_index('idx_artefacts_s3_bucket', 'artefacts', ['s3_bucket'])
        op.create_index('idx_artefacts_s3_key', 'artefacts', ['s3_key'])
        op.create_index('idx_artefacts_type', 'artefacts', ['type'])
        op.create_index('idx_artefacts_created_by', 'artefacts', ['created_by'])
        op.create_index('idx_artefacts_machine_id', 'artefacts', ['machine_id'])
        op.create_index('idx_artefacts_post_processor', 'artefacts', ['post_processor'])
        op.create_index('idx_artefacts_version_id', 'artefacts', ['version_id'])
        op.create_index('idx_artefacts_sha256', 'artefacts', ['sha256'])
        op.create_index('idx_artefacts_size_bytes', 'artefacts', ['size_bytes'])
        op.create_index('idx_artefacts_created_at', 'artefacts', ['created_at'])
        op.create_index('idx_artefacts_job_id_type', 'artefacts', ['job_id', 'type'])
        op.create_index('idx_artefacts_created_by_type', 'artefacts', ['created_by', 'type'])
        op.create_index(
            'idx_artefacts_machine_post',
            'artefacts',
            ['machine_id', 'post_processor'],
            postgresql_where=sa.text('machine_id IS NOT NULL')
        )
        op.create_index(
            'idx_artefacts_meta_gin',
            'artefacts',
            ['meta'],
            postgresql_using='gin',
            postgresql_where=sa.text('meta IS NOT NULL')
        )
    
    # Add comment to table
    op.execute("COMMENT ON TABLE artefacts IS 'Task 5.7: File artefacts with S3 tagging and audit logging'")


def downgrade() -> None:
    """
    Comprehensive downgrade to fully remove the artefacts table and all dependencies.
    
    WARNING: This will permanently delete all artefact data!
    Make sure to backup the artefacts table before running this downgrade:
    
    pg_dump -t artefacts -a your_database > artefacts_backup.sql
    """
    
    # Step 1: Drop all indexes on artefacts table
    indexes_to_drop = [
        'idx_artefacts_job_id',
        'idx_artefacts_created_by',
        'idx_artefacts_type',
        'idx_artefacts_sha256',
        'idx_artefacts_created_at',
        'idx_artefacts_s3_search',
        'idx_artefacts_job_id_type',
        'idx_artefacts_created_by_type',
        'idx_artefacts_machine_post',
        'idx_artefacts_meta_gin',
    ]
    
    for idx_name in indexes_to_drop:
        try:
            op.drop_index(idx_name, table_name='artefacts', if_exists=True)
            logger.info(f"Dropped index: {idx_name}")
        except Exception as e:
            # Index may not exist, log and continue
            logger.warning(f"Could not drop index {idx_name}: {e}")
    
    # Step 2: Drop all constraints on artefacts table
    constraints_to_drop = [
        ('fk_artefacts_job_id', 'foreignkey'),
        ('fk_artefacts_created_by', 'foreignkey'),
        ('fk_artefacts_machine_id', 'foreignkey'),
        ('uq_artefacts_s3_location', 'unique'),
        ('ck_artefacts_size_positive', 'check'),
        ('ck_artefacts_sha256_format', 'check'),
    ]
    
    for constraint_name, constraint_type in constraints_to_drop:
        try:
            op.drop_constraint(constraint_name, 'artefacts', type_=constraint_type)
            logger.info(f"Dropped constraint: {constraint_name}")
        except Exception as e:
            # Constraint may not exist, log and continue
            logger.warning(f"Could not drop constraint {constraint_name}: {e}")
    
    # Step 3: Check if table exists before dropping
    connection = op.get_bind()
    result = connection.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables "
            "  WHERE table_schema = 'public' "
            "  AND table_name = 'artefacts'"
            ")"
        )
    )
    table_exists = result.scalar()
    
    if table_exists:
        # Step 4: Count records that will be deleted (for logging)
        try:
            count_result = connection.execute(sa.text("SELECT COUNT(*) FROM artefacts"))
            record_count = count_result.scalar()
            logger.warning(
                f"DROPPING artefacts table with {record_count} records. "
                f"Ensure you have backed up this data if needed!"
            )
        except Exception as e:
            logger.warning(f"Could not count artefacts records: {e}")
        
        # Step 5: Drop the artefacts table completely
        op.drop_table('artefacts')
        logger.info("Successfully dropped artefacts table")
    else:
        logger.info("Artefacts table does not exist, nothing to drop")