from app.post.lint import lint_gcode


def test_lint_gcode_happy_path():
    nc = """
( JOB: test )
G21
G90
( WCS G54 )
T1 M6
G43 H1
M8
G0 X0 Y0 Z5
M9
M30
""".strip()
    out = lint_gcode(nc, dialect="grbl", tool_plane_enabled=False)
    assert isinstance(out, dict)
    assert "errors" in out and not out["errors"]


def test_lint_gcode_warns_on_missing_units_and_plane():
    nc = """
( JOB: test )
G90
( WCS G54 )
T1 M6
G43 H1
M8
G0 X0 Y0 Z5
M30
""".strip()
    out = lint_gcode(nc, dialect="fanuc", tool_plane_enabled=True)
    assert any("Units" in w for w in out["warnings"])  # G21/G20 yok
    assert any("Tool plane" in w for w in out["warnings"])  # G68 yok
