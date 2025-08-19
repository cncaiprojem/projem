from __future__ import annotations

import os
import platform
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Dict


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: int
    timed_out: bool


def _kill_tree(pid: int) -> None:
    system = platform.system().lower()
    if system == "windows":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            pass


def run_subprocess_with_timeout(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout_seconds: int = 60,
    env: Optional[Dict[str, str]] = None,
    pid_file: Optional[str] = None,
) -> RunResult:
    system = platform.system().lower()
    start = time.time()
    preexec_fn = os.setsid if system != "windows" else None
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if system == "windows" else 0

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        preexec_fn=preexec_fn,  # type: ignore[arg-type]
        creationflags=creationflags,
    )
    try:
        if pid_file:
            with open(pid_file, "w", encoding="utf-8") as f:
                f.write(str(process.pid))
    except Exception:
        pass
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        elapsed_ms = int((time.time() - start) * 1000)
        if pid_file:
            try:
                os.remove(pid_file)
            except Exception:
                pass
        return RunResult(
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_ms=elapsed_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        _kill_tree(process.pid)
        stdout, stderr = "", "Zaman aşımı"
        elapsed_ms = int((time.time() - start) * 1000)
        if pid_file:
            try:
                os.remove(pid_file)
            except Exception:
                pass
        return RunResult(
            returncode=-9, stdout=stdout, stderr=stderr, elapsed_ms=elapsed_ms, timed_out=True
        )
