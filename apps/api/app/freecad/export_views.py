from __future__ import annotations

import os
import subprocess
import tempfile


def _run_fc_script(fcstd_path: str, out_dir: str) -> dict[str, str]:
    """FreeCADCmd içinde minimal Part projection → SVG (front/right/iso)."""
    script = f"""
import FreeCAD as App
import Import
import Part
import os

doc = App.openDocument(r"{fcstd_path}")
App.ActiveDocument=doc
obj = None
for o in doc.Objects:
    if hasattr(o, 'Shape') and o.Shape:
        obj = o
        break
if obj is None:
    print('NO_SHAPE')
    raise SystemExit(0)

def export_view(vec, name):
    shp = obj.Shape
    proj = shp.makeParallelProjection(vec)
    fp = os.path.join(r"{out_dir}", f"{name}.svg")
    Part.export([proj], fp)
    print('EXPORTED', fp)

export_view(App.Vector(0,0,1), 'front')
export_view(App.Vector(1,0,0), 'right')
export_view(App.Vector(1,1,1), 'iso')
doc.close()
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        tmp = f.name
    try:
        from ..freecad.service import find_freecadcmd_path  # type: ignore
    except Exception:
        from .service import find_freecadcmd_path  # type: ignore
    fc = find_freecadcmd_path()
    if not fc:
        return {"front": "", "right": "", "iso": ""}
    subprocess.run([fc, tmp], check=False)
    return {"front": os.path.join(out_dir, "front.svg"), "right": os.path.join(out_dir, "right.svg"), "iso": os.path.join(out_dir, "iso.svg")}


def project_views(fcstd_path: str, out_dir: str) -> dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    try:
        return _run_fc_script(fcstd_path, out_dir)
    except Exception:
        return {"front": "", "right": "", "iso": ""}


