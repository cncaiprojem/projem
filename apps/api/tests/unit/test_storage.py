from __future__ import annotations

from pathlib import Path

from app.storage import upload_and_sign, presigned_url


class DummyS3:
    def __init__(self):
        self.uploads = []

    def upload_file(self, src, bucket, key, ExtraArgs=None):
        self.uploads.append((src, bucket, key))

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):
        return f"http://minio/{Params['Bucket']}/{Params['Key']}?sig=1"


def test_upload_and_presign(monkeypatch, tmp_path):
    dummy = DummyS3()

    def fake_client():
        return dummy

    monkeypatch.setattr("app.storage.get_s3_client", fake_client)
    path = tmp_path / "a.txt"
    path.write_text("hello")
    art = upload_and_sign(path, "text")
    assert art["s3_key"].startswith("artefacts/")
    assert art["signed_url"].startswith("http://minio/")


def test_presign_missing_env(monkeypatch):
    class Bad:
        def generate_presigned_url(self, *a, **kw):
            raise RuntimeError("no creds")

    monkeypatch.setattr("app.storage.get_s3_client", lambda: Bad())
    assert presigned_url("k") is None
