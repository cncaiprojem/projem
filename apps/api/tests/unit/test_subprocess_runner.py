from __future__ import annotations

import platform
from app.freecad.subprocess_runner import run_subprocess_with_timeout


def test_run_subprocess_timeout():
    # Çok kısa timeout ile uyuyan komutu öldürelim
    if platform.system().lower() == "windows":
        cmd = ["powershell", "-Command", "Start-Sleep", "5"]
    else:
        cmd = ["sh", "-lc", "sleep 5"]
    res = run_subprocess_with_timeout(cmd, timeout_seconds=1)
    assert res.timed_out is True


def test_run_subprocess_ok():
    if platform.system().lower() == "windows":
        cmd = ["cmd", "/c", "exit", "0"]
    else:
        cmd = ["sh", "-lc", "exit 0"]
    res = run_subprocess_with_timeout(cmd, timeout_seconds=2)
    assert res.returncode == 0
