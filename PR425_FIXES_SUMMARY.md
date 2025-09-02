# PR #425 - Critical Safety Improvements for Upload Normalization

## Fixed Issues from PR #424 (Gemini Code Assist Feedback)

### 1. HIGH PRIORITY: Deduplication Hash Fallback Risk ✅
**File**: `apps/api/app/services/upload_normalization_service.py` (lines 412-443)

**Problem**: 
- Fallback hashing using volume+area+vertex/edge counts could cause hash collisions
- Two different shapes could be incorrectly considered identical, leading to data loss

**Solution**:
```python
# Before (UNSAFE):
if hasattr(shape, 'hashCode'):
    shape_hash = shape.hashCode()
else:
    # Weak fallback that could cause collisions
    shape_hash = hash((round(shape.Volume, 3), 
                     round(shape.Area, 3),
                     len(shape.Vertexes),
                     len(shape.Edges)))

# After (SAFE):
if hasattr(shape, 'hashCode') and callable(getattr(shape, 'hashCode', None)):
    # Use the reliable hashCode method when available
    shape_hash = shape.hashCode()
    # ... deduplication logic ...
else:
    # Skip deduplication when reliable hashing unavailable
    print(f"Shape.hashCode() not available - skipping deduplication for safety", file=sys.stderr)
    print(f"Including shape without deduplication to prevent data loss", file=sys.stderr)
    unique_shapes.append(shape)
```

**Impact**: Prevents potential data loss from incorrect shape deduplication

### 2. MEDIUM PRIORITY: Exception Handling Too Broad ✅
**File**: `apps/api/app/routers/upload_normalization.py` (lines 137-145)

**Problem**:
- Catching all exceptions with `except Exception:` masks potential bugs
- Makes debugging harder and hides real errors

**Solution**:
```python
# Before (TOO BROAD):
try:
    detected_file_format = upload_normalization_service.detect_format(temp_file_path)
    file_format_for_metrics = detected_file_format.value
except Exception:
    file_format_for_metrics = "unknown"

# After (SPECIFIC):
try:
    detected_file_format = upload_normalization_service.detect_format(temp_file_path)
    file_format_for_metrics = detected_file_format.value
except NormalizationException:
    # Only catch the documented exception type
    file_format_for_metrics = "unknown"
```

**Impact**: Better error visibility and debugging capabilities

## Technical Details

### FreeCAD Shape.hashCode() Research
Based on FreeCAD documentation research via context7 MCP:
- `hashCode()` is part of OpenCascade's `TopoDS_Shape` class
- Not always exposed in FreeCAD's Python API
- When available, provides reliable geometric hashing based on topology
- When unavailable, deduplication should be skipped to avoid false positives

### Why the Fallback Was Dangerous
Different shapes can have identical:
- Volume (e.g., two different brackets with same volume)
- Surface area (different internal geometries)
- Vertex/edge counts (different topologies)

Example: A hollow cylinder and a solid cylinder with thin walls could have similar metrics but are completely different parts.

## Testing Verification

Created comprehensive test script that verified:
1. ✅ Shapes with `hashCode()` are properly deduplicated
2. ✅ Duplicate shapes with same `hashCode()` are removed
3. ✅ Shapes without `hashCode()` are ALL retained (no deduplication)
4. ✅ `NormalizationException` is caught correctly
5. ✅ Other exceptions (like `ValueError`) propagate properly
6. ✅ Successful format detection works as expected

## Files Modified
- `apps/api/app/services/upload_normalization_service.py` - Safe deduplication logic
- `apps/api/app/routers/upload_normalization.py` - Specific exception handling

## PR Link
https://github.com/cncaiprojem/projem/pull/425

## Key Takeaways
1. **Data integrity over performance** - Better to skip deduplication than risk data loss
2. **Specific exception handling** - Only catch what you can handle
3. **Research before assumptions** - FreeCAD API capabilities vary
4. **Log important decisions** - Log to stderr when skipping operations for safety