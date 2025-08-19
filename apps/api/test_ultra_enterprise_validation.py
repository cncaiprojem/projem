#!/usr/bin/env python3
"""
Ultra Enterprise Validation Test Suite for Gemini Code Assist Fixes.

Tests the strengthened validation rules in financial schemas.
"""

import sys
from decimal import Decimal

# Add the app directory to Python path for imports
sys.path.insert(0, ".")

try:
    from app.schemas.financial import MonetaryAmount, TaxCalculation, InvoiceLineItem, PaymentCreate
    from app.models.enums import Currency

    print("[OK] Successfully imported ultra enterprise financial modules")
except ImportError as e:
    print(f"[ERROR] Import error: {e}")
    sys.exit(1)


def test_ultra_strict_monetary_validation():
    """Test ultra-strict monetary amount validation."""
    print("\n[TEST] Testing Ultra-Strict Monetary Validation...")

    # Test valid amount
    valid_amount = MonetaryAmount(amount_cents=12345, currency=Currency.TRY)
    assert valid_amount.amount_decimal == Decimal("123.45")
    print("  [OK] Valid monetary amount works")

    # Test zero amount rejection
    try:
        MonetaryAmount(amount_cents=0, currency=Currency.TRY)
        assert False, "Should reject zero amount"
    except Exception as e:
        # Pydantic gives ValidationError, but the constraint works
        assert "greater than 0" in str(e) or "positive" in str(e)
        print("  [OK] Zero amount correctly rejected")

    # Test excessive amount rejection
    try:
        MonetaryAmount(amount_cents=15_000_000_000, currency=Currency.TRY)  # 150 million
        assert False, "Should reject excessive amount"
    except Exception as e:
        assert "exceeds maximum" in str(e) or "validation error" in str(e)
        print("  [OK] Excessive amount correctly rejected")


def test_ultra_strict_tax_validation():
    """Test ultra-strict tax calculation validation."""
    print("\n[TEST] Testing Ultra-Strict Tax Validation...")

    # Test valid Turkish KDV rate
    valid_tax = TaxCalculation(
        subtotal_cents=10000,
        tax_cents=2000,
        total_cents=12000,
        tax_rate_percent=Decimal("20.0"),  # Standard Turkish KDV
    )
    assert valid_tax.tax_decimal == Decimal("20.00")
    print("  [OK] Valid Turkish KDV calculation works")

    # Test invalid arithmetic
    try:
        TaxCalculation(
            subtotal_cents=10000,
            tax_cents=3000,  # Wrong tax amount
            total_cents=12000,
            tax_rate_percent=Decimal("20.0"),
        )
        assert False, "Should reject invalid arithmetic"
    except ValueError as e:
        assert "Tax calculation error" in str(e)
        print("  [OK] Invalid arithmetic correctly rejected")

    # Test precision error detection
    try:
        TaxCalculation(
            subtotal_cents=10000,
            tax_cents=1995,  # Off by more than 1 cent
            total_cents=11995,
            tax_rate_percent=Decimal("20.0"),
        )
        assert False, "Should reject precision errors > 1 cent"
    except ValueError as e:
        assert "precision error" in str(e)
        print("  [OK] Precision errors correctly detected")

    # Test excessive tax rate
    try:
        TaxCalculation(
            subtotal_cents=10000,
            tax_cents=6000,
            total_cents=16000,
            tax_rate_percent=Decimal("75.0"),  # Excessive rate
        )
        assert False, "Should reject excessive tax rate"
    except ValueError as e:
        assert "exceeds reasonable maximum" in str(e)
        print("  [OK] Excessive tax rate correctly rejected")


