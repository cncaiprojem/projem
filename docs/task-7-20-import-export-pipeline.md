# Task 7.20 - Multi-format Import/Export Pipeline Enhancement

## Overview

Task 7.20 implements a comprehensive import/export pipeline that supports 30+ file formats with advanced features including metadata preservation, format conversion, batch processing, and quality validation.

## Architecture

### Components

1. **Universal Importer** (`apps/api/app/services/universal_importer.py`)
   - Supports 30+ import formats
   - Metadata preservation
   - Unit system conversion
   - Coordinate system handling
   - Format validation with magic bytes

2. **Enhanced Exporter** (`apps/api/app/services/enhanced_exporter.py`)
   - Pre-export validation
   - Format-specific optimization
   - Post-export verification
   - Quality control checks
   - Metadata embedding

3. **Format Converter** (`apps/api/app/services/format_converter.py`)
   - Intelligent conversion matrix
   - Topology preservation
   - Mesh optimization
   - Reverse engineering (STL to STEP)
   - BIM conversion (IFC <-> FCStd)

4. **Batch Processor** (`apps/api/app/services/batch_import_export.py`)
   - Parallel batch processing
   - Progress tracking
   - Error recovery
   - Memory-efficient streaming
   - Adaptive resource management

5. **API Endpoints** (`apps/api/app/api/v2/import_export.py`)
   - RESTful API for all operations
   - File upload/download
   - Batch operations
   - Format information

## Supported Formats

### Native FreeCAD
- **FCStd** - FreeCAD Standard (full parametric data)
- **FCMacro** - FreeCAD Macro
- **FCMat** - FreeCAD Material

### CAD Formats
- **STEP/STP** - Standard for Exchange of Product data (AP203/AP214/AP242)
- **IGES/IGS** - Initial Graphics Exchange Specification
- **BREP/BRP** - Boundary Representation
- **SAT** - ACIS SAT
- **SAB** - ACIS Binary

### Mesh Formats
- **STL** - Stereolithography (ASCII/Binary)
- **OBJ** - Wavefront Object
- **PLY** - Polygon File Format
- **OFF** - Object File Format
- **3MF** - 3D Manufacturing Format
- **AMF** - Additive Manufacturing Format

### Drawing Formats
- **DXF** - Drawing Exchange Format
- **DWG** - AutoCAD Drawing (via conversion)
- **SVG** - Scalable Vector Graphics
- **PDF** - Portable Document Format (2D/3D)

### Point Cloud Formats
- **PCD** - Point Cloud Data
- **XYZ** - Simple XYZ coordinates
- **LAS/LAZ** - LIDAR data

### Industry Specific
- **IFC** - Industry Foundation Classes (BIM)
- **DAE** - COLLADA (animation)
- **GLTF/GLB** - GL Transmission Format (Web 3D)
- **VRML/WRL** - Virtual Reality Modeling Language
- **X3D** - Extensible 3D
- **U3D** - Universal 3D

## Conversion Matrix

The system uses an intelligent conversion matrix to determine the best path between formats:

| Source | Target | Method | Quality |
|--------|--------|--------|---------|
| STEP | STL | Tessellation | High |
| STL | STEP | Reverse Engineering | Medium |
| DXF | SVG | Vector Conversion | High |
| FCStd | IFC | BIM Export | High |
| IFC | FCStd | BIM Import | High |
| BREP | STEP | Topology Preservation | Maximum |
| OBJ | GLB | Mesh Optimization | High |

## API Usage

### Import File

```python
POST /api/v2/import-export/import
Content-Type: multipart/form-data

file: <binary>
job_id: 123
preserve_materials: true
unit_system: "metric"
```

### Export Document

```python
POST /api/v2/import-export/export
Content-Type: application/json

{
  "document_id": "doc_123",
  "format": "step",
  "options": {
    "step_schema": "AP214",
    "embed_metadata": true,
    "validate_output": true
  }
}
```

### Convert Format

```python
POST /api/v2/import-export/convert
Content-Type: multipart/form-data

file: <binary>
target_format: "step"
quality: "high"
preserve_topology: true
```

### Batch Import

```python
POST /api/v2/import-export/batch-import
Content-Type: application/json

{
  "file_urls": [
    "s3://bucket/file1.step",
    "s3://bucket/file2.stl"
  ],
  "options": {
    "strategy": "adaptive",
    "max_parallel": 4,
    "continue_on_error": true
  }
}
```

### Get Supported Formats

```python
GET /api/v2/import-export/formats?category=cad

Response:
[
  {
    "format": "step",
    "name": "STEP",
    "category": "cad",
    "extensions": [".step", ".stp"],
    "can_import": true,
    "can_export": true,
    "description": "Standard for Exchange of Product data"
  }
]
```

## Import Options

```python
class ImportOptions:
    preserve_history: bool = True        # Preserve parametric history
    preserve_materials: bool = True      # Preserve material information
    preserve_constraints: bool = True    # Preserve constraints
    preserve_colors: bool = True         # Preserve colors
    preserve_textures: bool = True       # Preserve textures
    unit_system: str = "metric"          # Unit system (metric/imperial/si)
    coordinate_system: str = "z_up"      # Coordinate system
    merge_solids: bool = False           # Merge solids
    import_hidden: bool = False          # Import hidden objects
    simplify_geometry: bool = False      # Simplify geometry
    tolerance: float = 0.001             # Import tolerance
```

