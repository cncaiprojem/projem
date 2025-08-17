"""
Ultra enterprise input sanitization service for FreeCAD CNC/CAM platform.
Implements comprehensive XSS/injection prevention with Turkish localization.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from ..core.logging import get_logger
from ..models.security_event import SecurityEvent
from ..settings import app_settings as appset

logger = get_logger(__name__)


class InputSanitizationService:
    """Ultra enterprise input sanitization and validation service.
    
    Provides comprehensive protection against:
    - XSS (Cross-Site Scripting)
    - SQL injection
    - HTML injection
    - Script injection
    - Path traversal
    - Command injection
    """
    
    # XSS patterns to detect and block
    XSS_PATTERNS = [
        # Script tags
        r'<\s*script[^>]*?>.*?<\s*/\s*script\s*>',
        r'<\s*script[^>]*?>',
        
        # Event handlers
        r'on\w+\s*=\s*["\']?[^"\']*["\']?',
        
        # JavaScript protocols
        r'javascript\s*:',
        r'vbscript\s*:',
        r'data\s*:.*?base64',
        
        # HTML entities that decode to scripts
        r'&#x?[0-9a-f]+;',
        
        # Iframe and object tags
        r'<\s*iframe[^>]*?>',
        r'<\s*object[^>]*?>',
        r'<\s*embed[^>]*?>',
        r'<\s*link[^>]*?>',
        
        # Meta refresh
        r'<\s*meta[^>]*?http-equiv[^>]*?>',
        
        # Form tags (potentially malicious)
        r'<\s*form[^>]*?>',
        
        # Common XSS functions
        r'alert\s*\(',
        r'confirm\s*\(',
        r'prompt\s*\(',
        r'eval\s*\(',
        r'setTimeout\s*\(',
        r'setInterval\s*\(',
        r'Function\s*\(',
        
        # Expression functions
        r'expression\s*\(',
        r'url\s*\(',
        
        # CSS injection
        r'@import',
        r'binding\s*:',
        r'behavior\s*:',
    ]
    
    # SQL injection patterns - more specific to avoid false positives
    SQL_INJECTION_PATTERNS = [
        # Union-based injections
        r'\bunion\s+select\b',
        r'\bunion\s+all\s+select\b',
        
        # SQL comment patterns in injection context
        r"'\s*--",
        r'"\s*--',
        r'/\*.*?\*/',
        
        # Stacked queries with dangerous operations
        r';\s*(drop|delete|update|insert|create|alter)\s+',
        
        # SQL functions in injection context
        r"'\s*(or|and)\s+\w+\s*\(",
        r'"\s*(or|and)\s+\w+\s*\(',
        
        # Classic injection patterns
        r"'\s*(or|and)\s+'[^']*'\s*=\s*'[^']*'",
        r'"\s*(or|and)\s+"[^"]*"\s*=\s*"[^"]*"',
        r"'\s*or\s+1\s*=\s*1\s*(--|\s*$)",
        r'"\s*or\s+1\s*=\s*1\s*(--|\s*$)',
        r"admin'\s*--",
        r'admin"\s*--',
        
        # Database-specific stored procedures
        r'xp_cmdshell',
        r'sp_executesql',
        r'@@version',
        
        # Blind injection patterns
        r"'\s*and\s+\d+\s*=\s*\d+\s*--",
        r'"\s*and\s+\d+\s*=\s*\d+\s*--',
    ]
    
    # Path traversal patterns
    PATH_TRAVERSAL_PATTERNS = [
        r'\.\./+',
        r'\.\.\\+',
        r'~/',
        r'%2e%2e%2f',
        r'%2e%2e\\',
        r'\.\.%2f',
        r'\.\.%5c',
    ]
    
    # Command injection patterns - more specific to avoid false positives
    COMMAND_INJECTION_PATTERNS = [
        # Shell command chains with dangerous commands
        r'[;&|]\s*(rm|del|format|cat|type|ls|dir|ps|kill|chmod|chown|sudo|su)\s+',
        r'`[^`]*\s*(rm|del|cat|ls|ps|wget|curl|nc|telnet|ssh)\s+[^`]*`',
        
        # Command substitution patterns
        r'\$\(\s*(rm|del|cat|ls|ps|wget|curl|nc|telnet|ssh)\s+',
        r'`\s*(rm|del|cat|ls|ps|wget|curl|nc|telnet|ssh)\s+',
        
        # Pipe to dangerous commands
        r'\|\s*(sh|bash|cmd|powershell|python|perl|ruby)\s*$',
        r'\|\s*(rm|del|format)\s+',
        
        # Logic operators with commands
        r'&&\s*(rm|del|format|cat|wget|curl|nc)\s+',
        r'\|\|\s*(rm|del|format|cat|wget|curl|nc)\s+',
        
        # File redirection patterns
        r'>\s*/etc/',
        r'>\s*c:\\windows',
        r'>>\s*/var/log',
    ]
    
    def __init__(self):
        """Initialize the input sanitization service."""
        self.compiled_xss_patterns = [re.compile(pattern, re.IGNORECASE | re.DOTALL) 
                                     for pattern in self.XSS_PATTERNS]
        self.compiled_sql_patterns = [re.compile(pattern, re.IGNORECASE) 
                                     for pattern in self.SQL_INJECTION_PATTERNS]
        self.compiled_path_patterns = [re.compile(pattern, re.IGNORECASE) 
                                      for pattern in self.PATH_TRAVERSAL_PATTERNS]
        self.compiled_cmd_patterns = [re.compile(pattern, re.IGNORECASE) 
                                     for pattern in self.COMMAND_INJECTION_PATTERNS]
    
    def sanitize_html(self, input_text: str) -> str:
        """Sanitize HTML content by escaping dangerous characters.
        
        Args:
            input_text: Raw input text that may contain HTML
            
        Returns:
            Sanitized text with HTML entities escaped
        """
        if not isinstance(input_text, str):
            return str(input_text)
        
        # HTML escape all dangerous characters
        sanitized = html.escape(input_text, quote=True)
        
        return sanitized
    
    def sanitize_text_input(self, input_text: str, strict: bool = True) -> str:
        """Sanitize general text input for safe storage and display.
        
        Args:
            input_text: Raw text input
            strict: If True, applies strict sanitization rules
            
        Returns:
            Sanitized text safe for storage and display
        """
        if not isinstance(input_text, str):
            return str(input_text)
        
        # Remove null bytes
        sanitized = input_text.replace('\x00', '')
        
        # Normalize line endings
        sanitized = sanitized.replace('\r\n', '\n').replace('\r', '\n')
        
        if strict:
            # Remove control characters except tab, newline, carriage return
            sanitized = ''.join(char for char in sanitized 
                              if ord(char) >= 32 or char in '\t\n\r')
            
            # Limit length to prevent DOS
            sanitized = sanitized[:10000]  # 10KB limit
        
        # HTML escape for XSS prevention
        sanitized = self.sanitize_html(sanitized)
        
        return sanitized
    
    def validate_against_xss(self, input_text: str) -> Dict[str, Any]:
        """Validate input against XSS patterns.
        
        Args:
            input_text: Text to validate
            
        Returns:
            Dictionary with validation results
        """
        if not isinstance(input_text, str):
            return {"is_safe": True, "threats": []}
        
        threats = []
        
        for pattern in self.compiled_xss_patterns:
            matches = pattern.findall(input_text.lower())
            if matches:
                threats.append({
                    "type": "XSS",
                    "pattern": pattern.pattern,
                    "matches": matches[:5]  # Limit to first 5 matches
                })
        
        return {
            "is_safe": len(threats) == 0,
            "threats": threats,
            "input_length": len(input_text)
        }
    
    def validate_against_sql_injection(self, input_text: str) -> Dict[str, Any]:
        """Validate input against SQL injection patterns.
        
        Args:
            input_text: Text to validate
            
        Returns:
            Dictionary with validation results
        """
        if not isinstance(input_text, str):
            return {"is_safe": True, "threats": []}
        
        threats = []
        
        # Only check inputs that could realistically contain SQL injection
        # Minimum length and must contain SQL-like patterns
        if len(input_text) > 5 and any(keyword in input_text.lower() 
                                      for keyword in ['select', 'union', 'insert', 'update', 'delete', 'drop', "'", '"']):
            for pattern in self.compiled_sql_patterns:
                matches = pattern.findall(input_text.lower())
                if matches:
                    threats.append({
                        "type": "SQL_INJECTION",
                        "pattern": pattern.pattern,
                        "matches": matches[:5]
                    })
        
        return {
            "is_safe": len(threats) == 0,
            "threats": threats,
            "input_length": len(input_text)
        }
    
    def validate_against_path_traversal(self, input_text: str) -> Dict[str, Any]:
        """Validate input against path traversal patterns.
        
        Args:
            input_text: Text to validate
            
        Returns:
            Dictionary with validation results
        """
        if not isinstance(input_text, str):
            return {"is_safe": True, "threats": []}
        
        threats = []
        
        for pattern in self.compiled_path_patterns:
            matches = pattern.findall(input_text)
            if matches:
                threats.append({
                    "type": "PATH_TRAVERSAL",
                    "pattern": pattern.pattern,
                    "matches": matches[:5]
                })
        
        return {
            "is_safe": len(threats) == 0,
            "threats": threats,
            "input_length": len(input_text)
        }
    
    def validate_against_command_injection(self, input_text: str) -> Dict[str, Any]:
        """Validate input against command injection patterns.
        
        Args:
            input_text: Text to validate
            
        Returns:
            Dictionary with validation results
        """
        if not isinstance(input_text, str):
            return {"is_safe": True, "threats": []}
        
        threats = []
        
        # Only check inputs that could realistically contain command injection
        # Must contain shell operators or command-like patterns
        if len(input_text) > 3 and any(operator in input_text 
                                      for operator in [';', '|', '&', '`', '$', '>', '<', 'rm ', 'del ', 'cat ', 'ls ']):
            for pattern in self.compiled_cmd_patterns:
                matches = pattern.findall(input_text)
                if matches:
                    threats.append({
                        "type": "COMMAND_INJECTION",
                        "pattern": pattern.pattern,
                        "matches": matches[:5]
                    })
        
        return {
            "is_safe": len(threats) == 0,
            "threats": threats,
            "input_length": len(input_text)
        }
    
    def comprehensive_validate(self, input_text: str) -> Dict[str, Any]:
        """Perform comprehensive security validation on input.
        
        Args:
            input_text: Text to validate
            
        Returns:
            Comprehensive validation results
        """
        if not isinstance(input_text, str):
            return {
                "is_safe": True,
                "sanitized": str(input_text),
                "threats": [],
                "validation_summary": "Non-string input converted to string"
            }
        
        # Perform all validations
        xss_result = self.validate_against_xss(input_text)
        sql_result = self.validate_against_sql_injection(input_text)
        path_result = self.validate_against_path_traversal(input_text)
        cmd_result = self.validate_against_command_injection(input_text)
        
        # Collect all threats
        all_threats = []
        all_threats.extend(xss_result.get("threats", []))
        all_threats.extend(sql_result.get("threats", []))
        all_threats.extend(path_result.get("threats", []))
        all_threats.extend(cmd_result.get("threats", []))
        
        # Determine overall safety
        is_safe = (
            xss_result["is_safe"] and 
            sql_result["is_safe"] and 
            path_result["is_safe"] and 
            cmd_result["is_safe"]
        )
        
        # Sanitize input regardless of threats (for safe storage)
        sanitized = self.sanitize_text_input(input_text, strict=True)
        
        return {
            "is_safe": is_safe,
            "sanitized": sanitized,
            "threats": all_threats,
            "validation_details": {
                "xss": xss_result["is_safe"],
                "sql_injection": sql_result["is_safe"],
                "path_traversal": path_result["is_safe"],
                "command_injection": cmd_result["is_safe"]
            },
            "input_length": len(input_text),
            "sanitized_length": len(sanitized)
        }
    
    def get_security_error_message(self, threats: List[Dict]) -> str:
        """Generate Turkish security error message based on threats.
        
        Args:
            threats: List of detected security threats
            
        Returns:
            Turkish error message
        """
        if not threats:
            return "Güvenlik: Genel güvenlik ihlali tespit edildi."
        
        threat_types = set(threat["type"] for threat in threats)
        
        messages = {
            "XSS": "Güvenlik: Potansiyel XSS (Cross-Site Scripting) saldırısı tespit edildi.",
            "SQL_INJECTION": "Güvenlik: Potansiyel SQL enjeksiyonu saldırısı tespit edildi.",
            "PATH_TRAVERSAL": "Güvenlik: Potansiyel dizin geçiş saldırısı tespit edildi.",
            "COMMAND_INJECTION": "Güvenlik: Potansiyel komut enjeksiyonu saldırısı tespit edildi."
        }
        
        if len(threat_types) == 1:
            threat_type = list(threat_types)[0]
            return messages.get(threat_type, "Güvenlik: Güvenlik ihlali tespit edildi.")
        else:
            return "Güvenlik: Birden fazla güvenlik tehdidi tespit edildi. İstek reddedildi."
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe storage.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename safe for filesystem
        """
        if not isinstance(filename, str):
            return "file"
        
        # Remove path separators and dangerous characters
        sanitized = re.sub(r'[<>:"|?*\\/]', '_', filename)
        
        # Remove control characters
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32)
        
        # Limit length
        if len(sanitized) > 255:
            name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
            sanitized = name[:250] + ('.' + ext if ext else '')
        
        # Ensure not empty
        if not sanitized.strip():
            sanitized = "file"
        
        return sanitized
    
    def sanitize_url(self, url: str) -> Optional[str]:
        """Sanitize and validate URL.
        
        Args:
            url: URL to sanitize
            
        Returns:
            Sanitized URL if valid, None if invalid
        """
        if not isinstance(url, str):
            return None
        
        try:
            parsed = urlparse(url)
            
            # Only allow http/https
            if parsed.scheme not in ['http', 'https']:
                return None
            
            # Reconstruct clean URL
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            
            return clean_url
        
        except Exception:
            return None


# Global service instance
input_sanitization_service = InputSanitizationService()