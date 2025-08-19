from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class Segment:
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float


def swept_cylinder_min_clearance(segments: Iterable[Segment], holder_diameter_mm: float, clearance_mm: float) -> tuple[float, list[dict]]:
    # Basit sahte hesap: segment uzunluğunu min clearance ile karşılaştır
    # M18.4'te gerçek geometri kesişimi ile değiştirilecek
    min_clear = 1e9
    hits: list[dict] = []
    for i, s in enumerate(segments):
        dx = s.x1 - s.x0
        dy = s.y1 - s.y0
        dz = s.z1 - s.z0
        L = max(1e-6, (dx*dx + dy*dy + dz*dz) ** 0.5)
        cur_clear = holder_diameter_mm/2 - 0.0  # placeholder
        min_clear = min(min_clear, cur_clear)
        if cur_clear < clearance_mm:
            hits.append({"index": i, "clear": cur_clear})
    return min_clear if min_clear < 1e9 else 0.0, hits


