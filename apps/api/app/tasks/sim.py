from __future__ import annotations

import io
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from billiard.exceptions import SoftTimeLimitExceeded
from opentelemetry import trace
from pygltflib import GLTF2, Accessor, Buffer, BufferView, Mesh, Node, Scene

from ..audit import audit
from ..config import settings
from ..db import db_session
from ..logging_setup import get_logger
from ..metrics import failures_total, job_latency_seconds, queue_wait_seconds, retried_total
from ..models import Job
from ..services.dlq import push_dead
from ..settings import app_settings as appset
from ..storage import get_s3_client, upload_and_sign
from .worker import celery_app

logger = get_logger(__name__)


def load_inputs(assembly_job_id: int, gcode_job_id: int | None) -> tuple[Path, str]:
    with db_session() as s:
        asm = s.get(Job, assembly_job_id)
        if not asm or not asm.artefacts:
            raise RuntimeError("Assembly işinin artefaktı bulunamadı")
        fcstd_key = asm.artefacts[0].get("s3_key")
        if not fcstd_key:
            raise RuntimeError("FCStd s3_key eksik")
        gcode_txt = None
        if gcode_job_id:
            gj = s.get(Job, gcode_job_id)
            if not gj or not gj.artefacts:
                raise RuntimeError("G-code artefaktı bulunamadı")
            gk = gj.artefacts[0].get("s3_key")
            if not gk:
                raise RuntimeError("G-code s3_key eksik")
            s3 = get_s3_client()
            bio = io.BytesIO()
            s3.download_fileobj(settings.s3_bucket_name, gk, bio)
            bio.seek(0)
            gcode_txt = bio.read().decode("utf-8", "ignore")
        s3 = get_s3_client()
        tmp_dir = Path("/tmp/sim")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fcstd_path = tmp_dir / "assembly.fcstd"
        s3.download_file(settings.s3_bucket_name, fcstd_key, str(fcstd_path))
        return fcstd_path, gcode_txt or ""


def parse_gcode_basic(text: str):
    moves = []
    units = 'mm'
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln: continue
        if ln.startswith('G21'): units = 'mm'
        if ln.startswith('G20'): units = 'inch'
        if ln.startswith('G0') or ln.startswith('G1'):
            def num(tag):
                import re
                m = re.search(fr"\b{tag}(-?\d+(?:\.\d+)?)\b", ln, re.I)
                return float(m.group(1)) if m else None
            moves.append({
                'type': 'G0' if ln.startswith('G0') else 'G1',
                'x': num('X'), 'y': num('Y'), 'z': num('Z'), 'f': num('F')
            })
    return moves, units


def carve_voxels(moves, bounds: dict[str, tuple[float, float]], res_mm: float, tool_diam_mm: float):
    nx = int((bounds['x'][1] - bounds['x'][0]) / res_mm) + 1
    ny = int((bounds['y'][1] - bounds['y'][0]) / res_mm) + 1
    nz = int((bounds['z'][1] - bounds['z'][0]) / res_mm) + 1
    vox = np.ones((nx, ny, nz), dtype=np.uint8)
    carved = 0
    last = [0.0, 0.0, 0.0]
    radius = tool_diam_mm / 2.0
    for i, mv in enumerate(moves):
        x = mv.get('x', last[0]); y = mv.get('y', last[1]); z = mv.get('z', last[2])
        # kaba: nokta çevresinde silindir çapında carving
        ix = int((x - bounds['x'][0]) / res_mm)
        iy = int((y - bounds['y'][0]) / res_mm)
        iz = int((z - bounds['z'][0]) / res_mm)
        r = max(1, int(radius / res_mm))
        x0, x1 = max(0, ix - r), min(nx - 1, ix + r)
        y0, y1 = max(0, iy - r), min(ny - 1, iy + r)
        z0, z1 = max(0, iz - r), min(nz - 1, iz + r)
        for xi in range(x0, x1 + 1):
            for yi in range(y0, y1 + 1):
                for zi in range(z0, z1 + 1):
                    if vox[xi, yi, zi]:
                        vox[xi, yi, zi] = 0
                        carved += 1
        last = [x, y, z]
    return vox, carved


