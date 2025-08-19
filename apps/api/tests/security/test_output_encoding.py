"""
Ultra enterprise output encoding tests for Task 3.10.
Tests safe output encoding for user-generated content.
"""

import pytest
from app.services.output_encoding_service import output_encoding_service


class TestOutputEncodingService:
    """Test output encoding service functionality."""

    def test_html_content_encoding(self):
        """Test HTML content encoding for safe display."""

        test_cases = [
            # Basic HTML entities
            (
                "<script>alert('xss')</script>",
                "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;",
            ),
            ("'\"&<>", "&#x27;&quot;&amp;&lt;&gt;"),
            ("Normal text", "Normal text"),
            ("", ""),
            (None, ""),
            # Special characters
            ("Text with\nnewlines\tand\ttabs", "Text with&#10;newlines&#9;and&#9;tabs"),
            ("Equals = sign", "Equals &#x3D; sign"),
            ("Backtick ` character", "Backtick &#x60; character"),
            ("Forward / slash", "Forward &#x2F; slash"),
            # Mixed content
            (
                "<p>Paragraph with 'quotes' & symbols</p>",
                "&lt;p&gt;Paragraph with &#x27;quotes&#x27; &amp; symbols&lt;/p&gt;",
            ),
        ]

        for input_text, expected in test_cases:
            result = output_encoding_service.encode_html_content(input_text)
            assert result == expected

    def test_html_attribute_encoding(self):
        """Test HTML attribute encoding."""

        test_cases = [
            ("value", '"value"'),
            ("value with spaces", '"value&#32;with&#32;spaces"'),
            ("<script>", '"&lt;script&gt;"'),
            ("'quotes'", '"&#x27;quotes&#x27;"'),
            ("", '""'),
            (None, '""'),
        ]

        for input_text, expected in test_cases:
            result = output_encoding_service.encode_html_attribute(input_text)
            assert result == expected

    def test_javascript_string_encoding(self):
        """Test JavaScript string encoding."""

        test_cases = [
            ("Hello world", '"Hello world"'),
            ("Line\nbreaks\tand\rreturns", '"Line\\nbreaks\\tand\\rreturns"'),
            ("'Single' and \"double\" quotes", '"\\\'Single\\\' and \\"double\\" quotes"'),
            ("Backslash \\ character", '"Backslash \\\\ character"'),
            (
                "<script>alert('xss')</script>",
                "\"\\x3Cscript\\x3Ealert(\\'xss\\')\\x3C\\x2Fscript\\x3E\"",
            ),
            ("", '""'),
            (None, '""'),
        ]

        for input_text, expected in test_cases:
            result = output_encoding_service.encode_javascript_string(input_text)
            assert result == expected

    def test_url_component_encoding(self):
        """Test URL component encoding."""

        test_cases = [
            ("hello world", "hello%20world"),
            ("user@example.com", "user%40example.com"),
            ("path/to/resource", "path%2Fto%2Fresource"),
            ("query=value&other=data", "query%3Dvalue%26other%3Ddata"),
            ("<script>alert('xss')</script>", "%3Cscript%3Ealert%28%27xss%27%29%3C%2Fscript%3E"),
            ("", ""),
            (None, ""),
        ]

        for input_text, expected in test_cases:
            result = output_encoding_service.encode_url_component(input_text)
            assert result == expected

    def test_css_value_encoding(self):
        """Test CSS value encoding."""

        test_cases = [
            ("normal-value", "normal-value"),
            ("value with spaces", "value with spaces"),
            ("'single quotes'", "\\'single quotes\\'"),
            ('"double quotes"', '\\"double quotes\\"'),
            ("line\nbreaks", "line\\A breaks"),
            ("expression(alert('xss'))", "expression\\28 alert\\28 \\'xss\\'\\29 \\29 "),
            ("", ""),
            (None, ""),
        ]

        for input_text, expected in test_cases:
            result = output_encoding_service.encode_css_value(input_text)
            assert result == expected

    def test_json_value_encoding(self):
        """Test JSON value encoding."""

        test_cases = [
            ("string", '"string"'),
            ("string with 'quotes'", "\"string with 'quotes'\""),
            (123, "123"),
            (True, "true"),
            (None, "null"),
            ({"key": "value"}, '{"key": "value"}'),
            (["item1", "item2"], '["item1", "item2"]'),
            ("<script>alert('xss')</script>", "\"<script>alert('xss')</script>\""),
        ]

        for input_value, expected in test_cases:
            result = output_encoding_service.encode_json_value(input_value)
            assert result == expected

    def test_xml_content_encoding(self):
        """Test XML content encoding."""

        test_cases = [
            ("normal text", "normal text"),
            ("<tag>content</tag>", "&lt;tag&gt;content&lt;/tag&gt;"),
            ("'quotes' & symbols", "&#x27;quotes&#x27; &amp; symbols"),
            ("text\vwith\x00null", "text&#11;with"),  # Vertical tab encoded, null removed
            ("", ""),
            (None, ""),
        ]

        for input_text, expected in test_cases:
            result = output_encoding_service.encode_xml_content(input_text)
            assert result == expected

    def test_context_based_encoding(self):
        """Test context-based encoding selection."""

        test_input = "<script>alert('test')</script>"

        # Test different contexts
        html_result = output_encoding_service.encode_for_context(test_input, "html")
        js_result = output_encoding_service.encode_for_context(test_input, "js")
        css_result = output_encoding_service.encode_for_context(test_input, "css")
        url_result = output_encoding_service.encode_for_context(test_input, "url")
        json_result = output_encoding_service.encode_for_context(test_input, "json")
        xml_result = output_encoding_service.encode_for_context(test_input, "xml")
        attr_result = output_encoding_service.encode_for_context(test_input, "attr")

        # Each context should produce different encoding
        contexts = [
            html_result,
            js_result,
            css_result,
            url_result,
            json_result,
            xml_result,
            attr_result,
        ]

        # Most should be different (some might be same if encoding is similar)
        assert len(set(contexts)) >= 4  # At least 4 different encodings

        # All should be safe (no raw script tags)
        for result in contexts:
            assert "<script>" not in result
            assert "alert(" not in result or "\\x" in result or "&" in result

    def test_user_content_safe_encoding(self):
        """Test safe encoding of user-generated content."""

        user_inputs = [
            "Normal user comment",
            "<script>alert('xss')</script>",
            "User posted: <b>bold text</b>",
            "Comment with 'quotes' and symbols &",
            "Multi\nline\ncontent",
            "",
        ]

        for user_input in user_inputs:
            result = output_encoding_service.encode_user_content_safe(user_input)

            # Should be safe for HTML display
            assert "<script>" not in result
            assert "javascript:" not in result
            assert "onerror=" not in result

            # Should preserve readability for legitimate content
            if "Normal user comment" in user_input:
                assert "Normal user comment" in result

    def test_template_data_safety(self):
        """Test creation of safe template data."""

        unsafe_data = {
            "username": "<script>alert('xss')</script>",
            "comment": "User said: 'hello world'",
            "count": 42,
            "is_active": True,
            "tags": ["tag1", "tag2"],
            "metadata": {"key": "value"},
        }

        safe_data = output_encoding_service.create_safe_template_data(unsafe_data)

        # Check that all values are safely encoded
        assert "<script>" not in safe_data["username"]
        assert "&lt;script&gt;" in safe_data["username"]

        assert "&#x27;" in safe_data["comment"]  # Single quotes encoded

        assert safe_data["count"] == "42"
        assert safe_data["is_active"] == "True"

        # Lists and dicts should be JSON-encoded
        assert '"tag1"' in safe_data["tags"]
        assert '"key"' in safe_data["metadata"]

    def test_api_response_safety(self):
        """Test creation of safe API responses."""

        unsafe_response = {
            "message": "<script>alert('xss')</script>",
            "data": {
                "user_input": "User typed: <img src=x onerror=alert(1)>",
                "nested": {"field": "javascript:alert('nested')"},
            },
            "items": ["item with <script>", {"name": "<b>bold</b>"}],
        }

        safe_response = output_encoding_service.create_safe_api_response(unsafe_response)

        # Check nested safety
        assert "<script>" not in str(safe_response)
        assert "javascript:" not in str(safe_response)
        assert "onerror=" not in str(safe_response)

        # Check structure preservation
        assert "message" in safe_response
        assert "data" in safe_response
        assert "items" in safe_response
        assert isinstance(safe_response["items"], list)
        assert isinstance(safe_response["data"], dict)

    def test_encoding_performance(self):
        """Test encoding performance with large content."""

        import time

        # Large content
        large_content = "User content " * 10000  # ~120KB

        start_time = time.time()
        result = output_encoding_service.encode_html_content(large_content)
        end_time = time.time()

        # Should complete quickly (< 1 second)
        assert end_time - start_time < 1.0
        assert "User content" in result

    def test_unicode_preservation(self):
        """Test that Unicode characters are properly preserved."""

        unicode_content = "Unicode: üöäß 中文 العربية 🚀 תרבות"

        # HTML encoding should preserve Unicode
        html_result = output_encoding_service.encode_html_content(unicode_content)
        assert "Unicode:" in html_result

        # JavaScript encoding should handle Unicode
        js_result = output_encoding_service.encode_javascript_string(unicode_content)
        assert '"Unicode:' in js_result

        # URL encoding should encode Unicode properly
        url_result = output_encoding_service.encode_url_component(unicode_content)
        assert "Unicode" in url_result or "%" in url_result  # Either preserved or percent-encoded

    def test_edge_cases(self):
        """Test edge cases in encoding."""

        edge_cases = [
            None,
            "",
            0,
            False,
            [],
            {},
            "\x00\x01\x02",  # Control characters
            "A" * 1000000,  # Very long string
        ]

        for edge_case in edge_cases:
            # Should not raise exceptions
            html_result = output_encoding_service.encode_html_content(edge_case)
            js_result = output_encoding_service.encode_javascript_string(edge_case)
            url_result = output_encoding_service.encode_url_component(edge_case)

            # Results should be strings
            assert isinstance(html_result, str)
            assert isinstance(js_result, str)
            assert isinstance(url_result, str)

    def test_nested_encoding_safety(self):
        """Test that multiple rounds of encoding remain safe."""

        malicious_input = "<script>alert('xss')</script>"

        # Double encode
        first_encode = output_encoding_service.encode_html_content(malicious_input)
        second_encode = output_encoding_service.encode_html_content(first_encode)

        # Both should be safe
        assert "<script>" not in first_encode
        assert "<script>" not in second_encode
        assert "&lt;script&gt;" in first_encode

        # Second encoding should further escape
        assert "&amp;lt;" in second_encode or "&lt;" in second_encode
