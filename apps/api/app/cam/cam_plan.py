from __future__ import annotations

from typing import Any


def derive_cam_params(plan: dict[str, Any], strategy: str = "balanced") -> dict[str, Any]:
    """Plan (M13) + varsayılanlara göre operasyon listesi ve takım çaplarını önerir.
    Dönen yapı Path builder tarafından kullanılacaktır.
    """
    cad = (plan or {}).get("cad", {})
    material = plan.get("material") or (plan.get("answers", {}) or {}).get("malzeme") or "Al6061"
    size = cad.get("size", {"x": 90, "y": 60, "z": 8})
    th = float(size.get("z", 8))

    # Basit heuristik: 6mm endmill + 5mm drill; ince parçada daha küçük stepdown
    stepdown = 1.5 if strategy == "safe" else (2.5 if strategy == "fast" else 2.0)

    ops = []
    # 1) Face (üst düzleme)
    ops.append(
        {
            "type": "face",
            "tool": {"type": "endmill_flat", "dia": 6.0},
            "params": {"stepover": 60, "stepdown": min(stepdown, th), "pattern": "zigzag"},
        }
    )
    # 2) Contour (dış profil)
    ops.append(
        {
            "type": "contour",
            "tool": {"type": "endmill_flat", "dia": 6.0},
            "params": {"side": "outside", "depth_per_pass": stepdown, "finish_pass": True, "allowance": 0.2},
        }
    )
    # 3) Holes (varsa)
    for h in cad.get("holes", []):
        d = float(h.get("d", 5.0))
        ops.append(
            {
                "type": "drill",
                "tool": {"type": "drill", "dia": d},
                "params": {"peck": 2.0 if th > 6 else 0.0, "dwell_ms": 50 if th > 8 else 0},
            }
        )

    # 4) Chamfer (varsa)
    if cad.get("chamfer_mm"):
        ops.append(
            {
                "type": "chamfer",
                "tool": {"type": "chamfer", "dia": 6.0},
                "params": {"width": float(cad["chamfer_mm"]), "angle_deg": 45.0},
            }
        )

    return {"material": material, "ops": ops, "wcs": plan.get("wcs") or "G54"}


