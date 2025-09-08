# PR #522: Complete Async Coverage Fixes

## Overview
This PR addresses all remaining blocking I/O operations identified by Gemini's async coverage review, ensuring complete async coverage across the codebase.

## HIGH Severity Issues Fixed

### 1. IFC Export Operations (enhanced_exporter.py)
**Issue**: `importIFC.export()` and `Arch.exportIFC()` were synchronous blocking calls  
**Fix**: Wrapped in `asyncio.to_thread()`

```python
# Before
importIFC.export(document.Objects, str(output_path))
Arch.exportIFC(document.Objects, str(output_path))

# After
await asyncio.to_thread(importIFC.export, document.Objects, str(output_path))
await asyncio.to_thread(Arch.exportIFC, document.Objects, str(output_path))
```

### 2. File Writing Operations (enhanced_exporter.py)
**Issue**: Synchronous file writing with `open()` and `write()` for XYZ format  
**Fix**: Build string and use `asyncio.to_thread()` with `write_text()`

```python
# Before
with open(output_path, "w") as f:
    f.write("\n".join(points))

# After
content = "\n".join(points)
await asyncio.to_thread(output_path.write_text, content)
```

### 3. PCD File Writing (enhanced_exporter.py)
**Issue**: Synchronous file writing for PCD point cloud format  
**Fix**: Build complete content string and use `asyncio.to_thread()`

```python
# Before
with open(output_path, "w") as f:
    f.write("# .PCD v0.7 - Point Cloud Data file format\n")
    # ... multiple write calls
    for p in points:
        f.write(f"{p[0]} {p[1]} {p[2]}\n")

# After
content = (
    "# .PCD v0.7 - Point Cloud Data file format\n"
    "VERSION 0.7\n"
    # ... build complete header
)
for p in points:
    content += f"{p[0]} {p[1]} {p[2]}\n"
await asyncio.to_thread(output_path.write_text, content)
```

### 4. FreeCAD Document Save (enhanced_exporter.py)
**Issue**: `document.saveAs()` was synchronous  
**Fix**: Wrapped in `asyncio.to_thread()`

```python
# Before
document.saveAs(str(output_path))

# After
await asyncio.to_thread(document.saveAs, str(output_path))
```

### 5. Import.export Operations (enhanced_exporter.py)
**Issue**: `Import.export()` was synchronous  
**Fix**: Wrapped in `asyncio.to_thread()`

```python
# Before
Import.export([shape], str(output_path))

# After
await asyncio.to_thread(Import.export, [shape], str(output_path))
```

### 6. Shape Make Solid (format_converter.py)
**Issue**: `shape.makeSolid()` was synchronous  
**Fix**: Wrapped in `asyncio.to_thread()`

```python
# Before
shape = shape.makeSolid()

# After
shape = await asyncio.to_thread(shape.makeSolid)
```

### 7. GLB Export (format_converter.py)
**Issue**: `scene.export()` for GLB was synchronous  
**Fix**: Wrapped in `asyncio.to_thread()`

```python
# Before
scene.export(str(output_file), file_type="glb")

# After
await asyncio.to_thread(scene.export, str(output_file), file_type="glb")
```

### 8. Trimesh Load Operations (format_converter.py)
**Issue**: `trimesh.load()` was synchronous in multiple places  
**Fix**: Wrapped all instances in `asyncio.to_thread()`

```python
# Before
mesh = trimesh.load(str(output_file))
scene = trimesh.load(str(output_file))

# After
mesh = await asyncio.to_thread(trimesh.load, str(output_file))
scene = await asyncio.to_thread(trimesh.load, str(output_file))
```

### 9. GLTF Scene Export (enhanced_exporter.py)
**Issue**: `scene.export()` in _export_gltf was synchronous  
**Fix**: Wrapped in `asyncio.to_thread()`

```python
# Before
scene.export(str(output_path))

# After
await asyncio.to_thread(scene.export, str(output_path))
```

### 10. Mesh Write Operations (enhanced_exporter.py)
**Issue**: Multiple `final_mesh.write()` calls were synchronous  
**Fix**: Wrapped all mesh.write operations in `asyncio.to_thread()`

