from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from ..logging_setup import get_logger
from ..schemas.cad import AssemblyRequestV1

# from ..llm import generate_freecad_script_for_planetary  # Temporarily disabled
from .service import detect_freecad
from .subprocess_runner import run_subprocess_with_timeout

logger = get_logger(__name__)


FORBIDDEN_IMPORTS = [r"FreeCADGui", r"PySide", r"QtGui", r"QtCore", r"os\.system", r"subprocess"]


def validate_script_security(script: str) -> None:
    for pattern in FORBIDDEN_IMPORTS:
        if re.search(pattern, script):
            raise ValueError(f"Üretilen script yasak modül içeriyor: {pattern}")


def build_freecad_python(script_body: str) -> str:
    # Tek recompute ve FCStd kaydı
    return f"""
import sys
import time
import os
import Part
import App
doc = App.newDocument('Assembly')
start=time.time()

{script_body}

App.ActiveDocument.recompute()
out_fcstd = os.environ.get('OUT_FCSTD')
if not out_fcstd:
    raise RuntimeError('OUT_FCSTD tanımlı değil')
App.ActiveDocument.saveAs(out_fcstd)
elapsed_ms=int((time.time()-start)*1000)
print('ELAPSED_MS='+str(elapsed_ms))
sys.exit(0)
"""


def build_freecad_validation() -> str:
    return """
import sys, os, App
path=os.environ.get('OUT_FCSTD')
if not path: raise RuntimeError('OUT_FCSTD yok')
doc=App.openDocument(path)
App.ActiveDocument.recompute()
obj_count=len(App.ActiveDocument.Objects)
print('OBJ_COUNT='+str(obj_count))
if obj_count < 5:
    raise RuntimeError('Nesne sayısı eşik altında')
sys.exit(0)
"""


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
def generate_and_validate(req: AssemblyRequestV1, pid_file: str | None = None) -> tuple[Path, dict]:
    # FreeCADCmd var mı
    fc = detect_freecad()
    if not fc.found or not fc.path:
        raise RuntimeError("FreeCADCmd bulunamadı")

    # bundle = generate_freecad_script_for_planetary(req.spec.model_dump())  # Temporarily disabled
    # script_body = bundle["script"]  # Temporarily disabled
    script_body = "# Placeholder script\nprint('LLM generation temporarily disabled')"
    validate_script_security(script_body)
    full_script = build_freecad_python(script_body)
    out_dir = Path(tempfile.mkdtemp())
    out_fcstd = out_dir / "assembly.fcstd"
    run_res = run_freecad_cmd(fc.path, full_script, out_fcstd, settings.freecad_timeout_seconds, pid_file=pid_file)
    if run_res["returncode"] != 0:
        raise RuntimeError(f"FreeCADCmd üretim hatası: {run_res['stderr']}")
    # Doğrulama
    val_script = build_freecad_validation()
    val_res = run_freecad_cmd(fc.path, val_script, out_fcstd, 120, pid_file=pid_file)
    if val_res["returncode"] != 0:
        raise RuntimeError(f"FreeCADCmd doğrulama hatası: {val_res['stderr']}")
    return out_fcstd, {"elapsed_ms": run_res["elapsed_ms"], "validation_ms": val_res["elapsed_ms"]}


def run_freecad_cmd(freecad_path: str, script: str, out_fcstd: Path, timeout: int, pid_file: str | None = None) -> dict:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
    tmp.write(script.encode("utf-8"))
    tmp.close()
    env = os.environ.copy()
    env["OUT_FCSTD"] = str(out_fcstd)
    res = run_subprocess_with_timeout([freecad_path, tmp.name], timeout_seconds=timeout, env=env, pid_file=pid_file)
    return {"returncode": res.returncode, "stdout": res.stdout, "stderr": res.stderr, "elapsed_ms": res.elapsed_ms}


