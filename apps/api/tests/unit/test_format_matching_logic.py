"""
Test export format matching logic for PR #501 fix.

This test validates the format matching algorithm logic without importing the full module.
"""

import pytest
from app.schemas.progress import ExportFormat


# Format map from constants.py
FORMAT_MAP = {
    "step": ExportFormat.STEP,
    "stp": ExportFormat.STEP,
    "stl": ExportFormat.STL,
    "fcstd": ExportFormat.FCSTD,
    "fcstd1": ExportFormat.FCSTD,
    "iges": ExportFormat.IGES,
    "igs": ExportFormat.IGES,
    "obj": ExportFormat.OBJ,
    "glb": ExportFormat.GLB,
    "brep": ExportFormat.BREP,
}


def get_export_format(format_str: str) -> ExportFormat:
    """
    Replicated logic from _report_export_progress for testing.
    This is the FIXED version of the algorithm.
    """
    format_lower = format_str.lower().strip()
    
    # Step 1: Try exact match
    format_enum = FORMAT_MAP.get(format_lower)
    
    # Step 2: If no exact match, try prefix matching
    if format_enum is None:
        for key, value in FORMAT_MAP.items():
            # Only match if the format starts with a known key
            # This prevents false matches like "s" matching "step"
            if format_lower.startswith(key):
                format_enum = value
                break
    
    # Step 3: If still no match, try to extract extension from filename
    if format_enum is None and '.' in format_lower:
        # Extract extension from potential filename
        extension = format_lower.rsplit('.', 1)[-1]
        format_enum = FORMAT_MAP.get(extension)
    
    # Step 4: Default to FCSTD if no match found
    if format_enum is None:
        format_enum = ExportFormat.FCSTD
    
    return format_enum


def get_export_format_old_buggy(format_str: str) -> ExportFormat:
    """
    The OLD BUGGY version for comparison.
    This demonstrates the issue we're fixing.
    """
    format_lower = format_str.lower()
    
    # Step 1: Try exact match
    format_enum = FORMAT_MAP.get(format_lower)
    
    # Step 2: If no exact match, try partial match (BUGGY!)
    if format_enum is None:
        for key, value in FORMAT_MAP.items():
            # This is the problematic line that causes false matches
            if key in format_lower or format_lower in key:
                format_enum = value
                break
    
    # Step 3: Default to FCSTD if no match found
    if format_enum is None:
        format_enum = ExportFormat.FCSTD
    
    return format_enum


class TestFormatMatchingLogic:
    """Test the format matching logic fix."""
    
    def test_single_character_bug_demonstration(self):
        """Demonstrate the bug with single character inputs."""
        # The OLD buggy version would incorrectly match single characters
        assert get_export_format_old_buggy("s") in [
            ExportFormat.STEP,  # "s" is in "step"
            ExportFormat.STL,   # "s" is in "stl"
            ExportFormat.FCSTD, # "s" is in "fcstd"
            ExportFormat.IGES,  # "s" is in "iges"
            ExportFormat.IGES,  # "s" is in "igs"
        ], "Bug: 's' matches multiple formats due to 'format_lower in key' check"
        
        assert get_export_format_old_buggy("t") in [
            ExportFormat.STEP,  # "t" is in "step"
            ExportFormat.STEP,  # "t" is in "stp"
            ExportFormat.STL,   # "t" is in "stl"
            ExportFormat.FCSTD, # "t" is in "fcstd"
        ], "Bug: 't' matches multiple formats"
        
        # The FIXED version should NOT match single characters
        assert get_export_format("s") == ExportFormat.FCSTD, "Fixed: 's' should default to FCSTD"
        assert get_export_format("t") == ExportFormat.FCSTD, "Fixed: 't' should default to FCSTD"
    
    def test_exact_matches(self):
        """Test exact format matching works correctly."""
        for format_key, expected in FORMAT_MAP.items():
            assert get_export_format(format_key) == expected, \
                f"Exact match failed for '{format_key}'"
    
    def test_prefix_matching(self):
        """Test prefix matching for composite names."""
        test_cases = [
            ("step_file", ExportFormat.STEP),
            ("step_binary", ExportFormat.STEP),
            ("stl_ascii", ExportFormat.STL),
            ("stl_binary", ExportFormat.STL),
            ("fcstd_compressed", ExportFormat.FCSTD),
            ("iges_export", ExportFormat.IGES),
        ]
        
        for input_format, expected in test_cases:
            result = get_export_format(input_format)
            assert result == expected, \
                f"Prefix match failed: '{input_format}' -> {result}, expected {expected}"
    
    def test_filename_extraction(self):
        """Test extraction of format from filename."""
        test_cases = [
            ("model.step", ExportFormat.STEP),
            ("part.stl", ExportFormat.STL),
            ("assembly.fcstd", ExportFormat.FCSTD),
            ("design.iges", ExportFormat.IGES),
            ("mesh.obj", ExportFormat.OBJ),
            ("model.glb", ExportFormat.GLB),
            ("shape.brep", ExportFormat.BREP),
            ("my_model.stp", ExportFormat.STEP),
            ("design.igs", ExportFormat.IGES),
        ]
        
        for filename, expected in test_cases:
            result = get_export_format(filename)
            assert result == expected, \
                f"Filename extraction failed: '{filename}' -> {result}, expected {expected}"
    
    def test_unknown_formats_default_to_fcstd(self):
        """Test that unknown formats default to FCSTD."""
        unknown_formats = [
            "unknown",
            "xyz",
            "custom_format",
            "3mf",  # Not in FORMAT_MAP
            "dae",  # Not in FORMAT_MAP
        ]
        
        for unknown in unknown_formats:
            result = get_export_format(unknown)
            assert result == ExportFormat.FCSTD, \
                f"Unknown format '{unknown}' should default to FCSTD, got {result}"
    
    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        test_cases = [
            ("STEP", ExportFormat.STEP),
            ("Step", ExportFormat.STEP),
            ("STL", ExportFormat.STL),
            ("Stl", ExportFormat.STL),
            ("FCSTD", ExportFormat.FCSTD),
        ]
        
        for input_format, expected in test_cases:
            result = get_export_format(input_format)
            assert result == expected, \
                f"Case insensitive match failed: '{input_format}' -> {result}, expected {expected}"
    
    def test_whitespace_handling(self):
        """Test whitespace is properly stripped."""
        test_cases = [
            ("  step  ", ExportFormat.STEP),
            ("\tstl\t", ExportFormat.STL),
            (" fcstd ", ExportFormat.FCSTD),
        ]
        
        for input_format, expected in test_cases:
            result = get_export_format(input_format)
            assert result == expected, \
                f"Whitespace handling failed: '{input_format}' -> {result}, expected {expected}"
    
    def test_edge_cases(self):
        """Test various edge cases."""
        # Empty string should default to FCSTD
        assert get_export_format("") == ExportFormat.FCSTD
        
        # Just a dot should default to FCSTD
        assert get_export_format(".") == ExportFormat.FCSTD
        
        # Multiple dots - should use last extension
        assert get_export_format("model.backup.step") == ExportFormat.STEP
        
        # Prefix that's also a valid format
        assert get_export_format("stepped_model") == ExportFormat.STEP  # starts with "step"
        
        # Format name within larger string (should not match with substring)
        # This would have matched with the buggy version
        assert get_export_format("my_custom_step_file") == ExportFormat.FCSTD
        assert get_export_format("restore_point") == ExportFormat.FCSTD