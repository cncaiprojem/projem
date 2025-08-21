"""
Ultra-Enterprise File Validation Service for Task 5.4

Implements comprehensive server-side validation:
- File type and extension validation
- MIME type verification with magic bytes
- Size limit enforcement  
- Double-extension attack prevention
- Filename sanitization with UUID generation
- Content scanning and malware detection hooks
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import re
import uuid
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Final, Set

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# CONSTANTS AND CONFIGURATION
# ============================================================================

# Maximum file size: 200MB as per Task 5.4 spec
MAX_FILE_SIZE: Final[int] = 200 * 1024 * 1024  # 200MB

# Minimum file size: At least 1 byte
MIN_FILE_SIZE: Final[int] = 1

# Allowed file extensions per Task 5.4
ALLOWED_EXTENSIONS: Final[Set[str]] = {
    # CAD/CAM formats
    ".step", ".stp",  # STEP files
    ".stl",           # STL format
    ".fcstd",         # FreeCAD native
    ".glb",           # GLTF binary
    
    # G-code and CNC formats
    ".nc",            # Numerical control
    ".tap",           # TAP format
    ".gcode", ".gco", # G-code variations
    
    # Media formats
    ".mp4",           # Video
    ".gif",           # Animated images
}

# Dangerous double extensions blacklist per Task 5.4
DANGEROUS_EXTENSIONS: Final[Set[str]] = {
    # Executables
    ".exe", ".dll", ".com", ".bat", ".cmd", ".msi", ".scr", ".vbs", ".js",
    ".jar", ".app", ".deb", ".rpm",
    
    # Scripts
    ".sh", ".bash", ".ps1", ".psm1", ".py", ".rb", ".pl", ".php",
    
    # Archives that could contain malware
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    
    # Other potentially dangerous
    ".iso", ".img", ".dmg", ".vhd", ".vmdk",
}

# MIME type to extension mapping per Task 5.4
MIME_TO_EXTENSIONS: Final[Dict[str, List[str]]] = {
    # CAD/CAM formats
    "model/step": [".step", ".stp"],
    "application/step": [".step", ".stp"],
    "application/x-step": [".step", ".stp"],
    "model/stl": [".stl"],
    "application/sla": [".stl"],
    "application/vnd.ms-pki.stl": [".stl"],
    "application/x-freecad": [".fcstd"],
    "application/vnd.freecad": [".fcstd"],
    "model/gltf-binary": [".glb"],
    "application/octet-stream": [".glb", ".fcstd"],  # Binary formats
    
    # G-code and CNC formats
    "text/plain": [".nc", ".tap", ".gcode", ".gco"],
    "application/x-gcode": [".gcode", ".gco"],
    "text/x-gcode": [".gcode", ".gco"],
    
    # Media formats
    "video/mp4": [".mp4"],
    "image/gif": [".gif"],
}

# Magic bytes for file type verification
# Format: extension -> [(offset, bytes_to_match), ...]
MAGIC_BYTES: Final[Dict[str, List[Tuple[int, bytes]]]] = {
    # STL ASCII format starts with "solid "
    ".stl": [
        (0, b"solid "),  # ASCII STL
        (0, bytes.fromhex("84"))  # Binary STL (starts with 84 bytes header)
    ],
    
    # STEP files are text starting with ISO-10303
    ".step": [
        (0, b"ISO-10303-21"),
        (0, b"STEP-File"),
    ],
    
    # MP4 signature
    ".mp4": [
        (4, b"ftyp"),  # MP4 file type box at offset 4
        (4, b"ftypmp4"),
        (4, b"ftypisom"),
        (4, b"ftypMSNV"),
    ],
    
    # GIF signatures
    ".gif": [
        (0, b"GIF87a"),
        (0, b"GIF89a"),
    ],
    
    # GLB (GLTF binary) signature
    ".glb": [
        (0, b"glTF"),  # GLB magic header
        (0, bytes.fromhex("676C5446")),  # "glTF" in hex
    ],
}

# Error messages in Turkish and English
ERROR_MESSAGES = {
    "INVALID_EXTENSION": {
        "en": "File type not allowed: {ext}",
        "tr": "İzin verilmeyen dosya türü: {ext}",
    },
    "MIME_MISMATCH": {
        "en": "MIME type {mime} does not match extension {ext}",
        "tr": "MIME türü {mime} uzantı {ext} ile uyuşmuyor",
    },
    "SIZE_TOO_LARGE": {
        "en": "File size {size}MB exceeds maximum {max}MB",
        "tr": "Dosya boyutu {size}MB maksimum {max}MB limitini aşıyor",
    },
    "SIZE_TOO_SMALL": {
        "en": "File cannot be empty",
        "tr": "Dosya boş olamaz",
    },
    "DOUBLE_EXTENSION": {
        "en": "Dangerous double extension detected: {filename}",
        "tr": "Tehlikeli çift uzantı tespit edildi: {filename}",
    },
    "INVALID_FILENAME": {
        "en": "Invalid or dangerous filename: {filename}",
        "tr": "Geçersiz veya tehlikeli dosya adı: {filename}",
    },
    "MAGIC_BYTES_MISMATCH": {
        "en": "File content does not match declared type",
        "tr": "Dosya içeriği beyan edilen türle uyuşmuyor",
    },
}


# ============================================================================
# VALIDATION RESULT CLASSES
# ============================================================================

class ValidationStatus(str, Enum):
    """Validation result status."""
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"


class ValidationResult:
    """
    Comprehensive validation result with details.
    """
    
    def __init__(
        self,
        status: ValidationStatus,
        sanitized_filename: Optional[str] = None,
        detected_extension: Optional[str] = None,
        detected_mime: Optional[str] = None,
        errors: Optional[List[Dict[str, str]]] = None,
        warnings: Optional[List[Dict[str, str]]] = None,
    ):
        self.status = status
        self.sanitized_filename = sanitized_filename
        self.detected_extension = detected_extension
        self.detected_mime = detected_mime
        self.errors = errors or []
        self.warnings = warnings or []
    
    @property
    def is_valid(self) -> bool:
        """Check if validation passed."""
        return self.status == ValidationStatus.VALID
    
    @property
    def error_code(self) -> int:
        """Get appropriate HTTP error code."""
        if not self.errors:
            return 200
        
        # Map error types to HTTP codes
        for error in self.errors:
            code = error.get("code", "")
            if code in ["SIZE_TOO_LARGE"]:
                return 413  # Payload Too Large
            elif code in ["DOUBLE_EXTENSION", "INVALID_FILENAME"]:
                return 400  # Bad Request - malformed input
            elif code in ["INVALID_EXTENSION", "MIME_MISMATCH", "MAGIC_BYTES_MISMATCH"]:
                return 415  # Unsupported Media Type
        
        return 400  # Bad Request
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API response."""
        return {
            "status": self.status.value,
            "sanitized_filename": self.sanitized_filename,
            "detected_extension": self.detected_extension,
            "detected_mime": self.detected_mime,
            "errors": self.errors,
            "warnings": self.warnings,
            "is_valid": self.is_valid,
            "error_code": self.error_code,
        }


