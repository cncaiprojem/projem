"""
Shared color utility module for consistent color generation across the application.

This module provides a centralized implementation for generating consistent user colors
used in collaboration features, following the DRY principle.
"""

import colorsys
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def generate_user_color(user_id: str, method: str = "hsl") -> str:
    """
    Generate a consistent color for a user.
    
    Args:
        user_id: Unique identifier for the user
        method: Color generation method ("hsl" for HSL-based or "palette" for predefined palette)
        
    Returns:
        Hex color string (e.g., "#FF6B6B")
    """
    try:
        if method == "hsl":
            return _generate_hsl_color(user_id)
        elif method == "palette":
            return _generate_palette_color(user_id)
        else:
            logger.warning(f"Unknown color generation method: {method}, falling back to palette")
            return _generate_palette_color(user_id)
    except Exception as e:
        logger.warning(f"Error generating color for user {user_id}: {e}")
        # Return a default gray color on error
        return "#808080"


def _generate_hsl_color(user_id: str) -> str:
    """
    Generate a color using HSL to RGB conversion for vibrant, consistent colors.
    
    This method generates colors with good saturation and lightness for visibility
    and ensures each user gets a unique, consistent color based on their ID.
    
    Args:
        user_id: Unique identifier for the user
        
    Returns:
        Hex color string
    """
    # Use hash to generate consistent color
    hash_val = abs(hash(user_id))
    
    # Generate hue from hash (0.0 to 1.0)
    hue = (hash_val % 360) / 360.0
    
    # Use good saturation and lightness for visibility
    saturation = 0.7  # 70% saturation for vibrant colors
    lightness = 0.5   # 50% lightness for good contrast
    
    # Convert HSL to RGB using colorsys
    # Note: colorsys.hls_to_rgb uses HLS order (Hue, Lightness, Saturation)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    
    # Convert to 0-255 range and format as hex
    r_int = int(r * 255)
    g_int = int(g * 255)
    b_int = int(b * 255)
    
    return f"#{r_int:02x}{g_int:02x}{b_int:02x}"


def _generate_palette_color(user_id: str) -> str:
    """
    Generate a color from a predefined palette of distinct colors.
    
    This method uses a curated palette of colors that work well together
    and provides good visual distinction between users.
    
    Args:
        user_id: Unique identifier for the user
        
    Returns:
        Hex color string from the palette
    """
    # Convert string user_id to int for color selection
    if user_id.isdigit():
        user_id_int = int(user_id)
    else:
        # Use hash for non-numeric IDs
        user_id_int = abs(hash(user_id))
    
    # Predefined palette of distinct, visually appealing colors
    colors = [
        "#FF6B6B",  # Soft red
        "#4ECDC4",  # Turquoise
        "#45B7D1",  # Sky blue
        "#96CEB4",  # Sage green
        "#FFEAA7",  # Pastel yellow
        "#DDA0DD",  # Plum
        "#98D8C8",  # Mint green
        "#F7DC6F",  # Golden yellow
        "#BB8FCE",  # Lavender
        "#85C1E2",  # Light blue
        "#F8B739",  # Orange
        "#6C5CE7",  # Purple
        "#FD79A8",  # Pink
        "#636E72",  # Dark gray
        "#00B894",  # Emerald
    ]
    
    return colors[user_id_int % len(colors)]


def validate_hex_color(color: str) -> bool:
    """
    Validate if a string is a valid hex color.
    
    Args:
        color: Color string to validate
        
    Returns:
        True if valid hex color, False otherwise
    """
    if not color or not isinstance(color, str):
        return False
    
    # Check if it starts with # and has correct length
    if not color.startswith("#"):
        return False
    
    # Remove # and check if remaining is valid hex
    hex_part = color[1:]
    if len(hex_part) not in (3, 6):
        return False
    
    try:
        int(hex_part, 16)
        return True
    except ValueError:
        return False


def hex_to_rgb(hex_color: str) -> Optional[tuple[int, int, int]]:
    """
    Convert hex color to RGB tuple.
    
    Args:
        hex_color: Hex color string (e.g., "#FF6B6B")
        
    Returns:
        RGB tuple (r, g, b) with values 0-255, or None if invalid
    """
    if not validate_hex_color(hex_color):
        return None
    
    hex_part = hex_color[1:]
    
    # Handle both 3 and 6 character hex codes
    if len(hex_part) == 3:
        hex_part = "".join([c * 2 for c in hex_part])
    
    try:
        r = int(hex_part[0:2], 16)
        g = int(hex_part[2:4], 16)
        b = int(hex_part[4:6], 16)
        return (r, g, b)
    except ValueError:
        return None


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """
    Convert RGB values to hex color string.
    
    Args:
        r: Red value (0-255)
        g: Green value (0-255)
        b: Blue value (0-255)
        
    Returns:
        Hex color string
    """
    # Clamp values to valid range
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    
    return f"#{r:02x}{g:02x}{b:02x}"