"""Smoke tests for marginal generation, fidelity, and consistency rules."""

from synthpediatric import DataDictionary, generate, marginal_fidelity, overall_score
from synthpediatric.constraints import AllowedValuesConstraint, RuleSet


def tiny_dict() -> DataDictionary:
    spec = {
        "name": "tiny",
        "n_records": 100,
        "variables": [
            {
                "name": "sex",
                "type": "categorical",
                "values": [
                    {"value": "Female", "count": 60},
                    {"value": "Male", "count": 40},
                ],
            },
            {
                "name": "stage",
                "type": "categorical",
                "values": [
                    {"value": "I", "count": 50},
                    {"value": "II", "count": 30},
                    {"value": "III", "count": 20},
                ],
            },
        ],
    }
    return DataDictionary.from_dict(spec)


def test_generate_shape_and_columns():
    d = tiny_dict()
    res = generate(d, n=500, rng=0)
    assert res.data.shape == (500, 2)
    assert set(res.data.columns) == {"sex", "stage"}


def test_marginals_are_faithful():
    d = tiny_dict()
    res = generate(d, n=20000, rng=1)
    assert overall_score(marginal_fidelity(d, res.data)) < 0.05


def test_consistency_rule_repairs_all_violations():
    d = tiny_dict()
    rules = RuleSet(
        [
            AllowedValuesConstraint(
                trigger_col="sex",
                trigger_values=["Male"],
                target_col="stage",
                allowed_values=["I"],
            )
        ]
    )
    res = generate(d, n=2000, rng=2, ruleset=rules)
    males = res.data[res.data["sex"] == "Male"]
    assert (males["stage"] == "I").all()
    assert res.total_repairs > 0