# ============================================================================
# FILE VALIDATION SERVICE
# ============================================================================

class FileValidationService:
    """
    Enterprise-grade file validation service for Task 5.4.
    
    Provides comprehensive validation including:
    - Extension validation against allowlist
    - MIME type verification
    - Size limit enforcement
    - Double-extension attack prevention
    - Magic bytes verification
    - Filename sanitization with UUID generation
    """
    
    def __init__(self):
        """Initialize file validation service."""
        # Initialize mimetypes with custom mappings
        mimetypes.init()
        self._register_custom_mimes()
        
        logger.info(
            "File validation service initialized",
            allowed_extensions=len(ALLOWED_EXTENSIONS),
            max_size_mb=MAX_FILE_SIZE // (1024 * 1024),
        )
    
    def _register_custom_mimes(self) -> None:
        """Register custom MIME types for CAD/CAM formats."""
        custom_types = {
            ".step": "model/step",
            ".stp": "model/step",
            ".stl": "model/stl",
            ".fcstd": "application/x-freecad",
            ".glb": "model/gltf-binary",
            ".nc": "text/plain",
            ".tap": "text/plain",
            ".gcode": "application/x-gcode",
            ".gco": "application/x-gcode",
        }
        
        for ext, mime in custom_types.items():
            mimetypes.add_type(mime, ext)
    
    def validate_upload_init(
        self,
        filename: str,
        size: int,
        mime_type: str,
        content: Optional[bytes] = None,
    ) -> ValidationResult:
        """
        Validate file upload at initialization stage.
        
        Args:
            filename: Original filename from client
            size: Declared file size in bytes
            mime_type: Declared MIME type
            content: Optional first bytes for magic validation
            
        Returns:
            ValidationResult with status and details
        """
        errors = []
        warnings = []
        
        # Step 1: Validate size
        size_result = self._validate_size(size)
        if not size_result[0]:
            errors.append(size_result[1])
        
        # Step 2: Extract and validate extension
        extension = self._extract_extension(filename)
        if not extension:
            errors.append({
                "code": "INVALID_EXTENSION",
                "message": ERROR_MESSAGES["INVALID_EXTENSION"]["en"].format(ext="none"),
                "turkish_message": ERROR_MESSAGES["INVALID_EXTENSION"]["tr"].format(ext="yok"),
            })
        elif not self._validate_extension(extension):
            errors.append({
                "code": "INVALID_EXTENSION",
                "message": ERROR_MESSAGES["INVALID_EXTENSION"]["en"].format(ext=extension),
                "turkish_message": ERROR_MESSAGES["INVALID_EXTENSION"]["tr"].format(ext=extension),
            })
        
        # Step 3: Check for double extension attacks
        if extension and self._has_dangerous_double_extension(filename):
            errors.append({
                "code": "DOUBLE_EXTENSION",
                "message": ERROR_MESSAGES["DOUBLE_EXTENSION"]["en"].format(filename=filename),
                "turkish_message": ERROR_MESSAGES["DOUBLE_EXTENSION"]["tr"].format(filename=filename),
            })
        
        # Step 4: Validate MIME type matches extension
        if extension and not self._validate_mime_extension_match(mime_type, extension):
            errors.append({
                "code": "MIME_MISMATCH",
                "message": ERROR_MESSAGES["MIME_MISMATCH"]["en"].format(
                    mime=mime_type, ext=extension
                ),
                "turkish_message": ERROR_MESSAGES["MIME_MISMATCH"]["tr"].format(
                    mime=mime_type, ext=extension
                ),
            })
        
        # Step 5: Validate magic bytes if content provided
        if content and extension:
            if not self._validate_magic_bytes(content, extension):
                warnings.append({
                    "code": "MAGIC_BYTES_MISMATCH",
                    "message": ERROR_MESSAGES["MAGIC_BYTES_MISMATCH"]["en"],
                    "turkish_message": ERROR_MESSAGES["MAGIC_BYTES_MISMATCH"]["tr"],
                })
        
        # Step 6: Generate sanitized filename
        sanitized_filename = self._generate_safe_filename(extension or ".bin")
        
        # Determine status
        status = ValidationStatus.INVALID if errors else ValidationStatus.VALID
        if not errors and warnings:
            status = ValidationStatus.WARNING
        
        return ValidationResult(
            status=status,
            sanitized_filename=sanitized_filename,
            detected_extension=extension,
            detected_mime=mime_type,
            errors=errors,
            warnings=warnings,
        )
    
    def validate_upload_finalize(
        self,
        object_key: str,
        actual_size: int,
        expected_size: int,
        content_sample: Optional[bytes] = None,
    ) -> ValidationResult:
        """
        Validate file upload at finalization stage.
        
        Args:
            object_key: S3 object key
            actual_size: Actual uploaded file size
            expected_size: Expected file size from init
            content_sample: Optional content sample for verification
            
        Returns:
            ValidationResult with status and details
        """
        errors = []
        warnings = []
        
        # Step 1: Validate actual size
        size_result = self._validate_size(actual_size)
        if not size_result[0]:
            errors.append(size_result[1])
        
        # Step 2: Verify size matches expected
        if actual_size != expected_size:
            errors.append({
                "code": "SIZE_MISMATCH",
                "message": f"Size mismatch: expected {expected_size}, got {actual_size}",
                "turkish_message": f"Boyut uyuşmazlığı: beklenen {expected_size}, alınan {actual_size}",
            })
        
        # Step 3: Extract extension from object key
        extension = self._extract_extension(object_key)
        if extension and not self._validate_extension(extension):
            errors.append({
                "code": "INVALID_EXTENSION",
                "message": ERROR_MESSAGES["INVALID_EXTENSION"]["en"].format(ext=extension),
                "turkish_message": ERROR_MESSAGES["INVALID_EXTENSION"]["tr"].format(ext=extension),
            })
        
        # Step 4: Validate magic bytes if content provided
        if content_sample and extension:
            if not self._validate_magic_bytes(content_sample, extension):
                errors.append({
                    "code": "MAGIC_BYTES_MISMATCH",
                    "message": ERROR_MESSAGES["MAGIC_BYTES_MISMATCH"]["en"],
                    "turkish_message": ERROR_MESSAGES["MAGIC_BYTES_MISMATCH"]["tr"],
                })
        
        # Determine status
        status = ValidationStatus.INVALID if errors else ValidationStatus.VALID
        if not errors and warnings:
            status = ValidationStatus.WARNING
        
        return ValidationResult(
            status=status,
            detected_extension=extension,
            errors=errors,
            warnings=warnings,
        )
    
    # ========================================================================
    # VALIDATION HELPERS
    # ========================================================================
    
    def _validate_size(self, size: int) -> Tuple[bool, Optional[Dict[str, str]]]:
        """
        Validate file size is within limits.
        
        Returns:
            Tuple of (is_valid, error_dict_if_invalid)
        """
        if size < MIN_FILE_SIZE:
            return False, {
                "code": "SIZE_TOO_SMALL",
                "message": ERROR_MESSAGES["SIZE_TOO_SMALL"]["en"],
                "turkish_message": ERROR_MESSAGES["SIZE_TOO_SMALL"]["tr"],
            }
        
        if size > MAX_FILE_SIZE:
            size_mb = size / (1024 * 1024)
            max_mb = MAX_FILE_SIZE / (1024 * 1024)
            return False, {
                "code": "SIZE_TOO_LARGE",
                "message": ERROR_MESSAGES["SIZE_TOO_LARGE"]["en"].format(
                    size=f"{size_mb:.1f}", max=f"{max_mb:.0f}"
                ),
                "turkish_message": ERROR_MESSAGES["SIZE_TOO_LARGE"]["tr"].format(
                    size=f"{size_mb:.1f}", max=f"{max_mb:.0f}"
                ),
            }
        
        return True, None
    
    def _extract_extension(self, filename: str) -> Optional[str]:
        """
        Extract file extension from filename.
        
        Returns lowercase extension with dot (e.g., ".stl")
        """
        if not filename:
            return None
        
        # Get the base filename without path
        filename = os.path.basename(filename)
        
        # Extract extension
        parts = filename.rsplit(".", 1)
        if len(parts) == 2 and parts[1]:
            return f".{parts[1].lower()}"
        
        return None
    
    def _validate_extension(self, extension: str) -> bool:
        """
        Validate extension against allowlist.
        
        Args:
            extension: Extension with dot (e.g., ".stl")
            
        Returns:
            True if allowed, False otherwise
        """
        return extension.lower() in ALLOWED_EXTENSIONS
    
    def _has_dangerous_double_extension(self, filename: str) -> bool:
        """
        Check for dangerous double extension attacks.
        
        Per Task 5.4 spec: Reject filenames where the last extension
        is allowed but the penultimate extension exists and is dangerous.
        
        Examples:
        - "file.exe.stl" -> REJECT (dangerous .exe)
        - "file.stl.exe" -> REJECT (last extension not allowed)
        - "file.v2.stl" -> ACCEPT (benign double extension)
        - "file.zip.stl" -> REJECT (dangerous .zip)
        """
        if not filename:
            return False
        
        # Get base filename without path
        filename = os.path.basename(filename).lower()
        
        # Split by dots
        parts = filename.split(".")
        
        # Need at least 3 parts for double extension (name + ext1 + ext2)
        if len(parts) < 3:
            return False
        
        # Get last two extensions
        last_ext = f".{parts[-1]}"
        penultimate_ext = f".{parts[-2]}"
        
        # Check if last extension is allowed
        if last_ext not in ALLOWED_EXTENSIONS:
            # If last extension is not allowed, it will be rejected anyway
            return False
        
        # Check if penultimate extension is dangerous
        if penultimate_ext in DANGEROUS_EXTENSIONS:
            logger.warning(
                "Dangerous double extension detected",
                filename=filename,
                last_ext=last_ext,
                penultimate_ext=penultimate_ext,
            )
            return True
        
        return False
    
    def _validate_mime_extension_match(self, mime_type: str, extension: str) -> bool:
        """
        Validate that MIME type matches the file extension.
        
        Args:
            mime_type: Declared MIME type
            extension: File extension with dot
            
        Returns:
            True if valid match, False otherwise
        """
        # Normalize inputs
        mime_type = mime_type.lower()
        extension = extension.lower()
        
        # Check if MIME type is in our mapping
        if mime_type in MIME_TO_EXTENSIONS:
            allowed_exts = MIME_TO_EXTENSIONS[mime_type]
            if extension not in allowed_exts:
                logger.warning(
                    "MIME type does not match extension",
                    mime_type=mime_type,
                    extension=extension,
                    allowed_extensions=allowed_exts,
                )
                return False
        else:
            # Unknown MIME type - check using mimetypes module
            guessed_ext = mimetypes.guess_extension(mime_type)
            if guessed_ext and guessed_ext != extension:
                logger.warning(
                    "MIME type mismatch detected",
                    mime_type=mime_type,
                    provided_ext=extension,
                    guessed_ext=guessed_ext,
                )
                # Be lenient for unknown types but log warning
                return True
        
        return True
    
    def _validate_magic_bytes(self, content: bytes, extension: str) -> bool:
        """
        Validate file content magic bytes match the extension.
        
        Args:
            content: First bytes of file content
            extension: File extension with dot
            
        Returns:
            True if magic bytes match or no signature defined
        """
        if not content:
            return True
        
        # Normalize extension
        extension = extension.lower()
        
        # Check if we have magic bytes defined for this extension
        if extension not in MAGIC_BYTES:
            # No magic bytes defined, assume valid
            return True
        
        # Check each possible magic signature
        signatures = MAGIC_BYTES[extension]
        for offset, magic in signatures:
            # Check if we have enough bytes
            if len(content) >= offset + len(magic):
                # Extract bytes at offset
                sample = content[offset:offset + len(magic)]
                if sample == magic:
                    return True
        
        # Special case for text formats (G-code, NC, TAP)
        text_extensions = {".nc", ".tap", ".gcode", ".gco"}
        if extension in text_extensions:
            # Try to decode as text
            try:
                content[:1000].decode("utf-8")
                return True
            except UnicodeDecodeError:
                pass
            
            try:
                content[:1000].decode("ascii")
                return True
            except UnicodeDecodeError:
                pass
        
        logger.warning(
            "Magic bytes validation failed",
            extension=extension,
            content_sample=content[:20].hex() if content else None,
        )
        
        return False
    
    def _generate_safe_filename(self, extension: str) -> str:
        """
        Generate a safe filename using UUID.
        
        Per Task 5.4: Use server-generated UUID to avoid
        traversal and UTF-8 tricks.
        
        Args:
            extension: File extension to append
            
        Returns:
            Safe filename like "550e8400-e29b-41d4-a716-446655440000.stl"
        """
        # Generate UUID v4
        file_id = uuid.uuid4()
        
        # Ensure extension is clean
        extension = extension.lower()
        if not extension.startswith("."):
            extension = f".{extension}"
        
        # Remove any path components or dangerous characters
        extension = re.sub(r'[^a-z0-9.]', '', extension)
        
        return f"{file_id}{extension}"
    
    def scan_content(self, content: bytes) -> Tuple[bool, Optional[str]]:
        """
        Scan file content for malware (placeholder for integration).
        
        This is a placeholder for future malware scanning integration.
        Task 5.4 mentions malware detection but doesn't require implementation.
        
        Args:
            content: File content to scan
            
        Returns:
            Tuple of (is_clean, threat_name_if_found)
        """
        # TODO: Integrate with ClamAV or other antivirus
        # For now, just check for obvious script signatures
        
        dangerous_patterns = [
            b"<script",  # JavaScript in files
            b"<?php",    # PHP code
            b"#!/bin/",  # Shell scripts
            b"@echo off", # Batch files
            b"MZ\x90\x00", # Windows PE executables
            b"\x7fELF",   # Linux ELF executables
        ]
        
        for pattern in dangerous_patterns:
            if pattern in content[:1000]:  # Check first 1KB
                logger.warning(
                    "Suspicious content pattern detected",
                    pattern=pattern.decode("utf-8", errors="ignore"),
                )
                return False, "Suspicious content pattern"
        
        return True, None


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_file_validation_service() -> FileValidationService:
    """
    Get file validation service instance for dependency injection.
    
    Returns:
        FileValidationService: Configured validation service
    """
    return FileValidationService()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "FileValidationService",
    "ValidationResult",
    "ValidationStatus",
    "get_file_validation_service",
    "ALLOWED_EXTENSIONS",
    "MAX_FILE_SIZE",
    "DANGEROUS_EXTENSIONS",
]