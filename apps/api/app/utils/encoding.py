"""
Shared encoding utilities for consistent UTF-8 handling across the application.
"""

import sys
import codecs

def setup_utf8_encoding():
    """
    Set up UTF-8 encoding for all platforms.
    This ensures consistent handling of non-ASCII characters.
    """
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')