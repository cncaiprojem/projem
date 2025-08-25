"""
Context dataclasses for API routers - Task 7.1
Enterprise-grade context objects for better code organization and reusability.

These context objects group related parameters to improve function signatures
and follow enterprise best practices for reducing parameter counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Response
from sqlalchemy.orm import Session

from ..middleware.jwt_middleware import AuthenticatedUser
from ..models.enums import JobType
from ..schemas.design_v2 import DesignCreateRequest


@dataclass
class JobRequestContext:
    """Context object for job request handling.
    
    Groups related input parameters for better code organization and maintainability.
    This follows enterprise best practices for reducing function parameter counts.
    
    Attributes:
        db: Database session for persistence operations
        idempotency_key: Optional idempotency key for duplicate prevention
        body: Request body containing design specifications
        job_type: Type of job being created
        current_user: Authenticated user making the request
    """
    db: Session
    idempotency_key: Optional[str]
    body: DesignCreateRequest
    job_type: JobType
    current_user: AuthenticatedUser


@dataclass
class JobResponseContext:
    """Output context object for job response handling.
    
    Separates output-related fields from input context for clearer separation of concerns,
    as recommended by Copilot PR review.
    
    Attributes:
        response: FastAPI response object for header manipulation
        estimated_duration: Estimated processing time in seconds
    """
    response: Response
    estimated_duration: int