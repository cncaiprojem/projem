from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..storage import upload_and_sign


@dataclass
class BuildResult:
    fcstd_path: Path
    toolpath_json: Path | None
    toolpath_csv: Path | None


def build_setup_job(*, setup_id: int, fast_mode: bool) -> BuildResult:
    # Placeholder: gerçek FreeCAD entegrasyonu M18.3 boyunca genişletilecek
    # Şimdilik sadece bir boş dosya üretip artefakt akışını doğruluyoruz
    tmp = Path("/tmp/m18")
    tmp.mkdir(parents=True, exist_ok=True)
    fc = tmp / f"setup_{setup_id}.FCStd"
    fc.write_bytes(b"FCStd placeholder")
    j = tmp / f"setup_{setup_id}_toolpath.json"
    j.write_text("{}", encoding="utf-8")
    c = tmp / f"setup_{setup_id}_toolpath.csv"
    c.write_text("op,tool,x,y,z,f\n", encoding="utf-8")
    # Upload examples (no-op if S3 disabled)
    try:
        upload_and_sign(fc, "fcstd")
        upload_and_sign(j, "toolpath-json")
        upload_and_sign(c, "toolpath-csv")
    except Exception:
        ...
    return BuildResult(fcstd_path=fc, toolpath_json=j, toolpath_csv=c)


