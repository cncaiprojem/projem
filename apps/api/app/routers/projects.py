# LEGACY ROUTER - DISABLED
# This router uses legacy Project model not in Task Master ERD
# The project concept has been replaced with the Model entity in Task Master
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy.orm import Session

from ..db import db_session
from ..models_project import Project, ProjectType, ProjectStatus
from ..schemas.project import ProjectCreate, ProjectOut


router = APIRouter(prefix="/api/v1/projects", tags=["Projeler"])
"""

# Task Master ERD compatible router would use Model entity instead
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/legacy-disabled", tags=["Disabled"])

# All legacy project endpoints are disabled - use Model entity endpoints instead
