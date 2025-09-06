"""
Error Response Models

This module contains the data models used for error responses,
including suggestions and remediation links.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ErrorSuggestion(BaseModel):
    """Actionable suggestion for error remediation."""
    en: str = Field(description="English suggestion text")
    tr: str = Field(description="Turkish suggestion text")


class RemediationLink(BaseModel):
    """Documentation or resource link for error remediation."""
    title: str = Field(description="Link title")
    url: str = Field(description="Link URL")


class ErrorDetails(BaseModel):
    """Detailed error information."""
    component: Optional[str] = Field(default=None, description="Component where error occurred")
    exception_class: Optional[str] = Field(default=None, description="Exception class name")
    phase: Optional[str] = Field(default=None, description="Processing phase")
    file_format: Optional[str] = Field(default=None, description="File format if relevant")
    param: Optional[Dict[str, Any]] = Field(default=None, description="Sanitized parameters")