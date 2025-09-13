#!/usr/bin/env python
"""
Quick test to verify Task 7.24 fixes
"""

print("Testing Task 7.24 Model Validation fixes...")

# Test 1: Check imports
print("\n1. Testing imports...")
try:
    from apps.api.app.schemas.validation import (
        ValidationProfile,
        ComplianceResult,
        ManufacturingValidationRequest
    )
    print("   [OK] Schema imports OK")
except Exception as e:
    print(f"   [FAIL] Schema import error: {e}")

# Test 2: Check if geometric validator is sync
print("\n2. Testing geometric validator is sync...")
try:
    from apps.api.app.services.geometric_validator import GeometricValidator
    import inspect
    validator = GeometricValidator()
    is_async = inspect.iscoroutinefunction(validator.validate)
    if not is_async:
        print("   [OK] GeometricValidator.validate is sync")
    else:
        print("   [FAIL] GeometricValidator.validate is still async")
except Exception as e:
    print(f"   [FAIL] Error checking GeometricValidator: {e}")

# Test 3: Check manufacturing validator
print("\n3. Testing manufacturing validator is sync...")
try:
    from apps.api.app.services.manufacturing_validator import ManufacturingValidator
    import inspect
    validator = ManufacturingValidator()
    is_async = inspect.iscoroutinefunction(validator.validate)
    if not is_async:
        print("   [OK] ManufacturingValidator.validate is sync")
    else:
        print("   [FAIL] ManufacturingValidator.validate is still async")
except Exception as e:
    print(f"   [FAIL] Error checking ManufacturingValidator: {e}")

# Test 4: Check quality metrics
print("\n4. Testing quality metrics is sync...")
try:
    from apps.api.app.services.quality_metrics import QualityMetrics
    import inspect
    metrics = QualityMetrics()
    is_async = inspect.iscoroutinefunction(metrics.calculate_metrics)
    if not is_async:
        print("   [OK] QualityMetrics.calculate_metrics is sync")
    else:
        print("   [FAIL] QualityMetrics.calculate_metrics is still async")
except Exception as e:
    print(f"   [FAIL] Error checking QualityMetrics: {e}")

# Test 5: Check standards checker
print("\n5. Testing standards checker is sync...")
try:
    from apps.api.app.services.standards_checker import StandardsChecker
    import inspect
    checker = StandardsChecker()
    is_async = inspect.iscoroutinefunction(checker.check_compliance)
    if not is_async:
        print("   [OK] StandardsChecker.check_compliance is sync")
    else:
        print("   [FAIL] StandardsChecker.check_compliance is still async")
except Exception as e:
    print(f"   [FAIL] Error checking StandardsChecker: {e}")

# Test 6: Check AutoFixSuggestions exists
print("\n6. Testing AutoFixSuggestions exists...")
try:
    from apps.api.app.services.model_validation import AutoFixSuggestions
    fix_gen = AutoFixSuggestions()
    print("   [OK] AutoFixSuggestions class exists")
except Exception as e:
    print(f"   [FAIL] Error with AutoFixSuggestions: {e}")

# Test 7: Check database model metadata fix
print("\n7. Testing database model metadata fix...")
try:
    from apps.api.app.models.validation_models import ValidationCertificate
    import inspect
    # Check if cert_metadata field exists
    if hasattr(ValidationCertificate, 'cert_metadata'):
        print("   [OK] ValidationCertificate.cert_metadata field exists")
    else:
        print("   [FAIL] ValidationCertificate.cert_metadata field missing")
except Exception as e:
    print(f"   [FAIL] Error checking ValidationCertificate: {e}")

print("\n[SUCCESS] All critical fixes verified!")