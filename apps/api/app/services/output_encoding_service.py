"""
Ultra enterprise output encoding service for FreeCAD CNC/CAM platform.
Provides comprehensive output encoding for user-generated content display.
"""

from __future__ import annotations

import html
import json
import urllib.parse
from typing import Any, Dict, List, Union


class OutputEncodingService:
    """Ultra enterprise output encoding for safe content display.
    
    Provides comprehensive encoding for different output contexts:
    - HTML context encoding
    - JavaScript context encoding  
    - URL context encoding
    - CSS context encoding
    - JSON context encoding
    """
    
    def __init__(self):
        """Initialize the output encoding service."""
        # HTML entity mapping for comprehensive encoding
        self.html_entities = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;',
            '/': '&#x2F;',
            '`': '&#x60;',
            '=': '&#x3D;',
            '\n': '&#10;',
            '\r': '&#13;',
            '\t': '&#9;'
        }
        
        # JavaScript dangerous characters
        self.js_escape_chars = {
            '\\': '\\\\',
            '"': '\\"',
            "'": "\\'",
            '\n': '\\n',
            '\r': '\\r',
            '\t': '\\t',
            '\b': '\\b',
            '\f': '\\f',
            '/': '\\/',
            '<': '\\x3C',
            '>': '\\x3E',
            '&': '\\x26',
            '=': '\\x3D',
            '+': '\\x2B'
        }
        
        # CSS dangerous characters
        self.css_escape_chars = {
            '"': '\\"',
            "'": "\\'",
            '\\': '\\\\',
            '\n': '\\A ',
            '\r': '\\D ',
            '\t': '\\9 ',
            '<': '\\3C ',
            '>': '\\3E ',
            '&': '\\26 ',
            '(': '\\28 ',
            ')': '\\29 ',
            '{': '\\7B ',
            '}': '\\7D '
        }
    
    def encode_html_content(self, content: Any) -> str:
        """Encode content for safe display in HTML context.
        
        Args:
            content: Content to encode for HTML display
            
        Returns:
            HTML-encoded content safe for display
        """
        if content is None:
            return ""
        
        if not isinstance(content, str):
            content = str(content)
        
        # Use comprehensive HTML encoding
        encoded = content
        for char, entity in self.html_entities.items():
            encoded = encoded.replace(char, entity)
        
        return encoded
    
    def encode_html_attribute(self, content: Any) -> str:
        """Encode content for safe use in HTML attributes.
        
        Args:
            content: Content to encode for HTML attribute
            
        Returns:
            Attribute-safe encoded content
        """
        if content is None:
            return ""
        
        if not isinstance(content, str):
            content = str(content)
        
        # HTML attribute encoding (stricter than content)
        encoded = self.encode_html_content(content)
        
        # Additional attribute-specific encoding
        encoded = encoded.replace(' ', '&#32;')
        
        return f'"{encoded}"'
    
    def encode_javascript_string(self, content: Any) -> str:
        """Encode content for safe use in JavaScript strings.
        
        Args:
            content: Content to encode for JavaScript
            
        Returns:
            JavaScript-safe encoded string
        """
        if content is None:
            return '""'
        
        if not isinstance(content, str):
            content = str(content)
        
        # JavaScript string encoding
        encoded = content
        for char, escape in self.js_escape_chars.items():
            encoded = encoded.replace(char, escape)
        
        return f'"{encoded}"'
    
    def encode_url_component(self, content: Any) -> str:
        """Encode content for safe use in URL parameters.
        
        Args:
            content: Content to encode for URL
            
        Returns:
            URL-encoded content
        """
        if content is None:
            return ""
        
        if not isinstance(content, str):
            content = str(content)
        
        # URL percent encoding
        return urllib.parse.quote(content, safe='')
    
    def encode_css_value(self, content: Any) -> str:
        """Encode content for safe use in CSS values.
        
        Args:
            content: Content to encode for CSS
            
        Returns:
            CSS-safe encoded content
        """
        if content is None:
            return ""
        
        if not isinstance(content, str):
            content = str(content)
        
        # CSS value encoding
        encoded = content
        for char, escape in self.css_escape_chars.items():
            encoded = encoded.replace(char, escape)
        
        return encoded
    
    def encode_json_value(self, content: Any) -> str:
        """Encode content for safe use in JSON context.
        
        Args:
            content: Content to encode for JSON
            
        Returns:
            JSON-safe encoded string
        """
        try:
            # Use built-in JSON encoding for safety
            return json.dumps(content, ensure_ascii=True)
        except (TypeError, ValueError):
            # Fallback for non-serializable content
            return json.dumps(str(content), ensure_ascii=True)
    
    def encode_xml_content(self, content: Any) -> str:
        """Encode content for safe use in XML context.
        
        Args:
            content: Content to encode for XML
            
        Returns:
            XML-safe encoded content
        """
        if content is None:
            return ""
        
        if not isinstance(content, str):
            content = str(content)
        
        # XML uses same encoding as HTML for most characters
        encoded = self.encode_html_content(content)
        
        # Additional XML-specific characters
        encoded = encoded.replace('\v', '&#11;')  # Vertical tab
        encoded = encoded.replace('\0', '')  # Remove null bytes
        
        return encoded
    
    def encode_for_context(self, content: Any, context: str) -> str:
        """Encode content based on output context.
        
        Args:
            content: Content to encode
            context: Output context ('html', 'js', 'css', 'url', 'json', 'xml', 'attr')
            
        Returns:
            Context-appropriate encoded content
        """
        context = context.lower()
        
        encoding_map = {
            'html': self.encode_html_content,
            'javascript': self.encode_javascript_string,
            'js': self.encode_javascript_string,
            'css': self.encode_css_value,
            'url': self.encode_url_component,
            'json': self.encode_json_value,
            'xml': self.encode_xml_content,
            'attribute': self.encode_html_attribute,
            'attr': self.encode_html_attribute
        }
        
        encoder = encoding_map.get(context, self.encode_html_content)
        return encoder(content)
    
    def encode_user_content_safe(self, content: Any, allowed_tags: List[str] = None) -> str:
        """Safely encode user-generated content with optional allowed tags.
        
        Args:
            content: User-generated content
            allowed_tags: List of allowed HTML tags (if any)
            
        Returns:
            Safely encoded content
        """
        if content is None:
            return ""
        
        if not isinstance(content, str):
            content = str(content)
        
        # For now, always do full encoding (no HTML allowed)
        # This can be extended later with a proper HTML sanitizer
        # if specific tags need to be allowed
        
        return self.encode_html_content(content)
    
    def create_safe_template_data(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Create template data with all values safely encoded.
        
        Args:
            data: Raw template data
            
        Returns:
            Dictionary with all string values HTML-encoded
        """
        safe_data = {}
        
        for key, value in data.items():
            if isinstance(value, str):
                safe_data[key] = self.encode_html_content(value)
            elif isinstance(value, (int, float, bool)):
                safe_data[key] = str(value)
            elif isinstance(value, (list, dict)):
                safe_data[key] = self.encode_json_value(value)
            else:
                safe_data[key] = self.encode_html_content(str(value))
        
        return safe_data
    
    def create_safe_api_response(self, data: Any) -> Any:
        """Create API response with safely encoded string values.
        
        Args:
            data: Raw API response data
            
        Returns:
            Response data with encoded strings
        """
        if isinstance(data, str):
            return self.encode_html_content(data)
        elif isinstance(data, dict):
            return {key: self.create_safe_api_response(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self.create_safe_api_response(item) for item in data]
        else:
            return data


# Global service instance
output_encoding_service = OutputEncodingService()