# Task 7.14: Golden Artefacts and Test Data

This directory contains the deterministic test corpus and golden artefacts for comprehensive integration testing of the FreeCAD-based CAD/CAM system.

## Directory Structure

```
tests/data/
├── prompt/           # Prompt-based test cases
│   ├── valid/       # Valid prompts with expected outputs
│   └── invalid/     # Invalid/ambiguous prompts for error testing
├── params/          # Parameter-driven test cases
│   ├── valid/       # Valid parameter sets
│   └── invalid/     # Invalid/missing parameters
├── uploads/         # File upload test cases
│   ├── valid/       # Valid STEP/STL files
│   └── invalid/     # Corrupted/invalid files
├── a4/             # Assembly4 test cases
│   ├── valid/       # Valid assemblies
│   └── invalid/     # Circular references, invalid constraints
└── golden/          # Golden artefacts with manifest
    ├── golden_manifest.json
    └── {test_case_id}/
        ├── {test_case_id}.step
        └── {test_case_id}.stl
```

## Golden Artefacts

Golden artefacts are deterministic reference outputs generated with:
- FreeCAD 1.1.0
- OCCT 7.8.1
- Fixed random seeds (PYTHONHASHSEED=0)
- Consistent export settings
- SHA256 verification

### Generating Golden Artefacts

```bash
# Regenerate all golden artefacts
make gen-golden

# Or directly with the script
python apps/api/tools/gen_golden.py --regenerate

# Verify existing artefacts
make verify-golden
```

### Manifest Structure

The `golden_manifest.json` contains:
- Version and generation timestamp
- Configuration (FreeCAD/OCCT versions, settings)
- For each artefact:
  - SHA256 hashes for each format
  - Geometric metrics (volume, surface area, bounding box)
  - File sizes
  - Local and S3 paths

## Test Cases

### Prompt Tests

- `simple_box.json`: Basic English prompt for box creation
- `turkish_decimal.json`: Turkish decimal comma notation (100,5 mm)
- `turkish_material.json`: Turkish material names (çelik, alüminyum)
- `ambiguous.json`: Intentionally vague prompt for error handling

### Parameter Tests

- `standard_box.json`: Complete parameter set with expected metrics
- `mixed_units.json`: Imperial to metric conversion
- `missing_required.json`: Missing required parameters

### Upload Tests

- `simple_cube.step`: Valid STEP file
- `simple_pyramid.stl`: Valid STL file
- `corrupted.step`: Intentionally corrupted for error testing

### Assembly4 Tests

- `two_part_assembly.json`: Valid two-part assembly with constraints
- `circular_reference.json`: Circular dependency for error testing

## Turkish Locale Testing

Special test cases for Turkish (tr_TR.UTF-8) locale:
- Decimal comma handling (100,5 vs 100.5)
- Material name translation (çelik → steel)
- Unicode filename support (Ç, Ş, Ğ, Ü, Ö, İ)

## CI Integration

### Running Tests Locally

```bash
# Run all integration tests
make test-golden

# Run with specific markers
pytest tests/integration/test_task_7_14_golden_artefacts.py -m slow
pytest tests/integration/test_task_7_14_golden_artefacts.py -m locale_tr
```

### CI Pipeline

Tests run automatically on:
- Push to main branch
- Pull requests
- Changes to test data

Matrix testing covers:
- Locales: C.UTF-8, tr_TR.UTF-8
- All test categories
- Performance benchmarks

### Docker Compose Test Environment

```bash
# Start test environment
docker compose -f infra/compose/docker-compose.test.yml up

# Run CI test suite
./scripts/ci/run_integration_tests.sh

# With options
./scripts/ci/run_integration_tests.sh --slow --regenerate-golden
```

## Edge Cases Covered

1. **Ambiguous Prompts**: Vague specifications that should be rejected
2. **Corrupted Files**: Invalid STEP/STL files
3. **Circular References**: Assembly dependency loops
4. **Missing Parameters**: Required fields not provided
5. **Rate Limiting**: Concurrent job limits
6. **Memory Limits**: Document manager cleanup
7. **Transient Failures**: Retry with exponential backoff

## Idempotency Testing

All operations are tested for idempotency:
- Processing same job multiple times yields identical results
- Parameter hashing is consistent
- SHA256 hashes are deterministic

## Performance Benchmarks

Performance tests measure:
- Golden artefact generation time
- File parsing speed
- Metric computation performance
- Memory usage patterns

## Contributing

When adding new test cases:
1. Follow the existing directory structure
2. Include expected outputs/errors in JSON files
3. Regenerate golden artefacts if needed
4. Update this README with new test descriptions
5. Ensure tests pass in both C.UTF-8 and tr_TR.UTF-8 locales