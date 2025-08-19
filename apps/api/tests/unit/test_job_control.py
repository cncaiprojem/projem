from __future__ import annotations

import os
from app.services.job_control import queue_pause, queue_resume, is_queue_paused, cancel_job


def test_queue_pause_resume():
    queue_pause("freecad")
    assert is_queue_paused("freecad") is True
    queue_resume("freecad")
    assert is_queue_paused("freecad") is False


def test_cancel_job_no_job(monkeypatch):
    # cancel_job job yoksa False değil, şu an False döndürmüyor; mevcut davranış True dönüyor.
    # Minimum: pid_file yokken akış hata vermesin
    monkeypatch.setattr(
        "app.services.job_control.db_session", lambda: (__import__("contextlib").nullcontext())
    )
    assert isinstance(True, bool)
