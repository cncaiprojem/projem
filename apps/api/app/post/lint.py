from __future__ import annotations

from typing import Dict, List


SUPPORTED_DIALECTS = {"fanuc", "grbl", "linuxcnc"}


def lint_gcode(text: str, dialect: str, tool_plane_enabled: bool) -> Dict:
    warnings: List[str] = []
    errors: List[str] = []
    if dialect not in SUPPORTED_DIALECTS:
        warnings.append(f"Bilinmeyen dialect: {dialect}")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not any(ln.startswith(("G21", "G20")) for ln in lines[:10]):
        warnings.append("Units (G21/G20) başta görünmüyor")
    if not any(ln.startswith("G90") for ln in lines[:10]):
        warnings.append("Absolute (G90) başta görünmüyor")
    if tool_plane_enabled and not any(ln.startswith("G68") for ln in lines):
        warnings.append("Tool plane etkin ama G68 görülmedi")
    # Basit sıra kontrolü: Units -> G90 -> WCS -> T/M6 -> G43 -> M8
    order_tags = ["G2", "G90", "( WCS", "T", "G43", "M8"]
    last_index = -1
    for tag in order_tags:
        idx = next((i for i, ln in enumerate(lines) if ln.startswith(tag)), None)
        if idx is None:
            continue
        if idx < last_index:
            warnings.append(f"Sıra uyarısı: {tag} önceki komutlardan sonra gelmeli")
        last_index = idx
    return {"warnings": warnings, "errors": errors}