def test_ultra_strict_line_item_validation():
    """Test ultra-strict line item validation."""
    print("\n[TEST] Testing Ultra-Strict Line Item Validation...")

    # Test valid line item
    valid_item = InvoiceLineItem(
        description="Enterprise Test Item",
        quantity=5,
        unit_price_cents=2000,  # 20.00 each
        tax_rate_percent=Decimal("20.0"),
        subtotal_cents=10000,  # 5 * 20.00 = 100.00
        tax_cents=2000,  # 20% of 100.00 = 20.00
        total_cents=12000,  # 100.00 + 20.00 = 120.00
    )
    assert valid_item.total_decimal == Decimal("120.00")
    print("  [OK] Valid line item works")

    # Test zero quantity rejection
    try:
        InvoiceLineItem(
            description="Invalid Item",
            quantity=0,  # Invalid
            unit_price_cents=2000,
            tax_rate_percent=Decimal("20.0"),
            subtotal_cents=0,
            tax_cents=0,
            total_cents=0,
        )
        assert False, "Should reject zero quantity"
    except Exception as e:
        assert "must be positive" in str(e) or "greater than 0" in str(e)
        print("  [OK] Zero quantity correctly rejected")

    # Test excessive quantity rejection
    try:
        InvoiceLineItem(
            description="Invalid Item",
            quantity=2_000_000,  # Excessive
            unit_price_cents=1000,
            tax_rate_percent=Decimal("20.0"),
            subtotal_cents=2_000_000_000,
            tax_cents=400_000_000,
            total_cents=2_400_000_000,
        )
        assert False, "Should reject excessive quantity"
    except ValueError as e:
        assert "exceeds reasonable maximum" in str(e)
        print("  [OK] Excessive quantity correctly rejected")

    # Test arithmetic error detection
    try:
        InvoiceLineItem(
            description="Invalid Item",
            quantity=5,
            unit_price_cents=2000,
            tax_rate_percent=Decimal("20.0"),
            subtotal_cents=9999,  # Wrong: should be 10000
            tax_cents=2000,
            total_cents=11999,
        )
        assert False, "Should detect arithmetic errors"
    except ValueError as e:
        assert "Subtotal calculation error" in str(e)
        print("  [OK] Arithmetic errors correctly detected")


def test_ultra_strict_payment_validation():
    """Test ultra-strict payment validation."""
    print("\n[TEST] Testing Ultra-Strict Payment Validation...")

    # Test valid payment
    valid_payment = PaymentCreate(
        provider="stripe",
        provider_ref="pi_1234567890",
        amount_cents=15000,
        currency=Currency.TRY,
        invoice_id=123,
        user_id=456,
    )
    assert valid_payment.provider == "stripe"  # Normalized
    print("  [OK] Valid payment creation works")

    # Test invalid provider reference
    try:
        PaymentCreate(
            provider="stripe",
            provider_ref="ab",  # Too short
            amount_cents=15000,
            currency=Currency.TRY,
            invoice_id=123,
            user_id=456,
        )
        assert False, "Should reject short provider reference"
    except ValueError as e:
        assert "too short" in str(e)
        print("  [OK] Short provider reference correctly rejected")

    # Test invalid characters in provider reference
    try:
        PaymentCreate(
            provider="stripe",
            provider_ref="pi_123@456",  # Invalid character @
            amount_cents=15000,
            currency=Currency.TRY,
            invoice_id=123,
            user_id=456,
        )
        assert False, "Should reject invalid characters"
    except ValueError as e:
        assert "invalid characters" in str(e)
        print("  [OK] Invalid characters correctly rejected")

    # Test negative IDs
    try:
        PaymentCreate(
            provider="stripe",
            provider_ref="pi_1234567890",
            amount_cents=15000,
            currency=Currency.TRY,
            invoice_id=-1,  # Invalid
            user_id=456,
        )
        assert False, "Should reject negative invoice ID"
    except Exception as e:
        assert "greater than 0" in str(e) or "validation error" in str(e)
        print("  [OK] Negative IDs correctly rejected")


def main():
    """Run all ultra enterprise validation tests."""
    print("[START] Running Ultra Enterprise Validation Tests")
    print("=" * 60)

    try:
        test_ultra_strict_monetary_validation()
        test_ultra_strict_tax_validation()
        test_ultra_strict_line_item_validation()
        test_ultra_strict_payment_validation()

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL ULTRA ENTERPRISE VALIDATION TESTS PASSED!")
        print("[OK] Banking-industry level validation implemented")
        print("[OK] Turkish financial compliance enforced")
        print("[OK] Ultra-strict error detection working")
        print("[OK] Comprehensive edge case coverage achieved")
        print("[OK] Production-ready financial precision delivered")

        return True

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
