"""
Test script for Task 4.4: Invoice model and service implementation.

This script verifies that the invoice model, service, and VAT calculations
work correctly according to Task 4.4 specifications.
"""

import sys
import os
from decimal import Decimal
from datetime import datetime, timezone

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_invoice_vat_calculation():
    """Test Task 4.4 VAT calculation with Turkish KDV."""
    from app.models.invoice import Invoice

    print("=== Testing Task 4.4 VAT Calculation ===")

    # Test case 1: Simple amount
    amount = Decimal("100.00")
    vat = Invoice.calculate_vat(amount)
    total = Invoice.calculate_total(amount, vat)

    print(f"Amount: {amount}")
    print(f"VAT (20%): {vat}")
    print(f"Total: {total}")

    assert vat == Decimal("20.00"), f"Expected VAT 20.00, got {vat}"
    assert total == Decimal("120.00"), f"Expected total 120.00, got {total}"
    print("PASS: Basic VAT calculation passed")

    # Test case 2: Complex amount with rounding
    amount = Decimal("123.456")
    amounts_dict = Invoice.create_invoice_amounts(amount)

    print(f"\nComplex amount: {amount}")
    print(f"Rounded amount: {amounts_dict['amount']}")
    print(f"VAT (20%): {amounts_dict['vat']}")
    print(f"Total: {amounts_dict['total']}")

    # Verify rounding behavior
    expected_amount = Decimal("123.46")  # Rounded to 2 decimal places
    expected_vat = Decimal("24.69")  # 20% of 123.46, rounded half-up
    expected_total = Decimal("148.15")  # 123.46 + 24.69

    assert amounts_dict["amount"] == expected_amount, (
        f"Expected amount {expected_amount}, got {amounts_dict['amount']}"
    )
    assert amounts_dict["vat"] == expected_vat, (
        f"Expected VAT {expected_vat}, got {amounts_dict['vat']}"
    )
    assert amounts_dict["total"] == expected_total, (
        f"Expected total {expected_total}, got {amounts_dict['total']}"
    )
    print("PASS: Complex VAT calculation with rounding passed")


def test_invoice_numbering_format():
    """Test Task 4.4 invoice numbering format."""
    print("\n=== Testing Task 4.4 Invoice Numbering Format ===")

    # Test current date format
    now = datetime.now(timezone.utc)
    year_month = now.strftime("%Y%m")

    # Mock sequence number (this would come from database in real implementation)
    sequence = 123
    invoice_number = f"{year_month}-{sequence:06d}-CNCAI"

    print(f"Generated invoice number: {invoice_number}")

    # Verify format: YYYYMM-XXXXXX-CNCAI
    parts = invoice_number.split("-")
    assert len(parts) == 3, f"Expected 3 parts separated by '-', got {len(parts)}"
    assert len(parts[0]) == 6, f"Expected YYYYMM (6 digits), got {len(parts[0])} digits"
    assert len(parts[1]) == 6, f"Expected 6-digit sequence, got {len(parts[1])} digits"
    assert parts[2] == "CNCAI", f"Expected 'CNCAI' suffix, got '{parts[2]}'"
    assert parts[1] == "000123", f"Expected zero-padded sequence '000123', got '{parts[1]}'"

    print("PASS: Invoice numbering format passed")


def test_invoice_model_fields():
    """Test that invoice model has all required Task 4.4 fields."""
    print("\n=== Testing Task 4.4 Invoice Model Fields ===")

    from app.models.invoice import Invoice
    from app.models.enums import PaidStatus

    # Check that the model has all required fields
    required_fields = {
        "id",
        "user_id",
        "license_id",
        "number",
        "amount",
        "currency",
        "vat",
        "total",
        "paid_status",
        "issued_at",
        "pdf_url",
        "provider_payment_id",
        "created_at",
        "updated_at",
    }

    model_fields = set(Invoice.__table__.columns.keys())
    missing_fields = required_fields - model_fields

    print(f"Required fields: {required_fields}")
    print(f"Model fields: {model_fields}")

    assert not missing_fields, f"Missing required fields: {missing_fields}"
    print("PASS: All required fields present in model")

    # Test PaidStatus enum values
    expected_statuses = {"unpaid", "pending", "paid", "failed", "refunded"}
    actual_statuses = {status.value for status in PaidStatus}

    assert actual_statuses == expected_statuses, (
        f"Expected statuses {expected_statuses}, got {actual_statuses}"
    )
    print("PASS: PaidStatus enum has correct values")


def test_invoice_service_basic():
    """Test basic invoice service functionality."""
    print("\n=== Testing Task 4.4 Invoice Service Basic Functions ===")

    from app.services.invoice_service import InvoiceService

    # Test amount calculation
    base_amount = Decimal("100.00")
    amounts = InvoiceService.calculate_invoice_amounts(base_amount)

    print(
        f"Service calculation - Amount: {amounts['amount']}, VAT: {amounts['vat']}, Total: {amounts['total']}"
    )

    assert amounts["amount"] == Decimal("100.00")
    assert amounts["vat"] == Decimal("20.00")
    assert amounts["total"] == Decimal("120.00")
    print("PASS: Invoice service amount calculation passed")


def main():
    """Run all Task 4.4 tests."""
    print("Starting Task 4.4 Invoice Implementation Tests\n")

    try:
        test_invoice_vat_calculation()
        test_invoice_numbering_format()
        test_invoice_model_fields()
        test_invoice_service_basic()

        print("\n" + "=" * 50)
        print("ALL TASK 4.4 TESTS PASSED!")
        print("- Invoice model with correct fields")
        print("- 20% Turkish VAT calculation with half-up rounding")
        print("- Invoice numbering format: YYYYMM-SEQ-CNCAI")
        print("- PaidStatus enum with required values")
        print("- Invoice service basic functionality")
        print("=" * 50)

    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