## Export Options

```python
class ExportOptions:
    compress: bool = False                # Compress output
    embed_metadata: bool = True           # Embed metadata
    validate_output: bool = True          # Validate output
    optimize_size: bool = False           # Optimize file size
    
    # Format-specific
    step_schema: str = "AP214"           # STEP schema
    stl_ascii: bool = False               # STL ASCII format
    stl_linear_deflection: float = 0.1   # STL linear deflection
    stl_angular_deflection: float = 0.5  # STL angular deflection
    
    # IFC options
    ifc_schema: str = "IFC4"             # IFC schema version
    ifc_include_properties: bool = True  # Include properties
    
    # GLTF options
    gltf_embed_textures: bool = True     # Embed textures
    gltf_draco_compression: bool = False # Use Draco compression
    
    mesh_quality: str = "normal"         # Mesh quality (low/normal/high/ultra)
    tolerance: float = 0.001             # Export tolerance
```

## Conversion Options

```python
class ConversionOptions:
    quality: str = "normal"               # Conversion quality
    preserve_topology: bool = True        # Preserve topology
    preserve_materials: bool = True       # Preserve materials
    preserve_hierarchy: bool = True       # Preserve hierarchy
    optimize_output: bool = False         # Optimize output
    
    # Mesh conversion
    mesh_quality: str = "normal"          # Mesh quality
    simplify_mesh: bool = False           # Simplify mesh
    target_face_count: int = None         # Target face count
    
    # Reverse engineering
    fit_surfaces: bool = True             # Fit surfaces to mesh
    detect_features: bool = True          # Detect features
    tolerance: float = 0.01               # Reconstruction tolerance
```

## Batch Processing

The batch processor supports multiple strategies:

1. **Sequential** - Process files one by one
2. **Parallel** - Process all files simultaneously
3. **Chunked** - Process in chunks
4. **Adaptive** - Automatically adjust based on system resources

### Resource Monitoring

The adaptive strategy monitors:
- Available memory
- CPU cores
- Average file size
- Current system load

## Quality Validation

### Pre-Export Validation
- Geometry validity check
- Topology verification
- Self-intersection detection
- Watertight check (for mesh formats)
- Manifold verification

### Post-Export Verification
- File existence check
- Format header validation
- File size validation
- Re-import capability test

## Metadata Preservation

The system preserves comprehensive metadata:

```json
{
  "format": "step",
  "freecad_version": "1.1.0",
  "occt_version": "7.8.1",
  "author": "User Name",
  "company": "Company Name",
  "license": "MIT",
  "creation_date": "2024-01-15T10:00:00Z",
  "objects": [
    {
      "name": "Part1",
      "type": "Part::Feature",
      "geometry": {
        "volume": 1234.56,
        "area": 789.01,
        "faces": 6,
        "edges": 12,
        "vertices": 8
      }
    }
  ],
  "materials": [
    {
      "object": "Part1",
      "properties": {
        "density": 7.85,
        "color": "#808080"
      }
    }
  ]
}
```

## Error Handling

The system provides comprehensive error handling:

1. **Format Detection Errors** - Invalid or unsupported formats
2. **Validation Errors** - Geometry or topology issues
3. **Conversion Errors** - Path not available or conversion failed
4. **Resource Errors** - Memory or disk space issues
5. **Timeout Errors** - Operation exceeded time limit

## Performance Metrics

The system tracks:
- Import/export duration
- Conversion time
- File size changes
- Success/failure rates
- Format-specific metrics

## Turkish Localization

All user-facing messages support Turkish:

```python
messages = {
    "format_detected": "Format tespit edildi",
    "validation_passed": "Doğrulama başarılı",
    "import_started": "İçe aktarma başladı",
    "export_completed": "Dışa aktarma tamamlandı",
    "conversion_completed": "Dönüştürme tamamlandı"
}
```

## Integration with FreeCAD Document Manager

The pipeline integrates seamlessly with Task 7.19's FreeCADDocumentManager:

1. Creates documents with deterministic naming
2. Manages document lifecycle
3. Handles transactions
4. Provides auto-save and recovery
5. Manages memory efficiently

## Security Considerations

1. **File Validation** - Magic byte checking, size limits
2. **Path Traversal Prevention** - Sanitized file paths
3. **Resource Limits** - Memory and CPU limits
4. **Timeout Protection** - Operation timeouts
5. **User Isolation** - User-specific operations

## Testing

Comprehensive tests should cover:

1. **Format Support** - Test each format import/export
2. **Conversion Matrix** - Test all conversion paths
3. **Batch Operations** - Test parallel processing
4. **Error Recovery** - Test failure scenarios
5. **Performance** - Test with large files
6. **Metadata** - Verify preservation

## Future Enhancements

1. **Additional Formats** - Add more specialized formats
2. **Cloud Storage** - Direct S3/Azure/GCS integration
3. **Streaming** - Large file streaming support
4. **Preview Generation** - Thumbnail/preview creation
5. **Format Analysis** - Automatic format recommendation
6. **AI-Assisted Conversion** - ML-based optimization

## Conclusion

Task 7.20 provides a comprehensive, production-ready import/export pipeline that handles 30+ formats with advanced features like metadata preservation, intelligent conversion, batch processing, and quality validation. The system is designed for scalability, reliability, and ease of use while maintaining full compatibility with FreeCAD's capabilities.