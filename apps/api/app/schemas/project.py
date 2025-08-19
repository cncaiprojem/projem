from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProjectType = Literal["part", "assembly"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: ProjectType = "part"
    source: Literal["prompt", "upload"] = "prompt"
    prompt: str | None = None


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
    context: dict[str, Any] | None = None


class DesignPlanOut(BaseModel):
    is_cnc_related: bool
    kind: ProjectType
    missing: list[str]
    plan: dict[str, Any]


class DesignAnswerIn(BaseModel):
    project_id: int
    answers: dict[str, Any]


class DesignAnswerOut(DesignPlanOut):
    pass


