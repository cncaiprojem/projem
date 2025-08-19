from __future__ import annotations

from pydantic import BaseModel

from .cad import ArtefactRef


class DesignBrief(BaseModel):
  prompt: str
  targets: dict | None = None
  materials: dict | None = None
  standards: list[str] | None = None
  constraints: list[str] | None = None


class DesignAnalysisQuestion(BaseModel):
  id: str
  text: str


class DesignJobCreate(BaseModel):
  brief: DesignBrief
  auto_clarify: bool = True
  chain: dict | None = None  # { cam?:bool, sim?:bool }


class BOMItem(BaseModel):
  part_no: str
  name: str
  material: str
  qty: int


class DesignJobResult(BaseModel):
  job_id: int
  artefacts: list[ArtefactRef]
  bom: list[BOMItem] | None = None
  params: dict | None = None
  notes: str | None = None


