from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationReport:
    ok: bool
    object_count: int
    details: dict
