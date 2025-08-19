from __future__ import annotations

import hashlib
import time

import requests

MAX_FCSTD_MB = 200
READ_CHUNK = 1024 * 1024


class DownloadError(RuntimeError):
    pass


def download_presigned(
    url: str,
    dst_path: str,
    timeout_s: int = 60,
    max_mb: int = MAX_FCSTD_MB,
    sha256: str | None = None,
):
    if not url.lower().endswith(".fcstd"):
        raise DownloadError("Beklenen .FCStd uzantısı.")
    t0 = time.time()
    r = requests.get(url, stream=True, timeout=timeout_s)
    r.raise_for_status()
    size = 0
    hasher = hashlib.sha256()
    with open(dst_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=READ_CHUNK):
            if not chunk:
                break
            f.write(chunk)
            size += len(chunk)
            hasher.update(chunk)
            if size > max_mb * 1024 * 1024:
                raise DownloadError("Dosya boyutu limiti aşıldı.")
    if sha256 and hasher.hexdigest().lower() != sha256.lower():
        raise DownloadError("SHA256 uyuşmuyor.")
    if time.time() - t0 > timeout_s * 2:
        raise DownloadError("İndirme makul sürenin üzerinde.")
    return {"bytes": size, "sha256": hasher.hexdigest()}