def marching_cubes_to_gltf(vox: np.ndarray, res_mm: float, out_path: Path):
    # Yerel import: binary uyumsuzluk riskini minimize etmek için yalnızca ihtiyaç anında yükle
    import mcubes
    verts, tris = mcubes.marching_cubes(vox.astype(np.float32), 0.5)
    verts *= res_mm
    vertices = verts.astype(np.float32).tobytes()
    indices = tris.astype(np.uint32).tobytes()

    gltf = GLTF2()
    gltf.scene = 0
    gltf.scenes = [Scene(nodes=[0])]

    # Buffers
    buffer = Buffer(byteLength=len(vertices) + len(indices))
    gltf.buffers = [buffer]
    gltf.bufferViews = [
        BufferView(buffer=0, byteOffset=0, byteLength=len(vertices), target=34962),
        BufferView(buffer=0, byteOffset=len(vertices), byteLength=len(indices), target=34963),
    ]
    gltf.accessors = [
        Accessor(bufferView=0, byteOffset=0, componentType=5126, count=len(verts), type="VEC3"),
        Accessor(bufferView=1, byteOffset=0, componentType=5125, count=len(tris) * 3, type="SCALAR"),
    ]
    gltf.meshes = [Mesh(primitives=[{"attributes": {"POSITION": 0}, "indices": 1}])]
    gltf.nodes = [Node(mesh=0)]

    # Bin dosya yaz
    bin_path = out_path.with_suffix('.bin')
    with open(bin_path, 'wb') as fb:
        fb.write(vertices + indices)
    gltf.buffers[0].uri = bin_path.name
    gltf.save(str(out_path))


@celery_app.task(
    bind=True,
    name="sim.generate",
    queue="sim",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=appset.task_soft_limits.get("sim", 1140),
    time_limit=appset.task_time_limits.get("sim", 1200),
)
def sim_generate(self, job_id: int) -> dict:
    start = time.time()
    with db_session() as s:
        job = s.get(Job, job_id)
        if not job:
            return {"error": "job yok"}
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.task_id = self.request.id
        params: dict = job.metrics.get("params", {}) if job.metrics else {}
        s.commit()

    asm_id = params.get('assembly_job_id')
    gcode_job_id = params.get('gcode_job_id')
    res_mm = float(params.get('resolution_mm', 0.8))
    bounds = params.get('bounds') or {"x": [0, 300], "y": [0, 300], "z": [-50, 150]}
    tool_diam = 6.0

    try:
        fcstd_path, gcode_txt = load_inputs(asm_id, gcode_job_id)
        moves, units = parse_gcode_basic(gcode_txt)
        if units == 'inch':
            for mv in moves:
                for k in ('x','y','z','f'):
                    if mv.get(k) is not None:
                        mv[k] *= 25.4
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("sim.carve") as span:
            vox, carved = carve_voxels(moves, bounds, res_mm, tool_diam)
            span.set_attribute("job_id", job_id)
            span.set_attribute("type", "sim")
        out = Path('/tmp/sim/result.gltf')
        out.parent.mkdir(parents=True, exist_ok=True)
        with tracer.start_as_current_span("sim.meshing") as span:
            marching_cubes_to_gltf(vox, res_mm, out)
            span.set_attribute("job_id", job_id)
            span.set_attribute("type", "sim")
        art = upload_and_sign(out, 'sim-mesh')
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = 'succeeded'
            job.finished_at = datetime.utcnow()
            job.metrics = {**(job.metrics or {}), 'voxel_resolution_mm': res_mm, 'carved_voxels': int(carved), 'elapsed_ms': int((time.time()-start)*1000)}
            job.artefacts = [{"type": art["type"], "s3_key": art["s3_key"], "size": art["size"], "sha256": art["sha256"]}]
            s.commit()
        if job.started_at and job.finished_at:
            job_latency_seconds.labels(type="sim", status="succeeded").observe((job.finished_at - job.started_at).total_seconds())
        if job.started_at and (job.metrics or {}).get("created_at"):
            try:
                created = datetime.fromisoformat(job.metrics["created_at"]).replace(tzinfo=None)
                queue_wait_seconds.labels(queue=(job.metrics or {}).get("queue", "sim")).observe((job.started_at - created).total_seconds())
            except Exception:
                ...
        audit("task.success", job_id=job_id, task="sim.generate")
        return {"ok": True}
    except SoftTimeLimitExceeded:
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = 'failed'
            job.finished_at = datetime.utcnow()
            job.error_message = 'Zaman sınırı aşıldı'
            s.commit()
        push_dead(job_id, 'sim.generate', 'time_limit')
        failures_total.labels(task='sim.generate', reason='time_limit').inc()
        audit('task.time_limit_hit', job_id=job_id, task='sim.generate')
        if self.request.retries < self.request.max_retries:
            retried_total.labels(task='sim.generate').inc()
        raise
    except Exception as e:
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = 'failed'
            job.finished_at = datetime.utcnow()
            job.error_message = str(e)
            s.commit()
        push_dead(job_id, "sim.generate", str(e))
        failures_total.labels(task='sim.generate', reason=type(e).__name__).inc()
        audit("dlq.push", job_id=job_id, task="sim.generate", reason=str(e))
        if getattr(self.request, "retries", 0) < getattr(self.request, "max_retries", 0):
            retried_total.labels(task='sim.generate').inc()
        raise


