"""
Test suite for PR #477 validation fixes.

Tests focus on PII validation logic without importing full middleware.
"""

import pytest
import sys
import os

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.exceptions import PIIMasker


class TestTurkishTCKimlikNoValidation:
    """Test Turkish TC Kimlik No validation with checksum algorithm."""
    
    def test_valid_tc_kimlik_no(self):
        """Test that valid TC Kimlik No is detected correctly."""
        # Valid test TC numbers (these pass the checksum)
        valid_numbers = [
            "10000000146",  # Test number that passes checksum
            "12345678950",  # Another valid test number with proper checksum
        ]
        
        for number in valid_numbers:
            assert PIIMasker._is_valid_tc_kimlik_no(number) is True
            
    def test_invalid_tc_kimlik_no_checksum(self):
        """Test that TC numbers with invalid checksum are rejected."""
        invalid_numbers = [
            "12345678901",  # Random 11 digits
            "98765432109",  # Random 11 digits
            "11111111111",  # All same digits
        ]
        
        for number in invalid_numbers:
            assert PIIMasker._is_valid_tc_kimlik_no(number) is False
            
    def test_tc_kimlik_no_starting_with_zero(self):
        """Test that TC numbers starting with 0 are invalid."""
        assert PIIMasker._is_valid_tc_kimlik_no("01234567890") is False
        
    def test_tc_kimlik_no_wrong_length(self):
        """Test that TC numbers with wrong length are invalid."""
        assert PIIMasker._is_valid_tc_kimlik_no("123456789") is False  # Too short
        assert PIIMasker._is_valid_tc_kimlik_no("123456789012") is False  # Too long
        
    def test_tc_kimlik_no_non_numeric(self):
        """Test that TC numbers with non-numeric characters are invalid."""
        assert PIIMasker._is_valid_tc_kimlik_no("1234567890a") is False
        assert PIIMasker._is_valid_tc_kimlik_no("abc12345678") is False
        
    def test_tc_kimlik_no_masking(self):
        """Test that only valid TC numbers are masked."""
        # Valid TC number should be masked
        text_with_valid = "My TC number is 10000000146"
        masked = PIIMasker.mask_text(text_with_valid)
        assert "[tc_no redacted]" in masked
        assert "10000000146" not in masked
        
        # Invalid TC number should NOT be masked
        text_with_invalid = "Random number 12345678901"
        masked = PIIMasker.mask_text(text_with_invalid)
        assert "12345678901" in masked  # Should remain unmasked
        assert "[tc_no redacted]" not in masked


class TestCreditCardLuhnValidation:
    """Test credit card validation with Luhn algorithm."""
    
    def test_valid_credit_cards(self):
        """Test that valid credit card numbers pass Luhn check."""
        valid_cards = [
            "4532015112830366",  # Valid Visa
            "5425233430109903",  # Valid Mastercard
            "374245455400126",   # Valid Amex (15 digits)
            "6011000991300009",  # Valid Discover
            "4532 0151 1283 0366",  # With spaces
            "4532-0151-1283-0366",  # With hyphens
        ]
        
        for card in valid_cards:
            assert PIIMasker._is_valid_credit_card(card) is True
            
    def test_invalid_credit_cards(self):
        """Test that invalid credit card numbers fail Luhn check."""
        invalid_cards = [
            "4532015112830367",  # Invalid checksum (last digit should be 6, not 7)
            "1234567890123456",  # Random 16 digits
            "1111111111111111",  # All ones (invalid checksum)
        ]
        
        for card in invalid_cards:
            assert PIIMasker._is_valid_credit_card(card) is False
            
    def test_credit_card_wrong_length(self):
        """Test that cards with wrong length are invalid."""
        assert PIIMasker._is_valid_credit_card("123456789012") is False  # 12 digits (too short)
        assert PIIMasker._is_valid_credit_card("12345678901234567890") is False  # 20 digits (too long)
        
    def test_credit_card_non_numeric(self):
        """Test that cards with non-numeric characters are invalid."""
        assert PIIMasker._is_valid_credit_card("4532-abcd-1283-0366") is False
        
    def test_credit_card_masking(self):
        """Test that only valid credit cards are masked."""
        # Valid card should be masked
        text_with_valid = "Payment with card 4532015112830366"
        masked = PIIMasker.mask_text(text_with_valid)
        assert "[card redacted]" in masked
        assert "4532015112830366" not in masked
        
        # Invalid card should NOT be masked
        text_with_invalid = "Number 1234567890123456 is not valid"
        masked = PIIMasker.mask_text(text_with_invalid)
        assert "1234567890123456" in masked  # Should remain unmasked
        assert "[card redacted]" not in masked


class TestIntegration:
    """Integration tests for validation changes."""
    
    def test_pii_masking_with_validation(self):
        """Test that PII masking only masks valid patterns."""
        text = """
        User info:
        - TC No: 10000000146 (valid, should be masked)
        - Random: 12345678901 (invalid TC, should NOT be masked)
        - Card: 4532015112830366 (valid, should be masked)
        - Number: 1234567890123456 (invalid card, should NOT be masked)
        - Email: user@example.com (should be masked)
        """
        
        masked = PIIMasker.mask_text(text)
        
        # Valid patterns should be masked
        assert "10000000146" not in masked
        assert "[tc_no redacted]" in masked
        assert "4532015112830366" not in masked
        assert "[card redacted]" in masked
        assert "user@example.com" not in masked
        assert "[email redacted]" in masked
        
        # Invalid patterns should remain
        assert "12345678901" in masked
        assert "1234567890123456" in masked


if __name__ == "__main__":
    pytest.main([__file__, "-v"])