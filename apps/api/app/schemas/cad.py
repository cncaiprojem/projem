from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class GearStage(BaseModel):
    ratio: float = Field(..., gt=0, description="Kademe dişli oranı (örn. 3.2)")
    helix: bool = Field(default=False, description="Helisel diş mi?")
    module: float | None = Field(default=None, gt=0, description="Dişli modul değeri (opsiyonel)")


class MaterialsSpec(BaseModel):
    gear: str = Field(..., min_length=1, description="Dişli malzemesi")
    housing: str = Field(..., min_length=1, description="Gövde malzemesi")


class OutputsSpec(BaseModel):
    torqueNm: float = Field(..., gt=0, description="Çıkış torku (Nm)")
    radialN: float = Field(..., ge=0, description="Radyal yük (N)")
    axialN: float = Field(..., ge=0, description="Eksenel yük (N)")


class PlanetarySpec(BaseModel):
    stages: list[GearStage] = Field(..., min_length=1, description="Kademe listesi")
    overall_ratio: float = Field(..., gt=0, description="Toplam oran (örn. 100.0)")
    power_kW: float = Field(..., gt=0, description="Güç (kW)")
    materials: MaterialsSpec
    outputs: OutputsSpec

    @field_validator("overall_ratio")
    @classmethod
    def check_overall_ratio(cls, v: float, values):
        try:
            stages = values.data.get("stages") or []
            if stages:
                prod = 1.0
                for s in stages:
                    prod *= s.ratio
                # oranlar farklı olabilir; fark büyükse uyarı yerine 422 yukarı seviyede verilecek
        except Exception:
            pass
        return v


class AssemblyRequestV1(BaseModel):
    type: str = Field(..., pattern="^planetary_gearbox$", description='"planetary_gearbox" olmalı')
    spec: PlanetarySpec


class AnalysisQuestion(BaseModel):
    field: str
    question: str


class AnalysisResponse(BaseModel):
    questions: list[AnalysisQuestion] = Field(default_factory=list)
    appliedDefaults: list[str] = Field(default_factory=list)


class ArtefactRef(BaseModel):
    type: str
    path: str
    size: int
    sha256: str
    signed_url: str | None = None


class AssemblyJobCreate(BaseModel):
    request: AssemblyRequestV1
    idempotency_key: str | None = None


class AssemblyJobResult(BaseModel):
    id: int
    status: str
    error_code: str | None = None
    error_message: str | None = None
    metrics: dict | None = None
    artefacts: list[ArtefactRef] | None = None


