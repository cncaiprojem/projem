import pytest
from app.schemas.m18 import SetupCreate, Op3DPlan


def test_setup_create_defaults():
    s = SetupCreate(project_id=1, name="Top")
    assert s.wcs == "G54"
    assert s.orientation_rx_deg == 0


def test_op3dplan_requires_ops():
    with pytest.raises(Exception):
        Op3DPlan(ops=None)  # type: ignore
    p = Op3DPlan(ops=[{"op_type": "surface", "params": {}}])
    assert p.ops and p.ops[0]["op_type"] == "surface"
