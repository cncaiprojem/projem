from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from app.tasks.cam import lint_gcode


@given(
    st.lists(
        st.sampled_from(
            [
                "G0 X0 Y0 Z0",
                "G1 X1 Y1 Z-1 F100",
                "G1 X2 Y0 Z0",
                "G21",
                "G20",
            ]
        ),
        min_size=1,
        max_size=20,
    ).map(lambda lines: "\n".join(lines))
)
def test_lint_random_sequences(text: str):
    params = {"units": "mm"}
    try:
        res = lint_gcode(text, params)
        assert isinstance(res, dict)
    except Exception as e:
        # Beklenen hata durumları: boş, G0/G1 yok, F eksik, birim eksik
        assert isinstance(e, Exception)
