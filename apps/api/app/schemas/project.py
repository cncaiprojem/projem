from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

ProjectType = Literal["part", "assembly"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: ProjectType = "part"
    source: Literal["prompt", "upload"] = "prompt"
    prompt: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    type: str
    status: str

    class Config:
        from_attributes = True


class DesignPlanIn(BaseModel):
    project_id: int
    prompt: str
    context: Optional[Dict[str, Any]] = None


class DesignPlanOut(BaseModel):
    is_cnc_related: bool
    kind: ProjectType
    missing: List[str]
    plan: Dict[str, Any]


class DesignAnswerIn(BaseModel):
    project_id: int
    answers: Dict[str, Any]


class DesignAnswerOut(DesignPlanOut):
    pass
