"""Task 7.15: Database migrations and schema setup for model flows

This migration creates the database schema for FreeCAD model generation flows including:
- models table with FreeCAD 1.1.0 versioning fields
- ai_suggestions table with Turkish KVKK compliance
- artefacts table enhancements (already exists, adding fields)
- topology_hashes table for OCCT 7.8.x deterministic exports

Revision ID: 20250827_213512_task_715
Revises: 20250825_add_params_hash_and_idempotency_constraint
Create Date: 2025-08-27 21:35:12.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text
import logging

# Configure logger
logger = logging.getLogger(__name__)

# revision identifiers
revision = '20250827_213512_task_715'
down_revision = '20250825_add_params_hash_and_idempotency_constraint'
branch_labels = None
depends_on = None


def create_enum_safe(enum_name: str, values: list) -> None:
    """Create enum type if it doesn't exist with proper transaction handling."""
    import re
    if not re.match(r'^[a-z_][a-z0-9_]*$', enum_name):
        raise ValueError(f"Invalid enum name: {enum_name}")
    
    connection = op.get_bind()
    try:
        # Check if enum exists first
        result = connection.execute(
            text("SELECT 1 FROM pg_type WHERE typname = :name"),
            {"name": enum_name}
        )
        if result.fetchone():
            logger.info(f"Enum type {enum_name} already exists, skipping")
            return
        
        # Create the enum
        values_str = ', '.join([f"'{v}'" for v in values])
        connection.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({values_str})"))
        logger.info(f"Created enum type: {enum_name}")
    except sa.exc.ProgrammingError as e:
        error_msg = str(e).lower()
        if 'already exists' in error_msg or 'duplicate type' in error_msg:
            logger.info(f"Enum type {enum_name} already exists, skipping")
        else:
            logger.error(f"Failed to create enum {enum_name}: {e}")
            raise


