# Rounding Standards for FreeCAD Project

## Summary
This document defines the rounding standards used throughout the codebase to ensure consistency and deterministic behavior.

## Rounding Methods

### ROUND_HALF_EVEN (Banker's Rounding)
**Used for:** Engineering, CAD, metrics, and general calculations  
**Files:**
- `app/services/metrics_extractor.py` - Model metrics extraction
- `app/schemas/metrics.py` - Metrics display formatting
- `app/services/freecad_rules_engine.py` - FreeCAD normalization
- `app/services/ai_adapter.py` - AI cost calculations (non-financial)

**Rationale:**
- IEEE 754 standard compliant
- Reduces cumulative bias in large datasets
- Provides deterministic rounding for engineering precision
- Minimizes rounding errors in statistical calculations

### ROUND_HALF_UP (Traditional Rounding)
**Used for:** Financial calculations requiring regulatory compliance  
**Files:**
- `app/services/invoice_service.py` - Turkish KDV (VAT) calculations
- `app/schemas/financial.py` - Financial validation
- `app/models/validators.py` - Currency conversion (cents)
- `app/models/invoice.py` - Invoice calculations

**Rationale:**
- Required for Turkish VAT compliance
- German and Swiss tax laws require ROUND_HALF_UP for VAT
- Standard practice in financial applications
- Provides consistent behavior for monetary calculations

## Implementation Guidelines

### For Engineering/CAD/Metrics:
```python
from decimal import Decimal, ROUND_HALF_EVEN

value = Decimal('2.5')
rounded = value.quantize(Decimal('0.1'), rounding=ROUND_HALF_EVEN)
# Result: 2 (rounds to nearest even)
```

### For Financial/Tax Calculations:
```python
from decimal import Decimal, ROUND_HALF_UP

amount = Decimal('2.5')
rounded = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
# Result: 3 (always rounds up at .5)
```

## Key Principles

1. **Always use Decimal for precision-critical calculations** - Never use float
2. **Use string literals for Decimal initialization** - `Decimal('0.1')` not `Decimal(0.1)`
3. **Be explicit about rounding mode** - Always specify the rounding parameter
4. **Document exceptions** - If a different rounding is needed, document why
5. **Test edge cases** - Particularly test .5 values to ensure expected behavior

## Compliance

- Turkish KDV regulations: ROUND_HALF_UP for VAT calculations
- IEEE 754 standard: ROUND_HALF_EVEN for engineering calculations
- Deterministic behavior: Both methods provide reproducible results when used correctly

## References

- Python decimal module documentation: https://docs.python.org/3/library/decimal.html
- IEEE 754 Standard: https://en.wikipedia.org/wiki/IEEE_754
- Turkish VAT regulations: 20% standard rate with precise rounding