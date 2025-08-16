#!/usr/bin/env python3
"""
Migration script to update the application to use structlog.
This script updates imports and demonstrates the new logging patterns.
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

# Add the parent directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def update_imports_in_file(file_path: Path) -> bool:
    """
    Update logging imports in a single file.
    
    Args:
        file_path: Path to the Python file to update
    
    Returns:
        True if file was modified, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Replace old imports
        replacements = [
            ('from app.logging_setup import get_logger', 'from app.core.logging import get_logger'),
            ('from .logging_setup import get_logger', 'from .core.logging import get_logger'),
            ('from ..logging_setup import get_logger', 'from ..core.logging import get_logger'),
            ('import app.logging_setup', 'import app.core.logging'),
        ]
        
        for old, new in replacements:
            content = content.replace(old, new)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        
        return False
    
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False


def find_python_files(directory: Path, exclude_dirs: List[str] = None) -> List[Path]:
    """
    Find all Python files in a directory.
    
    Args:
        directory: Root directory to search
        exclude_dirs: Directories to exclude from search
    
    Returns:
        List of Python file paths
    """
    exclude_dirs = exclude_dirs or ['__pycache__', '.git', 'venv', '.venv', 'migrations']
    python_files = []
    
    for root, dirs, files in os.walk(directory):
        # Remove excluded directories from search
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            if file.endswith('.py'):
                python_files.append(Path(root) / file)
    
    return python_files


def demonstrate_new_patterns():
    """Demonstrate the new logging patterns."""
    print("\n" + "="*60)
    print("STRUCTLOG MIGRATION GUIDE")
    print("="*60)
    
    print("\n1. BASIC USAGE:")
    print("-"*40)
    print("""
from app.core.logging import get_logger

logger = get_logger(__name__)

# Old way (string formatting):
logger.info(f"Processing job {job_id}")

# New way (structured data):
logger.info("job_processing", job_id=job_id, status="started")
""")
    
    print("\n2. USING DECORATORS:")
    print("-"*40)
    print("""
from app.core.logging import log_execution

@log_execution(include_args=True, include_result=True)
async def process_data(data_id: str) -> dict:
    # This will automatically log entry, exit, timing, and errors
    result = await do_processing(data_id)
    return result
""")
    
    print("\n3. CELERY TASKS:")
    print("-"*40)
    print("""
from app.core.celery_logging import log_task_execution

@celery_app.task
@log_task_execution()
def background_task(param: str):
    # Task execution will be logged automatically
    return process(param)
""")
    
    print("\n4. DATABASE OPERATIONS:")
    print("-"*40)
    print("""
from app.core.database_logging import QueryLogger

with QueryLogger("fetch_active_users") as qlog:
    users = session.query(User).filter_by(active=True).all()
    qlog.log_info(count=len(users))
""")
    
    print("\n5. SECURITY EVENTS:")
    print("-"*40)
    print("""
from app.core.logging import log_security_event

log_security_event(
    "authentication_failed",
    user_id=user_id,
    ip_address=request.client.host,
    details={"reason": "invalid_credentials"}
)
""")
    
    print("\n6. CONTEXT VARIABLES:")
    print("-"*40)
    print("""
from app.core.logging import request_id_ctx, user_id_ctx

# Set context (usually done by middleware)
request_id_ctx.set("req-123")
user_id_ctx.set("user-456")

# All subsequent logs will include these IDs automatically
logger.info("action_performed", action="update")
""")


def check_environment():
    """Check and display current environment configuration."""
    print("\n" + "="*60)
    print("CURRENT ENVIRONMENT CONFIGURATION")
    print("="*60)
    
    env_vars = [
        ("ENVIRONMENT", "development"),
        ("LOG_LEVEL", "INFO"),
    ]
    
    for var, default in env_vars:
        value = os.environ.get(var, default)
        print(f"{var}: {value}")
    
    print("\nTo change configuration, set environment variables:")
    print("export ENVIRONMENT=production")
    print("export LOG_LEVEL=DEBUG")


def main():
    """Main migration function."""
    print("Starting structlog migration...")
    
    # Check if we're in the right directory
    current_dir = Path.cwd()
    if not (current_dir / "app").exists():
        print("Error: Please run this script from the apps/api directory")
        sys.exit(1)
    
    # Find all Python files
    app_dir = current_dir / "app"
    python_files = find_python_files(app_dir)
    
    print(f"Found {len(python_files)} Python files")
    
    # Update imports
    modified_files = []
    for file_path in python_files:
        if update_imports_in_file(file_path):
            modified_files.append(file_path)
            print(f"✓ Updated: {file_path.relative_to(current_dir)}")
    
    print(f"\nModified {len(modified_files)} files")
    
    # Show demonstration
    demonstrate_new_patterns()
    
    # Check environment
    check_environment()
    
    print("\n" + "="*60)
    print("NEXT STEPS")
    print("="*60)
    print("""
1. Review the modified files to ensure imports are correct
2. Update your logging calls to use structured data
3. Add @log_execution decorators to service methods
4. Configure environment variables as needed
5. Run tests to ensure everything works:
   pytest tests/test_structlog_integration.py -v
6. Replace main.py with main_with_structlog.py when ready

For more information, see LOGGING_GUIDE.md
""")


if __name__ == "__main__":
    main()