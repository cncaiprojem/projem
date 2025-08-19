from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .cad import ArtefactRef


class DesignBrief(BaseModel):
    prompt: str
    targets: Optional[dict] = None
    materials: Optional[dict] = None
    standards: Optional[List[str]] = None
    constraints: Optional[List[str]] = None


class DesignAnalysisQuestion(BaseModel):
    id: str
    text: str


class DesignJobCreate(BaseModel):
    brief: DesignBrief
    auto_clarify: bool = True
    chain: Optional[dict] = None  # { cam?:bool, sim?:bool }


class BOMItem(BaseModel):
    part_no: str
    name: str
    material: str
    qty: int


class DesignJobResult(BaseModel):
    job_id: int
    artefacts: List[ArtefactRef]
    bom: Optional[List[BOMItem]] = None
    params: Optional[dict] = None
    notes: Optional[str] = None
