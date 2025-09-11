#!/usr/bin/env python3
"""Test script to verify PR #558 fixes are working correctly."""

import sys
import os
import asyncio
from pathlib import Path

# Add the app path to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'apps', 'api'))

async def test_branch_manager_initialization():
    """Test that ModelBranchManager correctly accepts commit_manager parameter."""
    from app.services.model_branch_manager import ModelBranchManager
    from app.services.model_object_store import ModelObjectStore
    from app.services.model_commit_manager import ModelCommitManager
    from app.services.freecad_document_manager import FreeCADDocumentManager, DocumentManagerConfig
    
    # Create dependencies
    temp_path = Path("/tmp/test_vcs")
    object_store = ModelObjectStore(temp_path / "objects")
    
    config = DocumentManagerConfig(
        base_dir=str(temp_path / "working"),
        use_real_freecad=False
    )
    doc_manager = FreeCADDocumentManager(config)
    commit_manager = ModelCommitManager(object_store, doc_manager)
    
    # Test that BranchManager accepts commit_manager
    branch_manager = ModelBranchManager(
        temp_path / "refs",
        object_store,
        commit_manager
    )
    
    # Verify it was set correctly
    assert branch_manager.commit_manager is not None
    assert branch_manager.commit_manager == commit_manager
    print("✓ ModelBranchManager correctly accepts commit_manager")
    
    return True

async def test_imports():
    """Test that all imports are properly moved to top of files."""
    # Test that imports work without circular dependencies
    try:
        from app.services.model_branch_manager import ModelBranchManager
        from app.services.model_commit_manager import ModelCommitManager
        from app.services.model_object_store import ModelObjectStore
        from app.services.model_version_control import ModelVersionControl
        from app.api.v2.version_control import router
        from app.models.vcs_repository import VCSRepository
        from app.models.version_control import FreeCADObjectData
        from app.utils.vcs_error_handler import handle_vcs_errors
        print("✓ All imports work without issues")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

async def test_already_merged_optimization():
    """Test that the already-merged optimization is present."""
    from app.services.model_version_control import ModelVersionControl
    import inspect
    
    # Get the merge_branches method source
    mvc = ModelVersionControl()
    source = inspect.getsource(mvc.merge_branches)
    
    # Check for the already-merged optimization
    if "common_ancestor == source_head" in source and "already_merged" in source:
        print("✓ Already-merged optimization is present in merge_branches")
        return True
    else:
        print("✗ Already-merged optimization not found")
        return False

async def test_no_duplicate_imports():
    """Test that duplicate imports have been removed."""
    files_to_check = [
        "apps/api/app/utils/vcs_error_handler.py",
        "apps/api/app/api/v2/version_control.py",
        "apps/api/app/models/vcs_repository.py",
        "apps/api/app/models/version_control.py",
        "apps/api/app/services/model_object_store.py",
    ]
    
    all_good = True
    for file_path in files_to_check:
        with open(file_path, 'r') as f:
            content = f.read()
            lines = content.split('\n')
            
        # Check for duplicate imports
        import_lines = []
        for i, line in enumerate(lines):
            if line.strip().startswith('import ') or line.strip().startswith('from '):
                # Skip imports in functions (local imports that should be removed)
                # Check indentation
                if line.startswith('    ') or line.startswith('\t'):
                    print(f"✗ Found local import in {file_path} at line {i+1}: {line.strip()}")
                    all_good = False
                else:
                    import_lines.append((i, line.strip()))
        
        # Check for duplicate asyncio import at end of file
        if file_path.endswith("vcs_error_handler.py"):
            if lines[-1].strip() == "import asyncio" or lines[-2].strip() == "import asyncio":
                print(f"✗ Found duplicate asyncio import at end of {file_path}")
                all_good = False
    
    if all_good:
        print("✓ No duplicate or local imports found")
    
    return all_good

async def main():
    """Run all tests."""
    print("Testing PR #558 fixes...")
    print("-" * 50)
    
    results = []
    
    # Run tests
    results.append(await test_imports())
    results.append(await test_branch_manager_initialization())
    results.append(await test_already_merged_optimization())
    results.append(await test_no_duplicate_imports())
    
    print("-" * 50)
    if all(results):
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)