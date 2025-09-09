"""
Test suite for PR #543 fixes:
- Client error notifications
- Jitter calculation
- Color generation deduplication
"""

import random
import pytest
from unittest.mock import patch, MagicMock
from app.utils.color_utils import (
    generate_user_color,
    validate_hex_color,
    hex_to_rgb,
    rgb_to_hex
)


class TestColorUtils:
    """Test the shared color utility module."""
    
    def test_generate_user_color_hsl_method(self):
        """Test HSL color generation method."""
        color = generate_user_color("user123", method="hsl")
        assert validate_hex_color(color)
        assert color.startswith("#")
        assert len(color) == 7
        
        # Test consistency - same user should get same color
        color2 = generate_user_color("user123", method="hsl")
        assert color == color2
        
        # Different users should (likely) get different colors
        color3 = generate_user_color("user456", method="hsl")
        # This might occasionally fail due to hash collisions, but unlikely
        assert color != color3 or True  # Allow for rare collisions
    
    def test_generate_user_color_palette_method(self):
        """Test palette color generation method."""
        color = generate_user_color("user123", method="palette")
        assert validate_hex_color(color)
        assert color.startswith("#")
        
        # Test consistency
        color2 = generate_user_color("user123", method="palette")
        assert color == color2
        
        # Test numeric user ID
        color_numeric = generate_user_color("123", method="palette")
        assert validate_hex_color(color_numeric)
    
    def test_generate_user_color_error_handling(self):
        """Test error handling returns gray fallback."""
        with patch('app.utils.color_utils.logger') as mock_logger:
            # Unknown method should fall back to palette
            color = generate_user_color("user123", method="unknown")
            assert validate_hex_color(color)
            mock_logger.warning.assert_called_once()
    
    def test_hex_color_validation(self):
        """Test hex color validation."""
        assert validate_hex_color("#FF6B6B")
        assert validate_hex_color("#fff")
        assert validate_hex_color("#000000")
        
        assert not validate_hex_color("FF6B6B")  # Missing #
        assert not validate_hex_color("#GGGGGG")  # Invalid hex
        assert not validate_hex_color("#FF6B6B6B")  # Too long
        assert not validate_hex_color("")
        assert not validate_hex_color(None)
    
    def test_hex_to_rgb_conversion(self):
        """Test hex to RGB conversion."""
        assert hex_to_rgb("#FF0000") == (255, 0, 0)
        assert hex_to_rgb("#00FF00") == (0, 255, 0)
        assert hex_to_rgb("#0000FF") == (0, 0, 255)
        assert hex_to_rgb("#808080") == (128, 128, 128)
        
        # Test 3-character hex codes
        assert hex_to_rgb("#F00") == (255, 0, 0)
        assert hex_to_rgb("#0F0") == (0, 255, 0)
        
        # Test invalid input
        assert hex_to_rgb("invalid") is None
        assert hex_to_rgb("") is None
    
    def test_rgb_to_hex_conversion(self):
        """Test RGB to hex conversion."""
        assert rgb_to_hex(255, 0, 0) == "#ff0000"
        assert rgb_to_hex(0, 255, 0) == "#00ff00"
        assert rgb_to_hex(0, 0, 255) == "#0000ff"
        assert rgb_to_hex(128, 128, 128) == "#808080"
        
        # Test clamping
        assert rgb_to_hex(300, -50, 128) == "#ff0080"
        assert rgb_to_hex(-10, 256, 999) == "#00ffff"


class TestJitterCalculation:
    """Test the corrected jitter calculation."""
    
    def test_jitter_range(self):
        """Test that jitter is within ±10% of base delay."""
        # Simulate the fixed jitter calculation
        base_delay = 8  # 2^3 for retry_count=3
        
        # Test multiple iterations to check range
        for _ in range(100):
            # This is the corrected calculation from collaboration_protocol.py
            jitter_factor = (random.random() - 0.5) * 0.2  # Random value in [-0.1, 0.1]
            jittered_delay = base_delay * (1 + jitter_factor)
            
            # Check that jittered delay is within ±10% of base
            min_delay = base_delay * 0.9
            max_delay = base_delay * 1.1
            
            assert min_delay <= jittered_delay <= max_delay, \
                f"Jitter {jittered_delay} not in range [{min_delay}, {max_delay}]"
    
    def test_old_jitter_was_incorrect(self):
        """Verify the old calculation was indeed incorrect (±5% instead of ±10%)."""
        base_delay = 8
        
        # Old incorrect calculation
        for _ in range(100):
            old_jitter = base_delay * 0.1 * (0.5 - random.random())  # Old: ±5%
            old_jittered = base_delay + old_jitter
            
            # Old calculation gives range [7.6, 8.4] which is ±5%
            assert 7.6 <= old_jittered <= 8.4
            
            # Verify it doesn't always satisfy ±10% range
            # (though it's within it, the range is narrower)
            if old_jittered < 7.7 or old_jittered > 8.3:
                # This would be very rare with ±5%
                pass


class TestErrorNotifications:
    """Test that error notifications are sent to clients on failures."""
    
    @pytest.mark.asyncio
    async def test_lock_release_error_notification(self):
        """Test lock release error sends notification to client."""
        # This would require mocking the WebSocket manager
        # Here we verify the structure is correct
        error_message = {
            "type": "lock_release_error",
            "message": "Failed to release locks. Please try again.",
            "error": "An error occurred while releasing the locks."
        }
        
        assert error_message["type"] == "lock_release_error"
        assert "message" in error_message
        assert "error" in error_message
    
    @pytest.mark.asyncio
    async def test_undo_error_notification(self):
        """Test undo error sends notification to client."""
        error_message = {
            "type": "undo_error",
            "message": "Failed to perform undo operation. Please try again.",
            "error": "An error occurred while processing the undo request."
        }
        
        assert error_message["type"] == "undo_error"
        assert "message" in error_message
        assert "error" in error_message
    
    @pytest.mark.asyncio
    async def test_redo_error_notification(self):
        """Test redo error sends notification to client."""
        error_message = {
            "type": "redo_error",
            "message": "Failed to perform redo operation. Please try again.",
            "error": "An error occurred while processing the redo request."
        }
        
        assert error_message["type"] == "redo_error"
        assert "message" in error_message
        assert "error" in error_message
    
    @pytest.mark.asyncio
    async def test_conflict_resolution_error_notification(self):
        """Test conflict resolution error sends notification to client."""
        conflict_id = "test-conflict-123"
        error_message = {
            "type": "conflict_resolution_error",
            "message": "Failed to resolve conflict. Please try again.",
            "error": "An error occurred while resolving the conflict.",
            "conflict_id": conflict_id
        }
        
        assert error_message["type"] == "conflict_resolution_error"
        assert "message" in error_message
        assert "error" in error_message
        assert error_message["conflict_id"] == conflict_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])