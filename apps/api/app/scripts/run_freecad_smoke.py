from __future__ import annotations

import requests

from app.db import db_session
from app.models_project import Project, Setup, ProjectType


def main():
    base = "http://localhost:8000"
    with db_session() as s:
        p = Project(name="Smoke", type=ProjectType.part)
        s.add(p)
        s.commit()
        pid = p.id
        s.add(Setup(project_id=pid, name="Top", wcs="G54"))
        s.commit()
        sid = s.query(Setup.id).filter_by(project_id=pid).first()[0]
    print("CAM", requests.post(f"{base}/api/v1/setups/{sid}/cam").status_code)
    print("SIM", requests.post(f"{base}/api/v1/setups/{sid}/simulate").status_code)


if __name__ == "__main__":  # pragma: no cover
    main()
