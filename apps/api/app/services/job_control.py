from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional

from ..db import db_session
from ..models import Job
from ..tasks.worker import celery_app
from ..audit import audit


def _kill_tree_by_pid(pid: int) -> None:
    system = platform.system().lower()
    if system == "windows":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(pid, 9)
        except Exception:
            pass


def cancel_job(job_id: int) -> bool:
    with db_session() as s:
        job = s.get(Job, job_id)
        if not job:
            return False
        if job.task_id:
            try:
                celery_app.control.revoke(job.task_id, terminate=True)
            except Exception:
                pass
        # pid_file konvansiyonu: /tmp/<task_id>.pid
        pid_file = f"/tmp/{job.task_id}.pid" if job.task_id else None
        if pid_file and os.path.exists(pid_file):
            try:
                pid = int(open(pid_file).read().strip())
                _kill_tree_by_pid(pid)
                os.remove(pid_file)
            except Exception:
                pass
        job.status = "failed"
        job.error_code = "CANCELLED"
        job.error_message = "İş kullanıcı tarafından iptal edildi"
        s.commit()
    audit("job.cancel", job_id=job_id, task_id=(job.task_id if "job" in locals() and job else None))
    return True


_paused_queues: set[str] = set()


def queue_pause(name: str) -> None:
    _paused_queues.add(name)
    audit("queue.pause", queue=name)


def queue_resume(name: str) -> None:
    _paused_queues.discard(name)
    audit("queue.resume", queue=name)


def is_queue_paused(name: str) -> bool:
    return name in _paused_queues
