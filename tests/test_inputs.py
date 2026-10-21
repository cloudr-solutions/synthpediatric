"""Tests for the input ingestion layer (frequencies, cohort filters, cross-tabs)."""

import pytest

from synthpediatric import (
    DataDictionary,
    apply_cohort,
    cohort_from_dict,
    dictionary_from_frequencies,
    generate,
    override_marginals,
)
from synthpediatric.calibrate import JointDistribution


def base_dict() -> DataDictionary:
    spec = {
        "name": "base",
        "n_records": 1000,
        "variables": [
            {
                "name": "sex",
                "type": "categorical",
                "values": [{"value": "Male", "count": 500}, {"value": "Female", "count": 500}],
            },
            {
                "name": "iccc",
                "type": "categorical",
                "values": [
                    {"value": "I", "count": 600},
                    {"value": "II", "count": 300},
                    {"value": "V", "count": 100},
                ],
            },
            {
                "name": "age",
                "type": "categorical",
                "values": [
                    {"value": "05 years", "count": 300},
                    {"value": "12 years", "count": 300},
                    {"value": "17 years", "count": 400},
                ],
            },
        ],
    }
    return DataDictionary.from_dict(spec)


def test_dictionary_from_frequencies():
    d = dictionary_from_frequencies(
        {"sex": {"Male": 574264, "Female": 900104}}, name="seerstat"
    )
    probs = dict(zip(d.variables["sex"].categories, d.variables["sex"].probabilities))
    assert abs(probs["Female"] - 900104 / (900104 + 574264)) < 1e-9


def test_override_marginals_replaces_distribution():
    d = base_dict()
    out = override_marginals(d, {"sex": {"Male": 900, "Female": 100}})
    probs = dict(zip(out.variables["sex"].categories, out.variables["sex"].probabilities))
    assert abs(probs["Male"] - 0.9) < 1e-9
    # other variables untouched
    assert set(out.variables["iccc"].categories) == {"I", "II", "V"}


def test_apply_cohort_equals_restricts_values():
    d = base_dict()
    cohort = cohort_from_dict(
        {"name": "leuk", "filters": [{"variable": "iccc", "op": "equals", "values": ["I"]}]}
    )
    restricted = apply_cohort(d, cohort)
    assert list(restricted.variables["iccc"].categories) == ["I"]
    gen = generate(restricted, n=500, rng=0).data
    assert (gen["iccc"] == "I").all()


def test_apply_cohort_min_max_on_numeric_labels():
    d = base_dict()
    cohort = cohort_from_dict(
        {
            "filters": [
                {"variable": "age", "op": "min", "threshold": 7},
                {"variable": "age", "op": "max", "threshold": 13},
            ]
        }
    )
    restricted = apply_cohort(d, cohort)
    # 05 years dropped (min 7); 17 years dropped (max 13); 12 years kept
    assert list(restricted.variables["age"].categories) == ["12 years"]


def test_apply_cohort_min_on_nonnumeric_raises():
    d = base_dict()
    cohort = cohort_from_dict({"filters": [{"variable": "sex", "op": "min", "threshold": 1}]})
    with pytest.raises(ValueError):
        apply_cohort(d, cohort)


def test_joint_from_counts_crosstab():
    counts = {("M", "I"): 40, ("M", "II"): 10, ("F", "I"): 20, ("F", "II"): 30}
    jd = JointDistribution.from_counts(counts, ["sex", "iccc"])
    assert jd.dimensions == ["sex", "iccc"]
    # marginal of sex: M = 50/100 = 0.5
    sex_m = jd.marginal("sex")
    assert abs(sex_m["M"] - 0.5) < 1e-9
