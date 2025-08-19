from app.sim.holder_check import Segment, swept_cylinder_min_clearance


def test_holder_clearance_stub_behaves():
    segs = [Segment(0, 0, 0, 10, 0, 0), Segment(10, 0, 0, 0, 10, 0)]
    min_clear, hits = swept_cylinder_min_clearance(segs, holder_diameter_mm=30.0, clearance_mm=10.0)
    assert isinstance(min_clear, float)
    assert isinstance(hits, list)
