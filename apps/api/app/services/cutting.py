# LEGACY SERVICE - DISABLED
# This service references legacy CuttingData model not in Task Master ERD
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models_cutting import CuttingData


def pick_cut(db: Session, material: str, tool_type: str, dia_mm: float, operation: str):
    q = (
        db.query(CuttingData)
        .filter(
            CuttingData.material == material,
            CuttingData.tool_type == tool_type,
            CuttingData.operation == operation,
            CuttingData.tool_dia_min_mm <= dia_mm,
            CuttingData.tool_dia_max_mm >= dia_mm,
        )
        .order_by(CuttingData.tool_dia_max_mm - CuttingData.tool_dia_min_mm)
    )
    row = q.first()
    if not row:
        # Güvenli default
        if tool_type == "drill":
            return dict(rpm=2500, feed=120, plunge=120, stepdown=dia_mm, stepover=0)
        if tool_type == "chamfer":
            return dict(rpm=8000, feed=350, plunge=150, stepdown=0.5, stepover=0)
        return dict(rpm=10000, feed=600, plunge=150, stepdown=max(1.0, dia_mm * 0.25), stepover=60)
    return dict(
        rpm=row.rpm,
        feed=row.feed_mm_min,
        plunge=row.plunge_mm_min,
        stepdown=row.stepdown_mm,
        stepover=row.stepover_pct,
    )
"""


# Task Master ERD replacement: Use Material model with cutting parameters
def pick_cut_task_master(material_name: str, tool_type: str, diameter_mm: float) -> dict:
    """
    Temporary placeholder for Task Master compatible cutting parameter logic.
    This should integrate with the Material model from Task Master ERD.
    """
    # Default safe cutting parameters until Material model is integrated
    if tool_type == "drill_twist":
        return {"rpm": 2500, "feed_mm_min": 120, "plunge_mm_min": 120, "stepdown_mm": diameter_mm}
    elif "chamfer" in tool_type:
        return {"rpm": 8000, "feed_mm_min": 350, "plunge_mm_min": 150, "stepdown_mm": 0.5}
    else:  # endmill types
        return {"rpm": 10000, "feed_mm_min": 600, "plunge_mm_min": 150, 
                "stepdown_mm": max(1.0, diameter_mm * 0.25)}


