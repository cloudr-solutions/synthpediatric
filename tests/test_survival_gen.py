"""Tests for input-driven survival generation."""

import numpy as np

from synthpediatric.analyze import kaplan_meier, kaplan_meier_by_group
from synthpediatric.survival_gen import sample_survival


def test_output_shapes_and_event_values():
    groups = np.array(["A"] * 500 + ["B"] * 500)
    months, event = sample_survival(groups, {"A": 0.9, "B": 0.5}, rng=0)
    assert months.shape == (1000,)
    assert event.shape == (1000,)
    assert set(np.unique(event)).issubset({0, 1})
    assert np.all(months >= 0)


def test_lower_survival_group_has_more_events():
    groups = np.array(["good"] * 4000 + ["poor"] * 4000)
    _, event = sample_survival(groups, {"good": 0.95, "poor": 0.40}, rng=1)
    good = event[:4000].mean()
    poor = event[4000:].mean()
    assert poor > good


def test_generated_curve_approximates_spec_points():
    # Generate from an explicit survival table, then recover it with Kaplan-Meier.
    n = 40000
    groups = np.array(["x"] * n)
    spec = {"x": {"points": {12: 0.9, 60: 0.6, 120: 0.4}}}
    months, event = sample_survival(groups, spec, rng=3, horizon_months=120.0)
    km = kaplan_meier(months, event)
    # KM survival at 60 months should be close to the specified 0.6.
    assert abs(km.survival_at(60.0) - 0.6) < 0.05


def test_by_group_integration():
    groups = np.array(["A"] * 2000 + ["B"] * 2000)
    months, event = sample_survival(groups, {"A": 0.9, "B": 0.5}, rng=2)
    import pandas as pd

    df = pd.DataFrame({"g": groups, "months": months, "event": event})
    curves = kaplan_meier_by_group(df, "months", "event", "g")
    assert set(curves) == {"A", "B"}
