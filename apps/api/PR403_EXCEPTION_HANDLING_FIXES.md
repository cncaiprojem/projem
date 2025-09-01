# PR #403 Exception Handling Fixes

## Summary
Fixed exception handling issues identified in PR #403 by implementing enterprise-grade exception handling with specific exception types instead of broad `Exception` catching.

## Changes Made

### 1. `a4_assembly.py` - Fixed Multiple Exception Handling Issues

#### Line 396-418: File Import Exception Handling
**Before:** Catching broad `Exception` and re-raising as `ValueError`
**After:** Specific exception handling for:
- `IOError, OSError, FileNotFoundError`: File system errors
- `ImportError`: FreeCAD import/format errors  
- `RuntimeError`: FreeCAD runtime errors (corrupt files, memory)
- `AttributeError`: FreeCAD API errors
- `Exception`: Only for truly unexpected errors, which are re-raised

#### Line 388-392: Document Closing Exception Handling
**Before:** Catching broad `Exception`
**After:** Specific handling for:
- `RuntimeError`: Document doesn't exist or already closed
- `AttributeError`: FreeCAD API issues

#### Line 630-638: Kinematic Simulation Exception Handling
**Before:** Catching broad `Exception`
**After:** Specific handling for:
- `ImportError, AttributeError`: Solver import/API errors
- `ValueError, TypeError`: Parameter/configuration errors
- `RuntimeError`: Solver runtime errors (convergence, constraints)

#### Line 845-867: Script Execution Exception Handling
**Before:** Catching broad `Exception` and converting to `ValueError`
**After:** Specific handling for:
- `NameError, AttributeError`: Undefined references
- `TypeError, ValueError`: Invalid operations
- `ImportError`: Unauthorized import attempts
- `RuntimeError`: Runtime failures (recursion, memory)
- `Exception`: Only for unexpected errors, which are re-raised

### 2. `standard_parts.py` - Fixed Size Parsing Exception Handling

#### Line 568-600: Size Parameter Parsing
**Before:** Catching broad `Exception` for all parsing errors
**After:** Specific handling for:
- `InvalidSizeFormatError`: Re-raised as-is (custom exception)
- `ValueError, TypeError`: Parsing-specific errors
- `IndexError, KeyError`: Structure-related errors
- `AttributeError`: Attribute access errors
- `Exception`: Only for unexpected errors, logged and re-raised

## Benefits

1. **Better Debugging**: Original stack traces are preserved using `raise ... from e`
2. **Clearer Error Messages**: Each exception type has specific, informative error messages
3. **No Masking**: Unexpected exceptions like `MemoryError` or `SystemError` are not masked
4. **Maintainability**: Clear separation of error types makes code easier to understand
5. **Enterprise-Grade**: Follows Python best practices for exception handling

## Testing Considerations

All changes maintain backward compatibility while improving error handling specificity. The code now:
- Preserves original exception chains for debugging
- Provides clear, actionable error messages
- Doesn't mask critical system errors
- Logs appropriately at each level

## Python Best Practices Applied

1. **Catch Specific Exceptions**: Each except block handles specific exception types
2. **Preserve Stack Traces**: Using `raise ... from e` maintains exception chains
3. **Log Appropriately**: Different log levels for different error types
4. **Don't Mask Unexpected Errors**: System errors propagate unchanged
5. **Informative Messages**: Error messages indicate the specific problem type