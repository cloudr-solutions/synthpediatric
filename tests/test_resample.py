"""Tests for category reweighting / rare-cancer oversampling."""

import pytest

from synthpediatric import DataDictionary, generate
from synthpediatric.resample import (
    oversample_values,
    rare_categories,
    reweight_variable,
)


def tiny_dict() -> DataDictionary:
    spec = {
        "name": "tiny",
        "n_records": 1000,
        "variables": [
            {
                "name": "iccc",
                "type": "categorical",
                "values": [
                    {"value": "common", "count": 950},
                    {"value": "rare", "count": 40},
                    {"value": "ultrarare", "count": 10},
                ],
            }
        ],
    }
    return DataDictionary.from_dict(spec)


def test_rare_categories_detects_low_frequency():
    d = tiny_dict()
    rare = rare_categories(d, "iccc", threshold=0.05)
    assert "rare" in rare and "ultrarare" in rare and "common" not in rare


def test_oversample_raises_rare_share_in_generated_cohort():
    d = tiny_dict()
    boosted = oversample_values(d, "iccc", ["rare", "ultrarare"], factor=20.0)
    base = generate(d, n=20000, rng=0).data["iccc"]
    over = generate(boosted, n=20000, rng=0).data["iccc"]
    base_rare = base.isin(["rare", "ultrarare"]).mean()
    over_rare = over.isin(["rare", "ultrarare"]).mean()
    assert over_rare > base_rare * 3  # substantially enriched


def test_reweight_preserves_other_variables_and_categories():
    d = tiny_dict()
    out = reweight_variable(d, "iccc", {"rare": 5.0})
    assert set(out.variables["iccc"].categories) == {"common", "rare", "ultrarare"}


def test_reweight_unknown_variable_raises():
    d = tiny_dict()
    with pytest.raises(KeyError):
        reweight_variable(d, "nope", {"x": 2.0})
