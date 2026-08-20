"""Tests for the survival-analysis module (Kaplan-Meier + log-rank)."""

import numpy as np
import pandas as pd
import pytest

from synthpediatric.analyze import kaplan_meier, kaplan_meier_by_group, logrank_test


def test_kaplan_meier_hand_computed():
    # times/events: (2,1),(3,1),(4,0 censored),(5,1); n=4.
    #   t=2: at risk 4, 1 event -> S = 3/4 = 0.75
    #   t=3: at risk 3, 1 event -> S = 0.75 * 2/3 = 0.50
    #   t=4: censored           -> S = 0.50
    #   t=5: at risk 1, 1 event -> S = 0.0
    km = kaplan_meier([2, 3, 4, 5], [1, 1, 0, 1])
    assert km.n == 4
    assert km.n_events == 3
    assert km.survival_at(2) == pytest.approx(0.75)
    assert km.survival_at(3) == pytest.approx(0.50)
    assert km.survival_at(4) == pytest.approx(0.50)
    assert km.survival_at(4.9) == pytest.approx(0.50)
    assert km.survival_at(5) == pytest.approx(0.0)
    assert km.median_survival() == pytest.approx(3.0)


def test_survival_before_first_event_is_one():
    km = kaplan_meier([10, 20, 30], [1, 1, 1])
    assert km.survival_at(0) == pytest.approx(1.0)
    assert km.survival_at(5) == pytest.approx(1.0)


def test_kaplan_meier_validates_input():
    with pytest.raises(ValueError):
        kaplan_meier([1, 2], [1])  # length mismatch
    with pytest.raises(ValueError):
        kaplan_meier([-1, 2], [1, 0])  # negative time
    with pytest.raises(ValueError):
        kaplan_meier([1, 2], [1, 2])  # event not 0/1


def test_kaplan_meier_by_group_and_logrank_separates_distinct_groups():
    rng = np.random.default_rng(0)
    # Group A dies fast; group B dies slow -> log-rank should be highly significant.
    a = rng.exponential(10, size=300)
    b = rng.exponential(60, size=300)
    df = pd.DataFrame(
        {
            "months": np.concatenate([a, b]),
            "event": np.ones(600, dtype=int),
            "group": ["A"] * 300 + ["B"] * 300,
        }
    )
    curves = kaplan_meier_by_group(df, "months", "event", "group")
    assert set(curves) == {"A", "B"}
    assert curves["A"].median_survival() < curves["B"].median_survival()

    res = logrank_test(df, "months", "event", "group")
    assert res["df"] == 1
    assert res["chi2"] > 10  # clearly separated
