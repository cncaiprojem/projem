# LEGACY SEED SCRIPT - DISABLED
# This script uses legacy models not in Task Master ERD
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..db import db_session
from ..models_tooling import Tool, Holder
from ..models_cutting import CuttingData
from ..models_project import Fixture
"""

import json
from pathlib import Path
from typing import Any, Dict


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def seed_tools(fixtures_dir: Path):
    tools_json = fixtures_dir / "tools.json"
    if not tools_json.exists():
        return
    data = _load_json(tools_json)
    with db_session() as s:
        for t in data:
            if s.query(Tool).filter_by(name=t["name"]).first():
                continue
            s.add(Tool(
                name=t["name"], type=t["type"], diameter_mm=t.get("diameter_mm"), flute_count=t.get("flute_count"),
                toolbit_json_path=t.get("toolbit_ref")
            ))
        s.commit()


def seed_fixtures(fixtures_dir: Path):
    fj = fixtures_dir / "fixtures.json"
    if not fj.exists():
        return
    data = _load_json(fj)
    with db_session() as s:
        for f in data:
            if s.query(Fixture).filter_by(name=f["name"]).first():
                continue
            s.add(Fixture(
                name=f["name"], type=f["type"], safety_clear_mm=f.get("safety_clear_mm", 10),
                jaw_open_mm=f.get("jaw_open_mm"), clamp_height_mm=f.get("clamp_height_mm")
            ))
        s.commit()


def main():
    root = Path(__file__).resolve().parents[3] / "apps" / "api" / "fixtures"
    seed_tools(root)
    seed_fixtures(root)
    # minimal cutting data örnekleri
    cut_path = root / "cutting_data.json"
    if cut_path.exists():
        data = _load_json(cut_path)
        with db_session() as s:
            for r in data:
                exists = s.query(CuttingData).filter_by(
                    material=r["material"], tool_type=r["tool_type"], operation=r["operation"],
                    tool_dia_min_mm=r["tool_diameter_range"][0], tool_dia_max_mm=r["tool_diameter_range"][1]
                ).first()
                if exists:
                    continue
                # basit rpm/feed hesap (vc ve fz verilmişse)
                rpm = int((r.get("vc_m_min", 300) * 1000) / (3.1416 * max(1.0, r["tool_diameter_range"][0])))
                feed = float(r.get("fz_mm_tooth", 0.04)) * 2 * rpm
                s.add(CuttingData(
                    material=r["material"], tool_type=r["tool_type"], operation=r["operation"],
                    tool_dia_min_mm=r["tool_diameter_range"][0], tool_dia_max_mm=r["tool_diameter_range"][1],
                    rpm=rpm, feed_mm_min=feed, plunge_mm_min=feed/4,
                    stepdown_mm=float(r.get("ap_mm", 1.0)), stepover_pct=float(r.get("ae_mm", 1.0))
                ))
            s.commit()
    print("Seed tamamlandı")


if __name__ == "__main__":
    main()


