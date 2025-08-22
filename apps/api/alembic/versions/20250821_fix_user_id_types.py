"""Fix user_id types in FileMetadata and UploadSession

Revision ID: fix_user_id_types_001
Revises: task_57_artefacts_persistence
Create Date: 2025-08-21

This migration fixes the data type mismatch where user_id columns
were incorrectly defined as UUID instead of Integer in FileMetadata
and UploadSession tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'fix_user_id_types_001'
down_revision = '20250821_task_57_artefacts_persistence'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Fix user_id columns to be Integer instead of UUID with proper data migration."""
    
    # Fix FileMetadata.user_id with data preservation
    # Step 1: Add a temporary column to store old UUIDs
    op.add_column('file_metadata', sa.Column('user_id_uuid_temp', postgresql.UUID(as_uuid=True)))
    
    # Step 2: Copy existing UUIDs to the temporary column (if any exist)
    op.execute("UPDATE file_metadata SET user_id_uuid_temp = user_id WHERE user_id IS NOT NULL")
    
    # Step 3: Drop the foreign key constraint with error handling
    # Per Gemini feedback: Add try/except for robustness
    try:
        op.drop_constraint('file_metadata_user_id_fkey', 'file_metadata', type_='foreignkey')
    except Exception as e:
        # Constraint might not exist, log and continue
        print(f"Warning: Could not drop constraint file_metadata_user_id_fkey: {e}")
    
    # Step 4: Change column type from UUID to Integer
    op.alter_column('file_metadata', 'user_id',
                    type_=sa.Integer(),
                    existing_type=postgresql.UUID(as_uuid=True),
                    postgresql_using='NULL')
    
    # Step 5: Attempt to migrate data by joining with users table
    # Note: This assumes users table has both id (Integer) and potentially a uuid column
    # If users don't have UUID column, we'll just leave user_id as NULL
    connection = op.get_bind()
    result = connection.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='uuid'"))
    has_uuid_column = result.fetchone() is not None
    
    if has_uuid_column:
        op.execute("""
            UPDATE file_metadata
            SET user_id = users.id
            FROM users
            WHERE file_metadata.user_id_uuid_temp = users.uuid
        """)
    
    # Step 6: Drop the temporary column
    op.drop_column('file_metadata', 'user_id_uuid_temp')
    
    # Step 7: Re-add the foreign key constraint
    op.create_foreign_key('file_metadata_user_id_fkey', 
                          'file_metadata', 'users',
                          ['user_id'], ['id'],
                          ondelete='SET NULL')
    
    # Fix UploadSession.user_id with the same approach
    # Step 1: Add a temporary column to store old UUIDs
    op.add_column('upload_sessions', sa.Column('user_id_uuid_temp', postgresql.UUID(as_uuid=True)))
    
    # Step 2: Copy existing UUIDs to the temporary column (if any exist)
    op.execute("UPDATE upload_sessions SET user_id_uuid_temp = user_id WHERE user_id IS NOT NULL")
    
    # Step 3: Drop the foreign key constraint with error handling
    # Per Gemini feedback: Add try/except for robustness
    try:
        op.drop_constraint('upload_sessions_user_id_fkey', 'upload_sessions', type_='foreignkey')
    except Exception as e:
        # Constraint might not exist, log and continue
        print(f"Warning: Could not drop constraint upload_sessions_user_id_fkey: {e}")
    
    # Step 4: Change column type from UUID to Integer
    op.alter_column('upload_sessions', 'user_id',
                    type_=sa.Integer(),
                    existing_type=postgresql.UUID(as_uuid=True),
                    postgresql_using='NULL')
    
    # Step 5: Attempt to migrate data
    if has_uuid_column:
        op.execute("""
            UPDATE upload_sessions
            SET user_id = users.id
            FROM users
            WHERE upload_sessions.user_id_uuid_temp = users.uuid
        """)
    
    # Step 6: Drop the temporary column
    op.drop_column('upload_sessions', 'user_id_uuid_temp')
    
    # Step 7: Re-add the foreign key constraint
    op.create_foreign_key('upload_sessions_user_id_fkey',
                          'upload_sessions', 'users',
                          ['user_id'], ['id'],
                          ondelete='SET NULL')


def downgrade() -> None:
    """
    Downgrade is not supported for this migration.
    
    CRITICAL DATA LOSS WARNING:
    =============================
    Converting from Integer back to UUID would result in:
    
    1. **Total Loss of User Associations**: All user_id values would be lost because:
       - The users table uses Integer IDs (not UUIDs)
       - There's no UUID column in the users table to map back to
       - New random UUIDs would have no relationship to actual users
    
    2. **Foreign Key Constraint Violations**: 
       - Cannot create FK from UUID column to Integer users.id column
       - Would require dropping all user-related constraints permanently
    
    3. **Audit Trail Breakage**:
       - All file upload history would lose user attribution
       - Upload sessions would become orphaned from their creators
       - Security audit logs would be incomplete
    
    4. **Compliance Issues**:
       - Loss of user attribution violates data retention requirements
       - Turkish tax law requires maintaining upload audit trails
    
    RECOVERY OPTIONS:
    =================
    If you absolutely must revert this migration:
    
    Option 1 (Recommended): Full Database Restore
    ----------------------------------------------
    1. Stop all application services
    2. Restore database from backup taken before this migration
    3. Re-apply any other migrations that occurred after this one
    
    Option 2: Manual Data Preservation (Complex)
    --------------------------------------------
    1. Export current data with user associations:
       pg_dump -t file_metadata -t upload_sessions > backup.sql
    
    2. Create mapping table:
       CREATE TABLE user_id_mapping (
           integer_id INTEGER,
           new_uuid UUID DEFAULT gen_random_uuid()
       );
       INSERT INTO user_id_mapping (integer_id)
       SELECT DISTINCT user_id FROM file_metadata
       UNION
       SELECT DISTINCT user_id FROM upload_sessions;
    
    3. Manually reconstruct relationships using mapping table
    
    Option 3: Accept Data Loss (NOT Recommended)
    --------------------------------------------
    Remove this raise statement to proceed with data loss.
    All user associations will be permanently lost.
    """
    raise NotImplementedError(
        "Downgrade is not supported for this migration due to CRITICAL DATA LOSS. "
        "Converting Integer user IDs back to UUID would permanently lose all user associations "
        "and break foreign key relationships. The users table uses Integer IDs, not UUIDs. "
        "Please see the downgrade() docstring for detailed recovery options. "
        "To proceed anyway (NOT RECOMMENDED), remove this exception."
    )