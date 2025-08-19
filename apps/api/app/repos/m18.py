from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models_project import Collision, Op3D, Setup


def get_setup(s: Session, setup_id: int) -> Setup | None:
    return s.get(Setup, setup_id)


def list_ops3d(s: Session, setup_id: int) -> list[Op3D]:
    return s.query(Op3D).filter(Op3D.setup_id == setup_id).order_by(Op3D.id.asc()).all()


def add_ops3d(s: Session, setup_id: int, ops: list[dict[str, Any]]) -> int:
    count = 0
    for op in ops:
        rec = Op3D(
            setup_id=setup_id,
            op_type=op.get("op_type", "surface"),
            target_faces_json=op.get("target_faces"),
            tool_id=op.get("tool_id"),
            params_json=op.get("params") or {},
        )
        s.add(rec)
        count += 1
    s.commit()
    return count


def add_collision(s: Session, setup_id: int, phase: str, ctype: str, severity: str, details: dict[str, Any]) -> int:
    rec = Collision(setup_id=setup_id, phase=phase, type=ctype, severity=severity, details_json=details)
    s.add(rec)
    s.commit()
    return rec.id


