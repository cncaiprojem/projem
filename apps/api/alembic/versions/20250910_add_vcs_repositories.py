"""Add VCS repositories table for version control system

Revision ID: add_vcs_repositories
Revises: latest
Create Date: 2025-09-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_vcs_repositories'
down_revision = 'task_711_artefact_storage'  # Points to the previous migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create vcs_repositories table."""
    
    # Create vcs_repositories table
    op.create_table(
        'vcs_repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('repository_id', sa.String(length=64), nullable=False, comment='Unique repository identifier'),
        sa.Column('name', sa.String(length=255), nullable=False, comment='Repository name'),
        sa.Column('description', sa.Text(), nullable=True, comment='Repository description'),
        sa.Column('owner_id', sa.Integer(), nullable=False, comment='Repository owner'),
        sa.Column('storage_path', sa.String(length=512), nullable=False, comment='Physical storage path for repository data'),
        sa.Column('use_real_freecad', sa.Boolean(), nullable=False, server_default='false', comment='Whether to use real FreeCAD API'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Whether repository is active'),
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default='false', comment='Whether repository is locked for maintenance'),
        sa.Column('current_branch', sa.String(length=255), nullable=True, server_default='main', comment='Current active branch'),
        sa.Column('commit_count', sa.Integer(), nullable=False, server_default='0', comment='Total number of commits'),
        sa.Column('branch_count', sa.Integer(), nullable=False, server_default='1', comment='Total number of branches'),
        sa.Column('tag_count', sa.Integer(), nullable=False, server_default='0', comment='Total number of tags'),
        sa.Column('storage_size_bytes', sa.BigInteger(), nullable=True, comment='Repository storage size in bytes'),
        sa.Column('last_commit_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp of last commit'),
        sa.Column('last_gc_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp of last garbage collection'),
        sa.Column('repo_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Additional repository metadata'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name='fk_vcs_repositories_owner_id_users', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name='pk_vcs_repositories'),
        sa.UniqueConstraint('repository_id', name='uq_vcs_repositories_repository_id'),
        sa.UniqueConstraint('owner_id', 'name', name='uq_vcs_repositories_owner_name')
    )
    
    # Create indexes
    # Note: repository_id already has a unique constraint, so separate index is redundant
    op.create_index('ix_vcs_repositories_owner_id_is_active', 'vcs_repositories', ['owner_id', 'is_active'])
    op.create_index('ix_vcs_repositories_repository_id_is_active', 'vcs_repositories', ['repository_id', 'is_active'])
    
    # Add update trigger for updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER update_vcs_repositories_updated_at 
        BEFORE UPDATE ON vcs_repositories 
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """Drop vcs_repositories table and related objects."""
    
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS update_vcs_repositories_updated_at ON vcs_repositories")
    
    # Drop function only if no other tables use it
    op.execute("""
        DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
    """)
    
    # Drop indexes
    op.drop_index('ix_vcs_repositories_repository_id_is_active', table_name='vcs_repositories')
    op.drop_index('ix_vcs_repositories_owner_id_is_active', table_name='vcs_repositories')
    
    # Drop table
    op.drop_table('vcs_repositories')