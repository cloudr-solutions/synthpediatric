"""Tests for the interactive rendering layer (skipped if plotly is absent)."""

import pytest

from synthpediatric.analyze import kaplan_meier


def test_write_survival_html(tmp_path):
    pytest.importorskip("plotly")
    from synthpediatric import write_survival_html

    curves = {
        "A": kaplan_meier([5, 10, 15, 20], [1, 1, 0, 1]),
        "B": kaplan_meier([2, 4, 6, 8], [1, 1, 1, 0]),
    }
    out = tmp_path / "km.html"
    write_survival_html(curves, out, title="test")

    assert out.exists()
    text = out.read_text()
    assert "Plotly.newPlot" in text          # a real interactive figure was written
    assert "At risk" in text                 # hover template present
