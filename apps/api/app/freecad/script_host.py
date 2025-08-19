from __future__ import annotations

from types import MappingProxyType
from typing import Any, Dict


ALLOWED_GLOBALS: Dict[str, Any] = {
    "__builtins__": MappingProxyType(
        {  # minimum güvenli yerleşikler
            "range": range,
            "len": len,
            "min": min,
            "max": max,
            "abs": abs,
            "float": float,
            "int": int,
            "str": str,
        }
    )
}


def build_exec_env() -> Dict[str, Any]:
    # Whitelist modüller FreeCAD içerisinde import edilecektir
    env: Dict[str, Any] = dict(ALLOWED_GLOBALS)
    allowed_modules = {"App": None, "Part": None, "Sketcher": None, "Asm4": None, "Path": None}
    env.update(allowed_modules)
    return env
