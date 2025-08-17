# LEGACY TEST FILE - DISABLED
# This test file references legacy models not in Task Master ERD
"""
from app.db import db_session
from app.models_project import Setup, Op3D, Project, ProjectType
from app.repos.m18 import add_ops3d, add_collision


def test_add_ops3d_and_collision():
    with db_session() as s:
        proj = Project(name="RepoProj", type=ProjectType.part)
        s.add(proj)
        s.flush()
        st = Setup(project_id=proj.id, name="RepoTest", wcs="G54")
        s.add(st)
        s.commit()
        sid = st.id

    with db_session() as s:
        n = add_ops3d(s, sid, [
            {"op_type": "surface", "params": {"stepover_pct": 30}},
            {"op_type": "adaptive", "params": {"max_stepdown_mm": 2.0}},
        ])
        assert n == 2

    with db_session() as s:
        cnt = s.query(Op3D).filter(Op3D.setup_id == sid).count()
        assert cnt == 2
        cid = add_collision(s, sid, phase="sim", ctype="holder", severity="warn", details={"index": 0})
        assert isinstance(cid, int)
"""


