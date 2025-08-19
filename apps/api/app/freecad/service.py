from __future__ import annotations

import os
import shutil

from ..config import settings
from ..logging_setup import get_logger
from ..schemas import FreeCADDetectResponse
from .subprocess_runner import run_subprocess_with_timeout


def find_freecadcmd_path() -> str | None:
    if settings.freecadcmd_path and os.path.isfile(settings.freecadcmd_path):
        return settings.freecadcmd_path
    cand = shutil.which("FreeCADCmd")
    if cand:
        return cand
    # Yaygın yollar
    for path in [
        "/usr/bin/FreeCADCmd",
        "/usr/local/bin/FreeCADCmd",
        "C:/Program Files/FreeCAD 0.21/bin/FreeCADCmd.exe",
        "C:/Program Files/FreeCAD/bin/FreeCADCmd.exe",
    ]:
        if os.path.isfile(path):
            return path
    return None


def get_freecad_version(path: str) -> str | None:
    res = run_subprocess_with_timeout([path, "--version"], timeout_seconds=30)
    if res.returncode == 0 and res.stdout:
        return res.stdout.strip().splitlines()[0]
    return None


def check_asm4_available(path: str) -> bool | None:
    # FreeCADCmd içinden Asm4 modülü import edilebilir mi kontrol et
    script = (
        "import importlib, sys; "
        "ok=False\n"
        "try:\n    import importlib; import Asm4; print('ASM4_OK')\n    ok=True\n"
        "except Exception as e:\n    print('ASM4_ERR:'+str(e))\n"
    )
    res = run_subprocess_with_timeout([path, "-c", script], timeout_seconds=30)
    if "ASM4_OK" in res.stdout:
        return True
    if "ASM4_ERR" in res.stdout or res.returncode != 0:
        return False
    return None


def detect_freecad() -> FreeCADDetectResponse:
    path = find_freecadcmd_path()
    if not path:
        return FreeCADDetectResponse(found=False, message="FreeCADCmd bulunamadı")
    version = get_freecad_version(path)
    asm4 = check_asm4_available(path) if settings.freecad_asm4_required else None
    logger = get_logger(__name__)
    logger.info("FreeCADCmd tespit edildi", extra={"freecad_version": version})
    return FreeCADDetectResponse(found=True, path=path, version=version, asm4_available=asm4)


