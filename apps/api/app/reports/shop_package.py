from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import qrcode
from cairosvg import svg2png
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..config import settings
from ..db import db_session
from ..freecad.export_views import project_views
from ..metrics import report_build_duration_seconds
from ..models_project import FileKind, Project, ProjectFile
from ..storage import get_s3_client, presigned_url
from ..storage_download import download_presigned


@dataclass
class PackageMeta:
    pages: int
    sha256: str
    bytes: int


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_shop_package_pdf(project_id: int, out_pdf_path: str) -> dict:
    # Basit PDF iskeleti; görsel/tablolar için sonraki iterasyon
    from time import perf_counter

    t0 = perf_counter()
    p = Path(out_pdf_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(p), pagesize=A4)
    w, h = A4
    # Kapak + başlık
    title = f"{settings.brand_name} — Atölye Paketi"
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, h - 30 * mm, title)
    c.setFont("Helvetica", 12)
    c.drawString(20 * mm, h - 40 * mm, f"Proje #{project_id}")
    # QR (varsa)
    if settings.public_web_base_url:
        url = f"{settings.public_web_base_url}/viewer?projectId={project_id}"
        qr = qrcode.QRCode(version=2, box_size=4, border=1)
        qr.add_data(url); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        c.drawImage(ImageReader(buf), w - 50 * mm, h - 70 * mm, width=30 * mm, height=30 * mm, mask='auto')
        c.setFont("Helvetica", 8)
        c.drawRightString(w - 20 * mm, h - 75 * mm, url)
    # İçindekiler
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 60 * mm, "İçindekiler")
    c.setFont("Helvetica", 10)
    y = h - 70 * mm
    for line in ["1. Kapak", "2. Görünüşler", "3. WCS / Stock", "4. Operasyonlar", "5. Güvenlik Notları"]:
        c.drawString(25 * mm, y, line)
        y -= 6 * mm
    c.showPage()

    # FCStd indir → SVG→PNG görünüşler
    front_png = right_png = iso_png = None
    summary = {}; stock = {}; wcs = "G54"; ops = []
    with db_session() as s:
        p = s.get(Project, project_id)
        if p and p.summary_json:
            summary = dict(p.summary_json)
            cam_job = summary.get("cam_job") or {}
            if isinstance(cam_job, dict):
                stock = cam_job.get("stock") or {}
                wcs = cam_job.get("wcs") or wcs
                ops = cam_job.get("ops") or []
        pf = (
            s.query(ProjectFile)
            .filter(ProjectFile.project_id == project_id, ProjectFile.kind == FileKind.cad)
            .order_by(ProjectFile.created_at.desc())
            .first()
        )
        if pf and pf.s3_key and pf.s3_key.endswith('.fcstd'):
            tmpd = Path(out_pdf_path).parent / f"pkg_{project_id}"
            tmpd.mkdir(parents=True, exist_ok=True)
            fcstd_local = tmpd / 'model.fcstd'
            url = presigned_url(pf.s3_key)
            if url:
                download_presigned(url, str(fcstd_local))
            else:
                get_s3_client().download_file(settings.s3_bucket_name, pf.s3_key, str(fcstd_local))
            views = project_views(str(fcstd_local), str(tmpd))
            for name in ("front", "right", "iso"):
                svgp = tmpd / f"{name}.svg"
                if svgp.exists():
                    pngp = tmpd / f"{name}.png"
                    try:
                        svg2png(url=str(svgp), write_to=str(pngp), dpi=200)
                        if name == 'front': front_png = pngp
                        if name == 'right': right_png = pngp
                        if name == 'iso': iso_png = pngp
                    except Exception:
                        pass

    # Görünüşler sayfası
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 30 * mm, "Görünüşler")
    y_img = h - 50 * mm
    for img in (front_png, right_png, iso_png):
        if img and Path(img).exists():
            try:
                c.drawImage(str(img), 20 * mm, y_img - 40 * mm, width=60 * mm, height=40 * mm, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        y_img -= 45 * mm
    c.showPage()

    # WCS/Stock sayfası
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 30 * mm, "WCS / Stock")
    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, h - 40 * mm, f"WCS: {wcs}")
    sx = stock.get('x_mm') or stock.get('x') or '-'
    sy = stock.get('y_mm') or stock.get('y') or '-'
    sz = stock.get('z_mm') or stock.get('z') or '-'
    c.drawString(25 * mm, h - 48 * mm, f"Stock: X={sx} mm, Y={sy} mm, Z={sz} mm")
    c.showPage()

    # Operasyonlar
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 30 * mm, "Operasyonlar")
    c.setFont("Helvetica", 10)
    y_op = h - 40 * mm
    if ops:
        for op in ops:
            t = op.get('type', '?')
            tool = op.get('tool') or {}
            tt = tool.get('type', '?'); dia = tool.get('dia', '?')
            c.drawString(25 * mm, y_op, f"- {t} | Takım: {tt} ⌀{dia} mm")
            y_op -= 6 * mm
            if y_op < 30 * mm:
                c.showPage(); c.setFont("Helvetica", 10); y_op = h - 30 * mm
    else:
        c.drawString(25 * mm, y_op, "Operasyon verisi yok")
        c.showPage()
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 30 * mm, "Güvenlik Notları")
    c.setFont("Helvetica", 10)
    notes = [
        "- Üretim öncesi kuru koşu (dry-run) zorunlu.",
        "- PPE: Gözlük, eldiven, kulaklık kullanın.",
        "- Sıkıştırma ve stock kollizyon kontrolü yapılmalıdır.",
    ]
    yy = h - 40 * mm
    for n in notes:
        c.drawString(25 * mm, yy, n)
        yy -= 6 * mm
    c.showPage()
    c.save()
    size = p.stat().st_size
    if size > (int(settings.pdf_max_mb or 20) * 1024 * 1024):
        raise RuntimeError("PDF boyutu limitini aşıyor")
    sha = _sha256(p)
    report_build_duration_seconds.labels(status="ok").observe(perf_counter() - t0)
    return {"pages": 1, "sha256": sha, "bytes": size, "path": str(p)}


