from __future__ import annotations

import json
import os
from typing import Any


def _ensure_mm():
    try:
        from FreeCAD import Units  # type: ignore

        Units.setSchema("Metric-mm")
    except Exception:
        pass


def _mk_toolbit(tmpdir: str, tool: dict[str, Any]) -> str:
    ttype = tool["type"]
    dia = float(tool.get("dia", 6.0))
    tb = {
        "version": 2,
        "name": f"{ttype}_{dia}mm",
        "description": ttype,
        "geometry": {"type": ttype, "diameter": dia},
    }
    fp = os.path.join(tmpdir, f"tb_{ttype}_{dia}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(tb, f)
    return fp


def _mk_tc(doc, toolbit_path: str, rpm: int, feed: float, plunge: float):
    from PathScripts import PathToolBit, PathToolController  # type: ignore

    tb = PathToolBit.Load(toolbit_path)
    tc = PathToolController.Create(doc, tb)
    tc.SpindleSpeed = rpm
    tc.FeedRate = feed
    tc.VerticalFeedRate = plunge
    return tc


def _add_face(doc, job, base, tc, params):
    from PathScripts import PathFace  # type: ignore

    op = PathFace.Create("Face", job)
    op.setEditorProperty("Base", [(base, ("Face1",))])
    op.setEditorProperty("ToolController", tc)
    op.setExpression("StepOver", f'{float(params.get("stepover", 60))} %')
    op.setExpression("StepDown", f'{float(params.get("stepdown", 1.0))} mm')
    doc.recompute()
    return op


def _add_contour(doc, job, base, tc, params):
    from PathScripts import PathProfile  # type: ignore

    op = PathProfile.Create("Profile", job)
    op.setEditorProperty("Base", [(base, ("Face1",))])
    op.setEditorProperty("ToolController", tc)
    op.setEditorProperty("Side", params.get("side", "Outside").capitalize())
    op.setExpression("StepDown", f'{float(params.get("depth_per_pass", 1.5))} mm')
    op.setEditorProperty("FinishDepth", float(params.get("finish_pass", True)))
    doc.recompute()
    return op


def _add_drill(doc, job, base, tc, params):
    from PathScripts import PathDrilling  # type: ignore

    op = PathDrilling.Create("Drill", job)
    op.setEditorProperty("Base", [(base, ("Face1",))])
    op.setEditorProperty("ToolController", tc)
    peck = float(params.get("peck", 0.0))
    if peck > 0:
        op.setEditorProperty("PeckDepth", peck)
    doc.recompute()
    return op


def _add_chamfer(doc, job, base, tc, params):
    from PathScripts import PathChamfer  # type: ignore

    op = PathChamfer.Create("Chamfer", job)
    op.setEditorProperty("Base", [(base, ("Face1",))])
    op.setEditorProperty("ToolController", tc)
    op.setEditorProperty("Width", float(params.get("width", 0.5)))
    doc.recompute()
    return op


def build_cam_job(fcstd_path: str, cam: dict[str, Any], stock: dict[str, Any], wcs: str, post_name: str | None, tmpdir: str, db=None):
    _ensure_mm()
    import FreeCAD as App  # type: ignore
    from PathScripts import PathJob  # type: ignore

    doc = App.openDocument(fcstd_path)
    try:
        doc.recompute()
        base = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape and o.Name][-1]
        job = PathJob.Create("Job", [base], None)
        if post_name:
            job.PostProcessor = post_name
        if stock.get("shape", "block") == "block":
            job.Stock.ExtX = float(stock.get("x_mm", 100))
            job.Stock.ExtY = float(stock.get("y_mm", 70))
            job.Stock.ExtZ = float(stock.get("z_mm", 10))
            job.Stock.Type = "Extend"
        job.SetupSheet.setEditorProperty("Output", "GCode")
        job.SetupSheet.setEditorProperty("WCS", wcs)

        ops_summary = []
        for op in cam.get("ops", []):
            tool = op["tool"]
            tb = _mk_toolbit(tmpdir, tool)
            if db is not None:
                try:
                    from ..services.cutting import pick_cut  # type: ignore

                    dia = float(tool.get("dia", 6.0))
                    cut = pick_cut(db, cam.get("material", "Al6061"), tool.get("type", "endmill_flat"), dia, op.get("type", ""))
                    feeds = {"rpm": cut["rpm"], "feed": cut["feed"], "plunge": cut["plunge"]}
                except Exception:
                    feeds = {"rpm": 10000, "feed": 600, "plunge": 150}
            else:
                feeds = {"rpm": 10000, "feed": 600, "plunge": 150}
            tc = _mk_tc(doc, tb, feeds["rpm"], feeds["feed"], feeds["plunge"])
            t = op["type"]
            if t == "face":
                created = _add_face(doc, job, base, tc, op["params"])
            elif t == "contour":
                created = _add_contour(doc, job, base, tc, op["params"])
            elif t == "drill":
                created = _add_drill(doc, job, base, tc, op["params"])
            elif t == "chamfer":
                created = _add_chamfer(doc, job, base, tc, op["params"])
            else:
                continue
            ops_summary.append({"name": created.Label, "type": t, "est_seconds": 0.0})

        doc.recompute()
        doc.save()
        # basit özet json
        jpath = os.path.join(tmpdir, "job_summary.json")
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump({"ops": ops_summary, "wcs": wcs, "stock": stock}, f, ensure_ascii=False, indent=2)
        return {"ops": ops_summary, "job_json": jpath, "svg": ""}
    finally:
        App.closeDocument(doc.Name)


