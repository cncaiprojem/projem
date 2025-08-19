from __future__ import annotations

import pytest

from app.schemas.cad import AssemblyRequestV1, PlanetarySpec, GearStage
from app.schemas.cam import CamJobCreate
from app.schemas.sim import SimJobCreate


def test_assembly_schema_valid():
    req = AssemblyRequestV1(
        type="planetary_gearbox",
        spec=PlanetarySpec(
            stages=[GearStage(ratio=3.0)],
            overall_ratio=3.0,
            power_kW=1.0,
            materials={"gear": "steel", "housing": "aluminum"},
            outputs={"torqueNm": 10, "radialN": 10, "axialN": 5},
        ),
    )
    assert req.type == "planetary_gearbox"


def test_assembly_schema_invalid_type():
    with pytest.raises(Exception):
        AssemblyRequestV1(
            type="unknown",
            spec=PlanetarySpec(
                stages=[GearStage(ratio=3.0)],
                overall_ratio=3.0,
                power_kW=1.0,
                materials={"gear": "steel", "housing": "aluminum"},
                outputs={"torqueNm": 10, "radialN": 10, "axialN": 5},
            ),
        )


def test_cam_schema_valid():
    c = CamJobCreate(assembly_job_id=1, post="grbl", params={})
    assert c.assembly_job_id == 1


def test_sim_schema_valid():
    s = SimJobCreate(assembly_job_id=1, gcode_job_id=None, resolution_mm=0.8)
    assert s.resolution_mm > 0