def upgrade() -> None:
    """Apply Task 7.15 database schema for model flows."""
    
    connection = op.get_bind()
    
    # Pre-upgrade guard: Check if models table exists and has data
    result = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'models'
    """))
    models_table_exists = result.scalar() > 0
    
    if models_table_exists:
        # Check for existing models with status in processing or completed
        result = connection.execute(text("""
            SELECT COUNT(*) FROM models 
            WHERE status IN ('processing', 'completed')
        """))
        existing_models_count = result.scalar()
        
        if existing_models_count > 0:
            logger.warning(f"Found {existing_models_count} existing models with processing/completed status")
            # Would need to check freecad_version and occt_version are present
            # For now we'll proceed as this is a new table structure
    
    # Create enums for model status and artefact file types
    create_enum_safe('model_status', ['pending', 'processing', 'completed', 'failed'])
    create_enum_safe('artefact_file_type', ['fcstd', 'step', 'stl', 'glb', 'iges', 'brep', 'obj', 'ply', 'dxf', 'svg', 'pdf', 'gcode'])
    create_enum_safe('shape_kind', ['Solid', 'Shell', 'Face', 'Edge', 'Vertex'])
    
    # Create models table with FreeCAD 1.1.0 alignment
    if not models_table_exists:
        op.create_table('models',
            sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column('job_id', sa.BigInteger(), nullable=False),
            sa.Column('canonical_params', postgresql.JSONB(), nullable=False, 
                     comment='Canonical parameters used for model generation'),
            sa.Column('script_hash', sa.String(64), nullable=False,
                     comment='SHA256 hash of the generation script'),
            sa.Column('status', postgresql.ENUM('pending', 'processing', 'completed', 'failed', 
                                               name='model_status', create_type=False), 
                     nullable=False, server_default='pending'),
            
            # FreeCAD 1.1.0 versioning fields
            sa.Column('freecad_version', sa.String(16), nullable=False,
                     comment='FreeCAD version (must match 1.1.x pattern)'),
            sa.Column('occt_version', sa.String(16), nullable=False,
                     comment='OpenCASCADE version (must match 7.8.x pattern)'),
            sa.Column('model_rev', sa.Integer(), nullable=False, server_default='1',
                     comment='Model revision number'),
            sa.Column('parent_model_id', sa.BigInteger(), nullable=True,
                     comment='Reference to parent model for versioning'),
            sa.Column('freecad_doc_uuid', postgresql.UUID(), nullable=True,
                     comment='FreeCAD document UUID'),
            sa.Column('doc_schema_version', sa.SmallInteger(), nullable=False, server_default='110',
                     comment='FreeCAD document schema version'),
            
            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, 
                     server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, 
                     server_default=sa.func.now(), onupdate=sa.func.now()),
            
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], 
                                  name='fk_models_job_id', ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['parent_model_id'], ['models.id'], 
                                  name='fk_models_parent_model_id', ondelete='SET NULL'),
            
            # Check constraints for version validation
            sa.CheckConstraint("freecad_version ~ '^1\\.1\\.\\d+$'", 
                             name='ck_models_freecad_version'),
            sa.CheckConstraint("occt_version ~ '^7\\.8\\.\\d+$'", 
                             name='ck_models_occt_version'),
            sa.CheckConstraint('model_rev > 0', 
                             name='ck_models_model_rev_positive'),
            
            # Unique constraint for document UUID and revision
            sa.UniqueConstraint('freecad_doc_uuid', 'model_rev', 
                              name='uq_models_doc_uuid_rev',
                              postgresql_where=text('freecad_doc_uuid IS NOT NULL')),
            
            comment='FreeCAD model generation records with versioning'
        )
        
        # Create indexes for models table
        op.create_index('idx_models_job_id', 'models', ['job_id'])
        op.create_index('idx_models_status', 'models', ['status'])
        op.create_index('idx_models_script_hash', 'models', ['script_hash'])
        op.create_index('idx_models_freecad_doc_uuid', 'models', ['freecad_doc_uuid'])
        op.create_index('idx_models_model_rev', 'models', ['model_rev'])
        op.create_index('idx_models_created_at', 'models', ['created_at'])
        op.create_index('idx_models_versions', 'models', ['freecad_version', 'occt_version'])
        op.create_index('idx_models_canonical_params', 'models', ['canonical_params'],
                       postgresql_using='gin',
                       postgresql_where=text('canonical_params IS NOT NULL'))
    
    # Create ai_suggestions table with Turkish KVKK compliance
    op.create_table('ai_suggestions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False,
                 comment='User prompt (PII masked for KVKK compliance)'),
        sa.Column('response', postgresql.JSONB(), nullable=False,
                 comment='AI response in structured format'),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('request_id', sa.String(255), nullable=False,
                 comment='Unique request identifier for tracing'),
        sa.Column('model_name', sa.String(100), nullable=True,
                 comment='AI model used for generation'),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True,
                 comment='Number of tokens in prompt'),
        sa.Column('response_tokens', sa.Integer(), nullable=True,
                 comment='Number of tokens in response'),
        sa.Column('total_cost_cents', sa.Integer(), nullable=True,
                 comment='Total cost in cents for this request'),
        sa.Column('metadata', postgresql.JSONB(), nullable=True,
                 comment='Additional metadata and context'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, 
                 server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                 server_default=sa.func.now()),
        sa.Column('retention_expires_at', sa.DateTime(timezone=True), nullable=True,
                 comment='KVKK compliance: When this record should be deleted'),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], 
                              name='fk_ai_suggestions_user_id', ondelete='CASCADE'),
        sa.UniqueConstraint('request_id', name='uq_ai_suggestions_request_id'),
        
        comment='AI suggestion records with Turkish KVKK compliance'
    )
    
    # Create indexes for ai_suggestions
    op.create_index('idx_ai_suggestions_user_id', 'ai_suggestions', ['user_id'])
    op.create_index('idx_ai_suggestions_request_id', 'ai_suggestions', ['request_id'])
    op.create_index('idx_ai_suggestions_created_at', 'ai_suggestions', ['created_at'])
    op.create_index('idx_ai_suggestions_retention_expires', 'ai_suggestions', 
                   ['retention_expires_at'],
                   postgresql_where=text('retention_expires_at IS NOT NULL'))
    op.create_index('idx_ai_suggestions_response', 'ai_suggestions', ['response'],
                   postgresql_using='gin')
    op.create_index('idx_ai_suggestions_metadata', 'ai_suggestions', ['metadata'],
                   postgresql_using='gin',
                   postgresql_where=text('metadata IS NOT NULL'))
    
    # Add file_type enum column to artefacts table if it doesn't exist
    # Check if column exists
    result = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'artefacts' 
        AND column_name = 'file_type'
    """))
    
    if result.scalar() == 0:
        op.add_column('artefacts', 
            sa.Column('file_type', 
                     postgresql.ENUM('fcstd', 'step', 'stl', 'glb', 'iges', 'brep', 
                                   'obj', 'ply', 'dxf', 'svg', 'pdf', 'gcode',
                                   name='artefact_file_type', create_type=False),
                     nullable=True,
                     comment='File type enumeration for better querying')
        )
        
        # Migrate existing type field to file_type enum
        connection.execute(text("""
            UPDATE artefacts 
            SET file_type = CASE 
                WHEN LOWER(type) IN ('fcstd') THEN 'fcstd'::artefact_file_type
                WHEN LOWER(type) IN ('step', 'stp') THEN 'step'::artefact_file_type
                WHEN LOWER(type) IN ('stl') THEN 'stl'::artefact_file_type
                WHEN LOWER(type) IN ('glb', 'gltf') THEN 'glb'::artefact_file_type
                WHEN LOWER(type) IN ('gcode', 'g-code', 'nc') THEN 'gcode'::artefact_file_type
                ELSE NULL
            END
            WHERE file_type IS NULL
        """))
    
    # Add metadata GIN indexes to artefacts if not exists
    # Check for existing GIN index on metadata
    result = connection.execute(text("""
        SELECT COUNT(*) FROM pg_indexes 
        WHERE schemaname = 'public' 
        AND tablename = 'artefacts' 
        AND indexname = 'idx_artefacts_metadata_assembly4'
    """))
    
    if result.scalar() == 0:
        # Add expression index for Assembly4 constraints
        op.create_index('idx_artefacts_metadata_assembly4', 'artefacts',
                       [text("(meta->'assembly4'->'constraints')")],
                       postgresql_using='gin',
                       postgresql_where=text("meta->'assembly4' IS NOT NULL"))
        
        # Add expression index for FreeCAD document index
        op.create_index('idx_artefacts_metadata_freecad_doc', 'artefacts',
                       [text("(meta->'freecad'->'document_index')")],
                       postgresql_using='gin',
                       postgresql_where=text("meta->'freecad' IS NOT NULL"))
    
    # Create topology_hashes table for OCCT 7.8.x deterministic exports
    op.create_table('topology_hashes',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('artefact_id', sa.BigInteger(), nullable=False),
        sa.Column('object_path', sa.Text(), nullable=False,
                 comment='Object path in model tree, e.g., Body/Pad/Face6'),
        sa.Column('shape_kind', postgresql.ENUM('Solid', 'Shell', 'Face', 'Edge', 'Vertex',
                                               name='shape_kind', create_type=False),
                 nullable=False),
        sa.Column('topo_hash', sa.Text(), nullable=False,
                 comment='Stable hash from OCCT 7.8.x'),
        sa.Column('occt_algo_version', sa.String(16), nullable=False, server_default='7.8.x',
                 comment='OCCT algorithm version used'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, 
                 server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                 server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['artefact_id'], ['artefacts.id'], 
                              name='fk_topology_hashes_artefact_id', ondelete='CASCADE'),
        sa.UniqueConstraint('artefact_id', 'object_path', 'shape_kind',
                          name='uq_topology_hashes_artefact_path_kind'),
        
        comment='OCCT topology hashes for deterministic shape exports'
    )
    
    # Create indexes for topology_hashes
    op.create_index('idx_topology_hashes_artefact_id', 'topology_hashes', ['artefact_id'])
    op.create_index('idx_topology_hashes_topo_hash', 'topology_hashes', ['topo_hash'])
    op.create_index('idx_topology_hashes_occt_algo_version', 'topology_hashes', 
                   ['occt_algo_version'])
    
    # Add idempotency_key constraint to jobs table if missing
    result = connection.execute(text("""
        SELECT COUNT(*) FROM pg_indexes 
        WHERE schemaname = 'public' 
        AND tablename = 'jobs' 
        AND indexname = 'uq_jobs_idempotency_key'
    """))
    
    if result.scalar() == 0:
        op.create_index('uq_jobs_idempotency_key', 'jobs', ['idempotency_key'],
                       unique=True,
                       postgresql_where=text('idempotency_key IS NOT NULL'))
    
    # Create generic function to update updated_at timestamp
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))
    
    # Add updated_at triggers to all tables that have the column
    tables_with_updated_at = ['models', 'ai_suggestions', 'topology_hashes']
    for table_name in tables_with_updated_at:
        connection.execute(text(f"""
            DROP TRIGGER IF EXISTS update_{table_name}_updated_at ON {table_name};
            
            CREATE TRIGGER update_{table_name}_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """))
    
    # Create trigger to increment model_rev on derived model creation
    # Fixed: Base revision on freecad_doc_uuid, not parent_model_id
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION increment_model_rev()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Only auto-increment if freecad_doc_uuid is provided
            IF NEW.freecad_doc_uuid IS NOT NULL THEN
                -- Get the max revision for this document UUID
                SELECT COALESCE(MAX(model_rev), 0) + 1
                INTO NEW.model_rev
                FROM models
                WHERE freecad_doc_uuid = NEW.freecad_doc_uuid;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        
        DROP TRIGGER IF EXISTS trigger_increment_model_rev ON models;
        
        CREATE TRIGGER trigger_increment_model_rev
        BEFORE INSERT ON models
        FOR EACH ROW
        EXECUTE FUNCTION increment_model_rev();
    """))
    
    logger.info("✅ Task 7.15 migration completed successfully")


def downgrade() -> None:
    """Rollback Task 7.15 database schema changes."""
    
    connection = op.get_bind()
    
    # Drop updated_at triggers
    tables_with_updated_at = ['models', 'ai_suggestions', 'topology_hashes']
    for table_name in tables_with_updated_at:
        connection.execute(text(f"""
            DROP TRIGGER IF EXISTS update_{table_name}_updated_at ON {table_name};
        """))
    
    # Drop trigger functions
    connection.execute(text("""
        DROP TRIGGER IF EXISTS trigger_increment_model_rev ON models;
        DROP FUNCTION IF EXISTS increment_model_rev();
        DROP FUNCTION IF EXISTS update_updated_at_column();
    """))
    
    # Drop tables in reverse order due to foreign keys
    op.drop_table('topology_hashes')
    op.drop_table('ai_suggestions')
    
    # Check if models table exists before dropping
    result = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'models'
    """))
    
    if result.scalar() > 0:
        op.drop_table('models')
    
    # Remove added columns from artefacts (if they were added)
    result = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'artefacts' 
        AND column_name = 'file_type'
    """))
    
    if result.scalar() > 0:
        op.drop_column('artefacts', 'file_type')
    
    # Drop indexes if they exist
    op.drop_index('idx_artefacts_metadata_assembly4', 'artefacts', if_exists=True)
    op.drop_index('idx_artefacts_metadata_freecad_doc', 'artefacts', if_exists=True)
    op.drop_index('uq_jobs_idempotency_key', 'jobs', if_exists=True)
    
    # Drop enums
    connection.execute(text("DROP TYPE IF EXISTS model_status"))
    connection.execute(text("DROP TYPE IF EXISTS artefact_file_type"))
    connection.execute(text("DROP TYPE IF EXISTS shape_kind"))
    
    logger.info("✅ Task 7.15 migration rolled back successfully")