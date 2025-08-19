from __future__ import annotations

from fastapi import APIRouter, HTTPException, Header, status
from datetime import datetime
from ..config import settings
from ..settings import app_settings as appset
from sqlalchemy.orm import Session

from ..db import db_session
from ..models import Job
from ..schemas.cad import (
    AnalysisResponse,
    AnalysisQuestion,
    AssemblyJobCreate,
    AssemblyJobResult,
    AssemblyRequestV1,
    PlanetarySpec,
)
from ..tasks.assembly import assembly_generate
from ..services.job_control import is_queue_paused


router = APIRouter(prefix="/api/v1/assemblies", tags=["Montaj Analiz/Üretim"])


CRITICAL_FIELDS = [
    ("spec.stages", "En az bir kademe (stages) belirtilmelidir."),
    ("spec.overall_ratio", "Toplam oran (overall_ratio) zorunludur."),
    ("spec.power_kW", "Güç (power_kW) zorunludur."),
    ("spec.materials.gear", "Dişli malzemesi (materials.gear) zorunludur."),
    ("spec.materials.housing", "Gövde malzemesi (materials.housing) zorunludur."),
]


def analyze_spec(spec: PlanetarySpec) -> AnalysisResponse:
    questions: list[AnalysisQuestion] = []
    applied: list[str] = []

    # Maks 5 soru: eksik/hatalı kritik alanları soralım
    # stages kontrolü
    if not spec.stages:
        questions.append(
            AnalysisQuestion(field="spec.stages", question="Kaç kademe ve oranları nedir?")
        )

    # overall vs stages çarpımı uyuşmuyor mu?
    prod = 1.0
    for s in spec.stages:
        prod *= s.ratio
    # %10 tolerans
    if spec.stages and not (0.9 <= (prod / spec.overall_ratio) <= 1.1):
        questions.append(
            AnalysisQuestion(
                field="spec.overall_ratio",
                question=f"Kademe oranlarının çarpımı ≈ {prod:.2f}. Toplam oranı {spec.overall_ratio} yerine {prod:.2f} olarak mı güncelleyelim?",
            )
        )

    return AnalysisResponse(questions=questions[:5], appliedDefaults=applied)


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(req: AssemblyRequestV1) -> AnalysisResponse:
    if req.type != "planetary_gearbox":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Desteklenmeyen montaj türü"
        )
    return analyze_spec(req.spec)


@router.post("", response_model=dict)
def create_assembly_job(
    body: AssemblyRequestV1,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    # Basit 422 doğrulama Pydantic tarafından sağlanır; ilave iş kuralları gerekiyorsa burada 422 verilebilir
    if appset.require_idempotency and not idempotency_key:
        raise HTTPException(status_code=422, detail="Idempotency-Key başlığı zorunludur")
    # freecad kuyruğu duraklatılmış mı?
    if is_queue_paused("freecad"):
        raise HTTPException(status_code=409, detail="freecad kuyruğu geçici olarak duraklatıldı.")
    with db_session() as s:
        if idempotency_key:
            exist = s.query(Job).filter_by(idempotency_key=idempotency_key, type="assembly").first()
            if exist:
                from ..audit import audit

                audit("idempotent_hit", job_id=exist.id, key=idempotency_key)
                return {"job_id": exist.id, "idempotent_hit": True}
        job = Job(
            type="assembly",
            status="pending",
            metrics={
                "request": body.model_dump(),
                "created_at": datetime.utcnow().isoformat(),
                "queue": "freecad",
            },
            idempotency_key=idempotency_key,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        try:
            assembly_generate.delay(job.id)
        except Exception:
            # kuyruğa gönderilemediyse kaydı geri al
            s.delete(job)
            s.commit()
            raise HTTPException(
                status_code=503, detail="Kuyruk geçici olarak erişilemiyor. Lütfen tekrar deneyin."
            )
        return {"job_id": job.id}
