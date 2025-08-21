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
    """Fix user_id columns to be Integer instead of UUID."""
    
    # Fix FileMetadata.user_id
    # First drop the foreign key constraint
    op.drop_constraint('file_metadata_user_id_fkey', 'file_metadata', type_='foreignkey')
    
    # Change column type from UUID to Integer
    # Note: This will fail if there's existing data with UUID values
    # In production, you'd need to handle data migration
    op.alter_column('file_metadata', 'user_id',
                    type_=sa.Integer(),
                    existing_type=postgresql.UUID(as_uuid=True),
                    postgresql_using='NULL')  # Clear existing values
    
    # Re-add the foreign key constraint
    op.create_foreign_key('file_metadata_user_id_fkey', 
                          'file_metadata', 'users',
                          ['user_id'], ['id'],
                          ondelete='SET NULL')
    
    # Fix UploadSession.user_id
    # First drop the foreign key constraint
    op.drop_constraint('upload_sessions_user_id_fkey', 'upload_sessions', type_='foreignkey')
    
    # Change column type from UUID to Integer
    op.alter_column('upload_sessions', 'user_id',
                    type_=sa.Integer(),
                    existing_type=postgresql.UUID(as_uuid=True),
                    postgresql_using='NULL')  # Clear existing values
    
    # Re-add the foreign key constraint
    op.create_foreign_key('upload_sessions_user_id_fkey',
                          'upload_sessions', 'users',
                          ['user_id'], ['id'],
                          ondelete='SET NULL')


def downgrade() -> None:
    """Revert user_id columns back to UUID (not recommended)."""
    
    # Revert UploadSession.user_id
    op.drop_constraint('upload_sessions_user_id_fkey', 'upload_sessions', type_='foreignkey')
    op.alter_column('upload_sessions', 'user_id',
                    type_=postgresql.UUID(as_uuid=True),
                    existing_type=sa.Integer(),
                    postgresql_using='gen_random_uuid()')
    op.create_foreign_key('upload_sessions_user_id_fkey',
                          'upload_sessions', 'users',
                          ['user_id'], ['id'],
                          ondelete='SET NULL')
    
    # Revert FileMetadata.user_id
    op.drop_constraint('file_metadata_user_id_fkey', 'file_metadata', type_='foreignkey')
    op.alter_column('file_metadata', 'user_id',
                    type_=postgresql.UUID(as_uuid=True),
                    existing_type=sa.Integer(),
                    postgresql_using='gen_random_uuid()')
    op.create_foreign_key('file_metadata_user_id_fkey',
                          'file_metadata', 'users',
                          ['user_id'], ['id'],
                          ondelete='SET NULL')