```python
# Before
final_mesh.write(str(output_path), "AST")
final_mesh.write(str(output_path), "OBJ")
final_mesh.write(str(output_path), "PLY")
final_mesh.write(str(output_path), "OFF")
final_mesh.write(str(output_path), "AMF")
final_mesh.write(str(output_path), "VRML")

# After
await asyncio.to_thread(final_mesh.write, str(output_path), "AST")
await asyncio.to_thread(final_mesh.write, str(output_path), "OBJ")
await asyncio.to_thread(final_mesh.write, str(output_path), "PLY")
await asyncio.to_thread(final_mesh.write, str(output_path), "OFF")
await asyncio.to_thread(final_mesh.write, str(output_path), "AMF")
await asyncio.to_thread(final_mesh.write, str(output_path), "VRML")
```

### 11. File Header Reading (enhanced_exporter.py)
**Issue**: Synchronous file reading with `open()` for format verification  
**Fix**: Use `asyncio.to_thread()` with efficient reading pattern that only reads needed bytes

```python
# Before
with open(file_path, "rb") as f:
    header = f.read(1024)

# After - Efficient pattern that only reads 1024 bytes
def read_header():
    with open(file_path, 'rb') as f:
        return f.read(1024)
header = await asyncio.to_thread(read_header)
```

## MEDIUM Severity Issues Fixed

### 12. Documentation Error Handling Pattern
**Issue**: Documentation examples had potential ReferenceError  
**Fix**: Initialize `original_shape = None` before try block

```python
# Before (could cause ReferenceError)
original_shape = shape.copy()
try:
    shape.scale(MM_TO_INCH)
except Exception as e:
    shape = original_shape  # Could be undefined

# After (safe pattern)
original_shape = None
try:
    original_shape = shape.copy()
    shape.scale(MM_TO_INCH)
except Exception as e:
    if original_shape:
        shape = original_shape
```

### 13. Redundant Module Import (batch_import_export.py)
**Issue**: `import hashlib` inside function when already imported at module level  
**Fix**: Removed redundant import, added comment

```python
# Before
import hashlib  # Redundant - already imported at module level
job_id_hash = hashlib.sha256(...)

# After
# hashlib already imported at module level
job_id_hash = hashlib.sha256(...)
```

## Files Modified

1. **apps/api/app/services/enhanced_exporter.py**
   - Fixed IFC export operations
   - Fixed file writing for XYZ and PCD formats
   - Fixed FreeCAD document save
   - Fixed Import.export operations

2. **apps/api/app/services/format_converter.py**
   - Fixed shape.makeSolid operation
   - Fixed GLB export
   - Fixed all trimesh.load operations

3. **apps/api/app/services/batch_import_export.py**
   - Removed redundant hashlib import

4. **FIXES_PR518_SUMMARY.md**
   - Fixed error handling pattern in documentation

5. **FIXES_PR520_ASYNC_IO.md**
   - Fixed error handling pattern in documentation

## Testing Recommendations

1. **Integration Tests**: Run all async export tests
   ```bash
   pytest apps/api/tests/integration/test_export_async.py -v
   ```

2. **Performance Tests**: Verify no performance regression
   ```bash
   pytest apps/api/tests/performance/test_export_performance.py -v
   ```

3. **Format-Specific Tests**: Test each export format
   ```bash
   pytest apps/api/tests/test_enhanced_exporter.py -v
   pytest apps/api/tests/test_format_converter.py -v
   ```

## Verification Checklist

- [x] All IFC export operations are async
- [x] All file writing operations use asyncio.to_thread (XYZ, PCD formats)
- [x] FreeCAD document operations are async (saveAs)
- [x] Import.export operations are async
- [x] Shape manipulation operations are async (makeSolid)
- [x] Trimesh operations are async (load, export)
- [x] Mesh write operations are async (STL, OBJ, PLY, OFF, AMF, VRML)
- [x] File read operations are async (header verification)
- [x] Documentation examples follow safe patterns
- [x] No redundant imports
- [x] All blocking I/O operations wrapped properly

## Impact

This completes the async coverage for all I/O operations in the export and conversion services, ensuring:
- No blocking operations in async functions
- Consistent async patterns throughout the codebase
- Proper error handling without potential ReferenceErrors
- Clean module-level imports

## Next Steps

After merging this PR:
1. Monitor performance metrics for any improvements
2. Update developer documentation with async best practices
3. Add linting rules to catch blocking I/O in async functions