from __future__ import annotations

from celery import shared_task

from ..freecad.service import detect_freecad


@shared_task(name="freecad.detect", queue="freecad")
def freecad_detect_task() -> dict:
    res = detect_freecad()
    return res.model_dump()
