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
    
    # Step 3: Drop the foreign key constraint
    op.drop_constraint('file_metadata_user_id_fkey', 'file_metadata', type_='foreignkey')
    
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
    
    # Step 3: Drop the foreign key constraint
    op.drop_constraint('upload_sessions_user_id_fkey', 'upload_sessions', type_='foreignkey')
    
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
    
    Converting from Integer back to UUID would require generating new UUIDs
    for each user_id, which would break existing foreign key relationships
    and lose the original UUID values. The users table uses Integer IDs,
    so creating a foreign key from UUID to Integer is not possible.
    
    If you need to revert this migration, you should:
    1. Backup your data
    2. Manually handle the data migration
    3. Or restore from a backup taken before this migration
    """
    raise NotImplementedError(
        "Downgrade is not supported for this migration. "
        "Converting Integer user IDs back to UUID would break foreign key relationships "
        "since the users table uses Integer IDs. Please restore from backup if needed."
    )