from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    openapi = app.openapi()
    out_dir = Path("/app_docs")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "openapi.json").write_text(
        json.dumps(openapi, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("OpenAPI üretildi:", out_dir / "openapi.json")


if __name__ == "__main__":
    main()
