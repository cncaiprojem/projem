# Constants Migration Guide - PR #508 Fix

## Critical Change: Percentage to Ratio Conversion

As part of fixing PR #508 (Gemini Critical Severity), we've standardized all threshold constants to use ratios (0.0-1.0) instead of percentages (0-100) for consistency with Prometheus best practices.

### Environment Variable Changes

The following environment variables have been renamed and their values changed from percentages to ratios:

| Old Variable Name | Old Default | New Variable Name | New Default |
|------------------|-------------|-------------------|-------------|
| `EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT` | 2.0 (2%) | `EXPORT_VALIDATION_FAILURE_THRESHOLD` | 0.02 |
| `AI_PROVIDER_ERROR_THRESHOLD_PERCENT` | 10.0 (10%) | `AI_PROVIDER_ERROR_THRESHOLD` | 0.1 |
| `MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT` | 5.0 (5%) | `MATERIAL_LIBRARY_ERROR_THRESHOLD` | 0.05 |
| `WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT` | 5.0 (5%) | `WORKBENCH_INCOMPATIBILITY_THRESHOLD` | 0.05 |

### Migration Steps

If you have custom values set for these environment variables:

1. Remove the `_PERCENT` suffix from the variable name
2. Convert the value from percentage to ratio by dividing by 100:
   - Example: `EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT=3.5` becomes `EXPORT_VALIDATION_FAILURE_THRESHOLD=0.035`

### Rationale

This change ensures:
- **Single source of truth**: Python constants and Prometheus alerts now use the same format
- **Prometheus compatibility**: Ratios (0-1) are the standard in Prometheus for representing percentages
- **Consistency**: All threshold values follow the same pattern

### Affected Files

- `apps/api/app/core/constants.py` - Constants definitions updated
- `infra/prometheus/alerts/task-7-17-model-generation-alerts.yml` - Already using correct format

No other code changes are required as these constants were not yet imported elsewhere in the codebase.