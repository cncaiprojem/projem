"""
Comprehensive tests for Task 5.4 - File Validation Service

Tests all validation requirements:
- Extension validation
- MIME type matching
- Size limits
- Double-extension attack prevention
- Magic bytes verification
- Filename sanitization
"""

import pytest
from unittest.mock import Mock, patch

from app.services.file_validation import (
    FileValidationService,
    ValidationStatus,
    get_file_validation_service,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    DANGEROUS_EXTENSIONS,
)


class TestFileValidationService:
    """Test suite for FileValidationService."""
    
    @pytest.fixture
    def validation_service(self):
        """Create validation service instance."""
        return FileValidationService()
    
    # ========================================================================
    # EXTENSION VALIDATION TESTS
    # ========================================================================
    
    def test_allowed_extensions_accepted(self, validation_service):
        """Test that all allowed extensions are accepted."""
        test_cases = [
            ("model.step", "model/step"),
            ("part.stl", "model/stl"),
            ("design.fcstd", "application/x-freecad"),
            ("scene.glb", "model/gltf-binary"),
            ("program.nc", "text/plain"),
            ("toolpath.tap", "text/plain"),
            ("printer.gcode", "application/x-gcode"),
            ("demo.mp4", "video/mp4"),
            ("animation.gif", "image/gif"),
        ]
        
        for filename, mime_type in test_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type=mime_type,
            )
            assert result.is_valid, f"Failed for {filename}: {result.errors}"
            assert result.sanitized_filename is not None
    
    def test_disallowed_extensions_rejected(self, validation_service):
        """Test that disallowed extensions are rejected with 415 error."""
        test_cases = [
            ("malware.exe", "application/x-msdownload"),
            ("script.js", "application/javascript"),
            ("archive.zip", "application/zip"),
            ("document.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ]
        
        for filename, mime_type in test_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type=mime_type,
            )
            assert not result.is_valid
            assert result.error_code == 415  # Unsupported Media Type
            assert any("INVALID_EXTENSION" in err.get("code", "") for err in result.errors)
    
    def test_case_insensitive_extension_handling(self, validation_service):
        """Test that extensions are handled case-insensitively."""
        test_cases = [
            "Model.STL",
            "Part.Stl",
            "design.FCSTD",
            "Scene.GLB",
        ]
        
        for filename in test_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type="application/octet-stream",
            )
            assert result.is_valid, f"Failed for {filename}"
            # Check that sanitized filename has lowercase extension
            assert result.sanitized_filename.endswith(filename.split(".")[-1].lower())
    
    # ========================================================================
    # MIME TYPE VALIDATION TESTS
    # ========================================================================
    
    def test_mime_type_extension_match(self, validation_service):
        """Test that MIME types must match file extensions."""
        # Valid matches
        valid_cases = [
            ("model.stl", "model/stl"),
            ("model.stl", "application/sla"),
            ("part.step", "model/step"),
            ("video.mp4", "video/mp4"),
            ("animation.gif", "image/gif"),
        ]
        
        for filename, mime_type in valid_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type=mime_type,
            )
            assert result.is_valid, f"Valid match failed: {filename} with {mime_type}"
    
    def test_mime_type_extension_mismatch(self, validation_service):
        """Test that MIME type mismatches are rejected with 415 error."""
        # Invalid matches - per Task 5.4 spec
        invalid_cases = [
            ("model.stl", "video/mp4"),  # STL with video MIME
            ("video.mp4", "model/stl"),  # MP4 with model MIME
            ("part.step", "image/gif"),  # STEP with image MIME
        ]
        
        for filename, mime_type in invalid_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type=mime_type,
            )
            assert not result.is_valid, f"Mismatch not caught: {filename} with {mime_type}"
            assert result.error_code == 415
            assert any("MIME_MISMATCH" in err.get("code", "") for err in result.errors)
    
    # ========================================================================
    # SIZE VALIDATION TESTS
    # ========================================================================
    
    def test_size_within_limits_accepted(self, validation_service):
        """Test that files within size limits are accepted."""
        test_sizes = [
            1,  # Minimum size
            1024,  # 1KB
            1024 * 1024,  # 1MB
            100 * 1024 * 1024,  # 100MB
            200 * 1024 * 1024,  # 200MB (max)
        ]
        
        for size in test_sizes:
            result = validation_service.validate_upload_init(
                filename="model.stl",
                size=size,
                mime_type="model/stl",
            )
            assert result.is_valid, f"Valid size rejected: {size}"
    
    def test_size_too_large_rejected(self, validation_service):
        """Test that files over 200MB are rejected with 413 error."""
        oversized = 200 * 1024 * 1024 + 1  # 200MB + 1 byte
        
        result = validation_service.validate_upload_init(
            filename="model.stl",
            size=oversized,
            mime_type="model/stl",
        )
        
        assert not result.is_valid
        assert result.error_code == 413  # Payload Too Large
        assert any("SIZE_TOO_LARGE" in err.get("code", "") for err in result.errors)
    
    def test_empty_file_rejected(self, validation_service):
        """Test that empty files (0 bytes) are rejected."""
        result = validation_service.validate_upload_init(
            filename="model.stl",
            size=0,
            mime_type="model/stl",
        )
        
        assert not result.is_valid
        assert any("SIZE_TOO_SMALL" in err.get("code", "") for err in result.errors)
    
    def test_finalize_size_mismatch(self, validation_service):
        """Test that size mismatches at finalization are caught."""
        result = validation_service.validate_upload_finalize(
            object_key="artefacts/job1/model.stl",
            actual_size=2048,
            expected_size=1024,
        )
        
        assert not result.is_valid
        assert any("SIZE_MISMATCH" in err.get("code", "") for err in result.errors)
    
    # ========================================================================
    # DOUBLE-EXTENSION ATTACK TESTS
    # ========================================================================
    
    def test_double_extension_attack_prevention(self, validation_service):
        """Test that double-extension attacks are prevented per Task 5.4 spec."""
        # These should be REJECTED (dangerous penultimate extension)
        dangerous_cases = [
            "malware.exe.stl",  # .exe is dangerous
            "script.js.stl",    # .js is dangerous
            "shell.sh.step",    # .sh is dangerous
            "batch.bat.glb",    # .bat is dangerous
            "archive.zip.stl",  # .zip is dangerous
            "package.rar.stl",  # .rar is dangerous
        ]
        
        for filename in dangerous_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type="model/stl",
            )
            assert not result.is_valid, f"Dangerous double extension not caught: {filename}"
            assert result.error_code == 400
            assert any("DOUBLE_EXTENSION" in err.get("code", "") for err in result.errors)
    
    def test_benign_double_extension_allowed(self, validation_service):
        """Test that benign double extensions are allowed."""
        # These should be ACCEPTED (benign penultimate extension)
        benign_cases = [
            "model.v2.stl",     # Version number
            "part.final.step",  # Descriptive
            "design.backup.fcstd",  # Backup indicator
            "scene.old.glb",    # Old version
        ]
        
        for filename in benign_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type="model/stl",
            )
            assert result.is_valid, f"Benign double extension rejected: {filename}"
    
    def test_wrong_final_extension_rejected(self, validation_service):
        """Test that files with wrong final extension are rejected."""
        # If the LAST extension is not allowed, reject regardless
        cases = [
            "model.stl.exe",  # .exe not allowed
            "part.step.zip",  # .zip not allowed
        ]
        
        for filename in cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type="application/octet-stream",
            )
            assert not result.is_valid, f"Wrong final extension not caught: {filename}"
            assert any("INVALID_EXTENSION" in err.get("code", "") for err in result.errors)
    
    # ========================================================================
    # MAGIC BYTES VALIDATION TESTS
    # ========================================================================
    
    def test_magic_bytes_stl_ascii(self, validation_service):
        """Test STL ASCII format magic bytes validation."""
        # STL ASCII starts with "solid "
        content = b"solid TestModel\nfacet normal 0 0 0\n"
        
        result = validation_service.validate_upload_init(
            filename="model.stl",
            size=len(content),
            mime_type="model/stl",
            content=content,
        )
        
        assert result.is_valid
        assert len(result.warnings) == 0
    
    def test_magic_bytes_stl_binary(self, validation_service):
        """Test STL binary format magic bytes validation."""
        # STL binary has 84-byte header
        content = b"\x84" + b"\x00" * 83 + b"\x00\x00\x00\x00"  # Header + triangle count
        
        result = validation_service.validate_upload_init(
            filename="model.stl",
            size=len(content),
            mime_type="model/stl",
            content=content,
        )
        
        assert result.is_valid
    
    def test_magic_bytes_mp4(self, validation_service):
        """Test MP4 magic bytes validation."""
        # MP4 has "ftyp" at offset 4
        content = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41"
        
        result = validation_service.validate_upload_init(
            filename="video.mp4",
            size=len(content),
            mime_type="video/mp4",
            content=content,
        )
        
        assert result.is_valid
    
    def test_magic_bytes_gif(self, validation_service):
        """Test GIF magic bytes validation."""
        # GIF89a header
        content = b"GIF89a" + b"\x00" * 100
        
        result = validation_service.validate_upload_init(
            filename="animation.gif",
            size=len(content),
            mime_type="image/gif",
            content=content,
        )
        
        assert result.is_valid
    
    def test_magic_bytes_mismatch_warning(self, validation_service):
        """Test that magic bytes mismatch generates warning."""
        # Wrong magic bytes for STL
        content = b"This is not an STL file"
        
        result = validation_service.validate_upload_init(
            filename="model.stl",
            size=len(content),
            mime_type="model/stl",
            content=content,
        )
        
        # Should still be valid but with warning at init stage
        assert result.is_valid
        assert len(result.warnings) > 0
        assert any("MAGIC_BYTES_MISMATCH" in warn.get("code", "") for warn in result.warnings)
    
    def test_magic_bytes_mismatch_finalize_error(self, validation_service):
        """Test that magic bytes mismatch at finalize stage causes error."""
        # Wrong magic bytes for STL
        content = b"This is not an STL file"
        
        result = validation_service.validate_upload_finalize(
            object_key="artefacts/job1/model.stl",
            actual_size=len(content),
            expected_size=len(content),
            content_sample=content,
        )
        
        # Should be invalid at finalize stage
        assert not result.is_valid
        assert any("MAGIC_BYTES_MISMATCH" in err.get("code", "") for err in result.errors)
    
    # ========================================================================
    # FILENAME SANITIZATION TESTS
    # ========================================================================
    
    def test_filename_sanitization_uuid(self, validation_service):
        """Test that filenames are sanitized to UUID format."""
        result = validation_service.validate_upload_init(
            filename="../../etc/passwd.stl",  # Path traversal attempt
            size=1024,
            mime_type="model/stl",
        )
        
        assert result.is_valid
        assert result.sanitized_filename is not None
        
        # Should be UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.stl
        import re
        uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.[a-z]+$'
        assert re.match(uuid_pattern, result.sanitized_filename)
    
    def test_filename_preserves_extension(self, validation_service):
        """Test that sanitized filename preserves the correct extension."""
        test_cases = [
            ("model.stl", ".stl"),
            ("Part.STEP", ".step"),  # Lowercase
            ("design.fcstd", ".fcstd"),
            ("animation.gif", ".gif"),
        ]
        
        for filename, expected_ext in test_cases:
            result = validation_service.validate_upload_init(
                filename=filename,
                size=1024,
                mime_type="application/octet-stream",
            )
            
            assert result.is_valid
            assert result.sanitized_filename.endswith(expected_ext)
    
    def test_filename_dangerous_characters_removed(self, validation_service):
        """Test that dangerous characters are removed from extensions."""
        result = validation_service.validate_upload_init(
            filename="model.s<t>l",  # Dangerous characters in extension
            size=1024,
            mime_type="model/stl",
        )
        
        # Should sanitize the extension
        assert result.sanitized_filename is not None
        assert "<" not in result.sanitized_filename
        assert ">" not in result.sanitized_filename
    
    # ========================================================================
    # CONTENT SCANNING TESTS
    # ========================================================================
    
    def test_scan_content_detects_scripts(self, validation_service):
        """Test that content scanning detects obvious script signatures."""
        dangerous_contents = [
            b"<script>alert('XSS')</script>",
            b"<?php system('rm -rf /'); ?>",
            b"#!/bin/bash\nrm -rf /",
            b"@echo off\ndel /f /s /q c:\\*.*",
        ]
        
        for content in dangerous_contents:
            is_clean, threat = validation_service.scan_content(content)
            assert not is_clean
            assert threat is not None
    
    def test_scan_content_allows_safe_content(self, validation_service):
        """Test that content scanning allows safe content."""
        safe_contents = [
            b"solid TestModel\nfacet normal 0 0 0\n",  # STL ASCII
            b"G0 X0 Y0 Z0\nG1 X10 Y10 Z0 F100\n",  # G-code
            b"ISO-10303-21;\nHEADER;\n",  # STEP file
        ]
        
        for content in safe_contents:
            is_clean, threat = validation_service.scan_content(content)
            assert is_clean
            assert threat is None
    
    # ========================================================================
    # INTEGRATION TESTS
    # ========================================================================
    
    def test_full_validation_flow_success(self, validation_service):
        """Test complete validation flow for a valid file."""
        # Init stage
        init_result = validation_service.validate_upload_init(
            filename="model.stl",
            size=1024,
            mime_type="model/stl",
            content=b"solid TestModel\n",
        )
        
        assert init_result.is_valid
        assert init_result.sanitized_filename is not None
        
        # Finalize stage
        finalize_result = validation_service.validate_upload_finalize(
            object_key=f"artefacts/job1/{init_result.sanitized_filename}",
            actual_size=1024,
            expected_size=1024,
            content_sample=b"solid TestModel\n",
        )
        
        assert finalize_result.is_valid
    
    def test_full_validation_flow_failure(self, validation_service):
        """Test validation flow for various invalid files."""
        # Test 1: Wrong extension
        result = validation_service.validate_upload_init(
            filename="malware.exe",
            size=1024,
            mime_type="application/x-msdownload",
        )
        assert not result.is_valid
        assert result.error_code == 415
        
        # Test 2: File too large
        result = validation_service.validate_upload_init(
            filename="huge.stl",
            size=300 * 1024 * 1024,  # 300MB
            mime_type="model/stl",
        )
        assert not result.is_valid
        assert result.error_code == 413
        
        # Test 3: Double extension attack
        result = validation_service.validate_upload_init(
            filename="virus.exe.stl",
            size=1024,
            mime_type="model/stl",
        )
        assert not result.is_valid
        assert result.error_code == 400
    
    # ========================================================================
    # ERROR MESSAGE TESTS
    # ========================================================================
    
    def test_error_messages_bilingual(self, validation_service):
        """Test that error messages are provided in both English and Turkish."""
        result = validation_service.validate_upload_init(
            filename="script.exe",
            size=1024,
            mime_type="application/x-msdownload",
        )
        
        assert not result.is_valid
        for error in result.errors:
            assert "message" in error  # English
            assert "turkish_message" in error  # Turkish
            assert error["message"] != error["turkish_message"]
    
    def test_error_codes_match_spec(self, validation_service):
        """Test that error codes match Task 5.4 specification."""
        # 415 for unsupported type/MIME
        result = validation_service.validate_upload_init(
            filename="file.xyz",
            size=1024,
            mime_type="application/unknown",
        )
        assert result.error_code == 415
        
        # 413 for oversize
        result = validation_service.validate_upload_init(
            filename="large.stl",
            size=300 * 1024 * 1024,
            mime_type="model/stl",
        )
        assert result.error_code == 413
        
        # 400 for malformed input (double extension)
        result = validation_service.validate_upload_init(
            filename="bad.exe.stl",
            size=1024,
            mime_type="model/stl",
        )
        assert result.error_code == 400


class TestValidationServiceFactory:
    """Test the factory function."""
    
    def test_get_file_validation_service(self):
        """Test that factory returns proper service instance."""
        service = get_file_validation_service()
        assert isinstance(service, FileValidationService)
        
        # Should be able to validate
        result = service.validate_upload_init(
            filename="test.stl",
            size=1024,
            mime_type="model/stl",
        )
        assert result is not None