from fastapi import APIRouter

from ..freecad.service import detect_freecad
from ..schemas import FreeCADDetectResponse

router = APIRouter(prefix="/api/v1/freecad", tags=["FreeCAD"])


@router.get("/detect", response_model=FreeCADDetectResponse)
def detect() -> FreeCADDetectResponse:
    return detect_freecad()


