from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .subprocess_runner import run_subprocess_with_timeout


def build_cam_script(params: dict) -> str:
    return """
import os, json, App, Path
from PathScripts import PathJob, PathToolController, PathPostProcessor

fcstd = os.environ.get('FCSTD_PATH')
gcode_out = os.environ.get('GCODE_OUT')
post_name = os.environ.get('POST_NAME')
params = json.loads(os.environ.get('CAM_PARAMS_JSON','{}'))
if not fcstd or not gcode_out or not post_name:
    raise RuntimeError('Giriş eksik')

doc = App.openDocument(fcstd)
obj = App.ActiveDocument

# Stock basit: model bbox + margin
margin = float(params.get('stock_margin_mm', 2.0))
bbox = obj.getObject(obj.Objects[0].Name).Shape.BoundBox if obj.Objects else None
if not bbox:
    raise RuntimeError('Model BoundBox bulunamadı')

stock = App.ActiveDocument.addObject('Part::Box','Stock')
stock.Length = bbox.XLength + 2*margin
stock.Width  = bbox.YLength + 2*margin
stock.Height = bbox.ZLength + 2*margin
stock.Placement.Base.x = bbox.XMin - margin
stock.Placement.Base.y = bbox.YMin - margin
stock.Placement.Base.z = bbox.ZMin - margin

job = PathJob.Create('Job', [o for o in obj.Objects if hasattr(o,'Shape')], stock=stock)
tc = PathToolController.Create('TC')
tc.setExpression('Tool.Diameter', None)
job.Proxy.addToolController(job, tc)

# Basit operasyon: Profile
from PathScripts import PathProfile
prof = PathProfile.Create('Profile', job)
prof.setEditorProperty('Active', True)

App.ActiveDocument.recompute()

pp = PathPostProcessor.PostProcessor.load(post_name)
code = pp.export(job, gcode_out)

print('GCODE_OUT=' + gcode_out)
"""


def make_path_job(freecad_path: str, fcstd_path: Path, params: dict, post_name: str, timeout: int) -> tuple[Path, dict]:
    tmp_script = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
    tmp_script.write(build_cam_script(params).encode("utf-8"))
    tmp_script.close()
    env = os.environ.copy()
    gcode_out = fcstd_path.with_suffix('.gcode')
    env['FCSTD_PATH'] = str(fcstd_path)
    env['GCODE_OUT'] = str(gcode_out)
    env['POST_NAME'] = post_name
    import json as _json
    env['CAM_PARAMS_JSON'] = _json.dumps(params)
    res = run_subprocess_with_timeout([freecad_path, tmp_script.name], timeout_seconds=timeout, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"FreeCAD Path hatası: {res.stderr}")
    return gcode_out, {"elapsed_ms": res.elapsed_ms}


