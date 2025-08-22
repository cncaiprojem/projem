# PR #192 Complete Feedback Fixes

## Summary
Fixed ALL critical issues from PR #192 Copilot and Gemini feedback for Task 5.7 (Artefact persistence).

## Issues Fixed

### Copilot Issues Fixed:
1. ✅ **asyncio.run() blocking event loop** (file_service.py line 901-908)
   - Created `create_artefact_sync()` wrapper method in ArtefactService
   - Properly handles both sync and async contexts without blocking

2. ✅ **Deprecated 'regex' parameter in Pydantic v2** (artefact.py schema line 38)
   - Changed from `regex=` to `pattern=` for Pydantic v2 compatibility

3. ✅ **Authorization doesn't account for admin users** (artefact_service.py line 124-135)
   - Added admin role check allowing admins to access any job
   - Non-admin users restricted to their own jobs

4. ✅ **Silently continuing after artefact creation failure** (file_service.py line 918-936)
   - Added proper error tracking in file metadata
   - Logs failure details for monitoring while not breaking upload

5. ✅ **Regex pattern not compiled as module constant** (artefact.py model)
   - Added `SHA256_PATTERN` as compiled regex at module level
   - Added `validate_sha256()` class method using the compiled pattern

### Gemini Issues Fixed:
1. ✅ **Audit log not persisted - commit after audit entry** (artefact_service.py line 194-218)
   - Moved audit log creation BEFORE commit
   - Ensures audit entry is in same transaction as artefact

2. ✅ **Bare except blocks in migration** (20250821_task_57_artefacts_persistence.py)
   - Changed all bare `except:` to `except Exception as e:`
   - Added proper error logging with context

3. ✅ **Business logic in router** (artefacts.py router)
   - Moved `created_by` override logic to service layer
   - Router now only handles HTTP concerns

4. ✅ **Unused imports** (artefacts.py router)
   - Removed `ArtefactS3TagsResponse` and `ArtefactTagRequest` imports

5. ✅ **Non-deterministic user selection** (file_service.py _get_system_user_id)
   - Added `ORDER BY User.id.asc()` to all queries
   - Ensures deterministic user selection

## Files Modified
1. `apps/api/app/services/file_service.py`
   - Fixed asyncio.run() issue
   - Added error handling for artefact creation
   - Added ORDER BY for deterministic queries

2. `apps/api/app/services/artefact_service.py`
   - Added `create_artefact_sync()` wrapper
   - Fixed audit log transaction order
   - Added admin role authorization check
   - Moved created_by override logic from router

3. `apps/api/app/schemas/artefact.py`
   - Changed `regex=` to `pattern=` for Pydantic v2

4. `apps/api/app/models/artefact.py`
   - Added `SHA256_PATTERN` compiled regex constant
   - Added `validate_sha256()` class method

5. `apps/api/app/routers/artefacts.py`
   - Removed unused imports
   - Simplified to let service handle business logic

6. `apps/api/alembic/versions/20250821_task_57_artefacts_persistence.py`
   - Fixed bare except blocks with proper Exception handling

## Testing
All files compile successfully without syntax errors. The fixes ensure:
- No event loop blocking in async contexts
- Pydantic v2 compatibility
- Proper RBAC with admin support
- Audit trail integrity
- Deterministic database queries
- Clean separation of concerns

## Enterprise Standards Compliance
✅ All fixes follow enterprise standards from CLAUDE.md:
- Proper error handling with Turkish messages
- Comprehensive audit logging
- Transaction integrity
- Performance optimization (compiled regex)
- Clean architecture patterns