from __future__ import annotations

import os
import hashlib
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass
class BuildParams:
    width: float
    height: float
    thickness: float
    holes: Tuple[Tuple[float, float, float], ...] = ()
    chamfer_mm: float | None = None
    fillet_mm: float | None = None
    material: str | None = None


def parse_plan_to_params(plan: Dict[str, Any]) -> BuildParams:
    cad = plan.get("cad", {})
    size = cad.get("size", {"x": 90, "y": 60, "z": 8})
    width = float(size.get("x", 90))
    height = float(size.get("y", 60))
    thick = float(size.get("z", 8))
    holes = []
    for h in cad.get("holes", []):
        holes.append((float(h.get("x", 0)), float(h.get("y", 0)), float(h.get("d", 5))))
    chamfer = cad.get("chamfer_mm")
    fillet = cad.get("fillet_mm")
    mat = plan.get("material") or plan.get("answers", {}).get("malzeme")
    return BuildParams(width, height, thick, tuple(holes), chamfer, fillet, mat)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_fcstd(params: BuildParams, out_dir: str) -> Dict[str, str]:
    # FreeCAD importları fonksiyon içine alındı (ortam yoksa import hatası almamak için)
    import FreeCAD as App  # type: ignore
    import Part  # type: ignore

    doc = App.newDocument("Model")
    try:
        box = doc.addObject("Part::Box", "Plate")
        box.Length = params.width
        box.Width = params.height
        box.Height = params.thickness
        box.Placement = App.Placement(App.Vector(0, 0, 0), App.Rotation(0, 0, 0, 1))
        base = box
        doc.recompute()

        for x, y, d in params.holes:
            cyl = doc.addObject("Part::Cylinder", f"Hole_{x}_{y}")
            cyl.Radius = d / 2.0
            cyl.Height = params.thickness + 1.0
            cyl.Placement = App.Placement(App.Vector(x, y, -0.5), App.Rotation(0, 0, 0, 1))
            doc.recompute()
            cut = doc.addObject("Part::Cut", f"Cut_{x}_{y}")
            cut.Base = base
            cut.Tool = cyl
            doc.recompute()
            base = cut

        if params.chamfer_mm:
            ch = doc.addObject("Part::Chamfer", "Chamfer")
            ch.Base = base
            edges = [
                (f"Edge{i + 1}", float(params.chamfer_mm)) for i in range(len(base.Shape.Edges))
            ]
            ch.Edges = edges
            doc.recompute()
            base = ch

        if params.fillet_mm:
            fl = doc.addObject("Part::Fillet", "Fillet")
            fl.Base = base
            edges = [
                (f"Edge{i + 1}", float(params.fillet_mm)) for i in range(len(base.Shape.Edges))
            ]
            fl.Edges = edges
            doc.recompute()
            base = fl

        fcstd_path = os.path.join(out_dir, "model.fcstd")
        step_path = os.path.join(out_dir, "model.step")
        stl_path = os.path.join(out_dir, "model.stl")
        gltf_path = os.path.join(out_dir, "model.gltf")

        doc.saveAs(fcstd_path)
        shape = base.Shape
        shape.exportStep(step_path)
        shape.exportStl(stl_path)

        try:
            import trimesh  # type: ignore

            m = trimesh.load(stl_path)
            m.export(gltf_path)
        except Exception:
            gltf_path = ""

        return {"fcstd": fcstd_path, "step": step_path, "stl": stl_path, "gltf": gltf_path}
    finally:
        App.closeDocument(doc.Name)  # type: ignore


def validate_fcstd(fcstd_path: str) -> Dict[str, Any]:
    import FreeCAD as App  # type: ignore

    doc = App.openDocument(fcstd_path)
    try:
        doc.recompute()
        solids = sum(1 for o in doc.Objects if hasattr(o, "Shape") and o.Shape.Solids)
        volume = 0.0
        for o in doc.Objects:
            if hasattr(o, "Shape") and o.Shape.Solids:
                try:
                    volume += float(o.Shape.Volume)
                except Exception:
                    pass
        ok = solids > 0 and volume > 0.0
        return {"ok": ok, "solids": solids, "volume": volume}
    finally:
        App.closeDocument(doc.Name)  # type: ignore


def build_from_plan(plan: Dict[str, Any], out_dir: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    params = parse_plan_to_params(plan)
    paths = build_fcstd(params, out_dir)
    stats = validate_fcstd(paths["fcstd"])
    return paths, stats
