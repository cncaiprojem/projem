# PR #501 Fix: Export Format Matching Logic

## Critical Issue Fixed

**File**: `apps/api/app/tasks/freecad_with_progress.py`
**Line**: 316 (now fixed)

### The Problem

The original code had an overly broad matching condition:
```python
if key in format_lower or format_lower in key:  # PROBLEMATIC!
```

This caused incorrect format matching when:
- Input was "s" → matched "step", "stl", "fcstd", "fcstd1", "iges", "igs" (all contain "s")
- Input was "t" → matched "step", "stp", "stl", "fcstd", "fcstd1" (all contain "t")
- Input was any single character that appeared in format names

### The Solution

Replaced with a hierarchical matching algorithm:

1. **Exact match**: Direct lookup in FORMAT_MAP
2. **Prefix match**: Only if input STARTS WITH a known format (e.g., "step_file" → "step")
3. **File extension**: Extract from filename if contains "." (e.g., "model.step" → "step")
4. **Default with warning**: Fall back to FCSTD and log warning for unknown formats

```python
# Step 1: Try exact match
format_enum = FORMAT_MAP.get(format_lower)

# Step 2: If no exact match, try prefix matching
if format_enum is None:
    for key, value in FORMAT_MAP.items():
        if format_lower.startswith(key):  # FIXED: Only prefix matching
            format_enum = value
            break

# Step 3: Extract extension from filename
if format_enum is None and '.' in format_lower:
    extension = format_lower.rsplit('.', 1)[-1]
    format_enum = FORMAT_MAP.get(extension)

# Step 4: Default to FCSTD with warning
if format_enum is None:
    logger.warning(f"Unknown export format '{format_str}', defaulting to FCSTD")
    format_enum = ExportFormat.FCSTD
```

## Test Coverage

Created comprehensive unit tests in `test_format_matching_logic.py`:

- ✅ Demonstrates the bug with old logic
- ✅ Validates exact matches work
- ✅ Tests prefix matching (e.g., "step_file" → STEP)
- ✅ Tests filename extraction (e.g., "model.step" → STEP)
- ✅ Verifies single characters don't match incorrectly
- ✅ Tests unknown formats default to FCSTD
- ✅ Validates case-insensitive matching
- ✅ Tests whitespace handling

## Impact

This fix ensures:
- **Predictable behavior**: Format matching follows a clear hierarchy
- **No false matches**: Single characters or partial strings won't cause incorrect exports
- **Better debugging**: Unknown formats are logged for visibility
- **Enterprise compliance**: Follows FreeCAD best practices for format handling

## Verification

Run tests:
```bash
cd apps/api
python -m pytest tests/unit/test_format_matching_logic.py -xvs
```

All 8 tests pass, confirming the fix resolves the issue while maintaining backward compatibility for legitimate use cases.