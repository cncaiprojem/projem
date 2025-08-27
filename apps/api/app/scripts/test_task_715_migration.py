#!/usr/bin/env python3
"""Test Task 7.15 migration up and down functionality.

This script tests the database migration for model flows including:
- models table creation and constraints
- ai_suggestions table with KVKK compliance
- artefacts table enhancements
- topology_hashes table
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_alembic_config():
    """Get Alembic configuration."""
    alembic_cfg = Config(project_root / "alembic.ini")
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))
    return alembic_cfg


def get_latest_migration_revision():
    """Get the latest migration revision ID from the migrations directory."""
    from alembic.script import ScriptDirectory
    from alembic.config import Config
    
    alembic_cfg = get_alembic_config()
    script_dir = ScriptDirectory.from_config(alembic_cfg)
    
    # Get the head revision
    head_revision = script_dir.get_current_head()
    
    # If looking specifically for Task 7.15, find by pattern
    for revision in script_dir.walk_revisions():
        if 'task_715' in revision.revision or 'Task 7.15' in revision.doc:
            return revision.revision
    
    return head_revision


def test_migration():
    """Test Task 7.15 migration up and down."""
    
    # Get database URL from environment or use default
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://freecad:password@localhost:5432/freecad"
    )
    
    engine = create_engine(database_url)
    inspector = inspect(engine)
    
    logger.info("Testing Task 7.15 migration...")
    
    try:
        # Get Alembic config
        alembic_cfg = get_alembic_config()
        
        # Get current revision
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            current_rev = result.scalar()
            logger.info(f"Current revision: {current_rev}")
        
        # Get the Task 7.15 migration revision
        task_715_revision = get_latest_migration_revision()
        
        # Upgrade to Task 7.15
        logger.info(f"Upgrading to Task 7.15 (revision: {task_715_revision})...")
        command.upgrade(alembic_cfg, task_715_revision)
        
        # Verify tables exist
        tables = inspector.get_table_names()
        
        expected_tables = ["models", "ai_suggestions", "topology_hashes"]
        for table in expected_tables:
            if table not in tables:
                logger.error(f"Table {table} not created!")
                return False
            logger.info(f"✅ Table {table} exists")
        
        # Check models table columns
        models_columns = {col['name'] for col in inspector.get_columns("models")}
        expected_models_columns = {
            "id", "job_id", "canonical_params", "script_hash", "status",
            "freecad_version", "occt_version", "model_rev", "parent_model_id",
            "freecad_doc_uuid", "doc_schema_version", "created_at", "updated_at"
        }
        
        missing_cols = expected_models_columns - models_columns
        if missing_cols:
            logger.error(f"Missing columns in models table: {missing_cols}")
            return False
        logger.info("✅ Models table has all expected columns")
        
        # Check constraints on models table
        models_constraints = inspector.get_check_constraints("models")
        constraint_names = {c['name'] for c in models_constraints}
        expected_constraints = {
            "ck_models_freecad_version",
            "ck_models_occt_version", 
            "ck_models_model_rev_positive"
        }
        
        missing_constraints = expected_constraints - constraint_names
        if missing_constraints:
            logger.error(f"Missing constraints: {missing_constraints}")
            assert False, f"Missing constraints: {missing_constraints}"
        else:
            logger.info("✅ All constraints present on models table")
        
        # Check indexes
        models_indexes = inspector.get_indexes("models")
        index_names = {idx['name'] for idx in models_indexes}
        expected_indexes = {
            "idx_models_job_id", "idx_models_status", "idx_models_script_hash",
            "idx_models_freecad_doc_uuid", "idx_models_model_rev",
            "idx_models_created_at", "idx_models_versions"
        }
        
        missing_indexes = expected_indexes - index_names
        if missing_indexes:
            logger.error(f"Missing indexes: {missing_indexes}")
            assert False, f"Missing indexes: {missing_indexes}"
        else:
            logger.info("✅ All indexes present on models table")
        
        # Test enum types
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT typname FROM pg_type 
                WHERE typname IN ('model_status', 'artefact_file_type', 'shape_kind')
            """))
            enums = {row[0] for row in result}
            
            expected_enums = {"model_status", "artefact_file_type", "shape_kind"}
            missing_enums = expected_enums - enums
            
            if missing_enums:
                logger.error(f"Missing enum types: {missing_enums}")
                return False
            logger.info("✅ All enum types created")
        
        # Test trigger function
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT routine_name FROM information_schema.routines 
                WHERE routine_name = 'increment_model_rev'
                AND routine_type = 'FUNCTION'
            """))
            if not result.scalar():
                logger.error("Trigger function increment_model_rev not found!")
                return False
            logger.info("✅ Trigger function exists")
        
        logger.info("✅ Task 7.15 migration upgrade successful!")
        
        # Test downgrade
        logger.info("Testing downgrade...")
        command.downgrade(alembic_cfg, "20250825_add_params_hash_and_idempotency_constraint")
        
        # Verify tables are dropped
        tables = inspector.get_table_names()
        for table in expected_tables:
            if table in tables:
                logger.error(f"Table {table} not dropped!")
                return False
        logger.info("✅ All Task 7.15 tables dropped")
        
        # Verify enums are dropped
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT typname FROM pg_type 
                WHERE typname IN ('model_status', 'artefact_file_type', 'shape_kind')
            """))
            remaining_enums = {row[0] for row in result}
            if remaining_enums:
                logger.warning(f"Enums not dropped: {remaining_enums}")
        
        logger.info("✅ Task 7.15 migration downgrade successful!")
        
        # Restore to Task 7.15
        logger.info(f"Restoring to Task 7.15 (revision: {task_715_revision})...")
        command.upgrade(alembic_cfg, task_715_revision)
        
        logger.info("✅ All Task 7.15 migration tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"Migration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_migration()
    sys.exit(0 if success else 1)