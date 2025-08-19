from __future__ import annotations

from types import MappingProxyType
from typing import Any

ALLOWED_GLOBALS: dict[str, Any] = {
    "__builtins__": MappingProxyType({  # minimum güvenli yerleşikler
        "range": range,
        "len": len,
        "min": min,
        "max": max,
        "abs": abs,
        "float": float,
        "int": int,
        "str": str,
    })
}


def build_exec_env() -> dict[str, Any]:
    # Whitelist modüller FreeCAD içerisinde import edilecektir
    env: dict[str, Any] = dict(ALLOWED_GLOBALS)
    allowed_modules = {"App": None, "Part": None, "Sketcher": None, "Asm4": None, "Path": None}
    env.update(allowed_modules)
    return env


