# LEGACY MODULE - DISABLED
# This module uses legacy Tool model not in Task Master ERD
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from typing import Dict, List

from ..db import db_session
from ..metrics import tool_scan_count_total
from ..models_tooling import Tool
"""

import glob
import json
import os
from typing import Dict, List


# Legacy functionality commented out - create placeholder for compatibility
def scan_toolbits(root: str) -> List[Dict]:
    """
    Legacy function - returns empty list until Task Master Tool model integration.
    """
    return []

# Original implementation disabled below:
"""
REQUIRED_KEYS = {"version", "geometry"}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate(tb: Dict) -> None:
    if not isinstance(tb, dict) or not REQUIRED_KEYS.issubset(tb.keys()):
        raise ValueError("ToolBit JSON şeması hatalı")
    geom = tb.get("geometry", {})
    if "type" not in geom:
        raise ValueError("ToolBit geometry.type gerekli")


def scan_toolbits(root: str) -> List[Dict]:
    root = os.path.abspath(root)
    found: List[Dict] = []
    with db_session() as s:
        for fp in glob.glob(os.path.join(root, "**", "*.json"), recursive=True):
            try:
                tb = json.loads(open(fp, "r", encoding="utf-8").read())
                _validate(tb)
                sha = _sha256(fp)
                name = tb.get("name") or os.path.basename(fp)
                ttype = tb.get("geometry", {}).get("type")
                dia = tb.get("geometry", {}).get("diameter")
                exist = s.query(Tool).filter(Tool.sha256 == sha).first()
                if exist:
                    found.append({"id": exist.id, "name": exist.name, "type": exist.type, "diameter_mm": exist.diameter_mm})
                    continue
                tool = Tool(name=name, type=str(ttype), diameter_mm=float(dia) if dia else None, toolbit_json_path=fp, sha256=sha)
                s.add(tool)
                s.commit()
                found.append({"id": tool.id, "name": tool.name, "type": tool.type, "diameter_mm": tool.diameter_mm})
                tool_scan_count_total.inc()
            except Exception:
                continue
    return found
"""


