"""Smoke tests for joint calibration (IPF/raking)."""

import numpy as np
import pandas as pd
import pytest

from synthpediatric import DataDictionary
from synthpediatric.calibrate import (
    JointDistribution,
    calibrate_to_dictionary,
    generate_calibrated,
    raking_ipf,
    targets_from_dictionary,
)


def target_dict() -> DataDictionary:
    spec = {
        "name": "target",
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
                "name": "arm",
                "type": "categorical",
                "values": [
                    {"value": "X", "count": 50},
                    {"value": "Y", "count": 50},
                ],
            },
        ],
    }
    return DataDictionary.from_dict(spec)


def proxy_with_association(n: int = 6000, seed: int = 0) -> pd.DataFrame:
    """Wrong marginals, but a real association: Females lean toward arm X."""
    rng = np.random.default_rng(seed)
    sex = rng.choice(["Female", "Male"], size=n, p=[0.3, 0.7])  # deliberately != target
    arm = np.where(
        sex == "Female",
        rng.choice(["X", "Y"], size=n, p=[0.8, 0.2]),
        rng.choice(["X", "Y"], size=n, p=[0.2, 0.8]),
    )
    return pd.DataFrame({"sex": sex, "arm": arm})


def _cond_x_given_female(joint: JointDistribution) -> float:
    si = joint.dimensions.index("sex")
    fi = joint.categories["sex"].index("Female")
    xi = joint.categories["arm"].index("X")
    row = joint.table.take(fi, axis=si)
    return float(row[xi] / row.sum())


def test_ipf_matches_target_marginals():
    d = target_dict()
    proxy = proxy_with_association()
    result = calibrate_to_dictionary(proxy, ["sex", "arm"], d)
    assert result.converged
    sex_m = result.joint.marginal("sex")
    arm_m = result.joint.marginal("arm")
    assert abs(sex_m["Female"] - 0.60) < 1e-3
    assert abs(arm_m["X"] - 0.50) < 1e-3


def test_ipf_preserves_association_direction():
    d = target_dict()
    proxy = proxy_with_association()
    raw = JointDistribution.from_records(proxy, ["sex", "arm"])
    cal = calibrate_to_dictionary(proxy, ["sex", "arm"], d).joint
    # Females still lean to arm X after calibration, and well above the 0.5 marginal.
    assert _cond_x_given_female(raw) > 0.6
    assert _cond_x_given_female(cal) > 0.6


def test_generate_calibrated_shape_and_backbone():
    d = target_dict()
    cal = calibrate_to_dictionary(proxy_with_association(), ["sex", "arm"], d).joint
    res = generate_calibrated(d, cal, n=1000, rng=3)
    assert res.data.shape == (1000, 2)
    assert set(res.data.columns) == {"sex", "arm"}


def test_from_records_empty_proxy_raises():
    empty = pd.DataFrame({"sex": [np.nan, np.nan], "arm": [np.nan, np.nan]})
    with pytest.raises(ValueError, match="no complete proxy records"):
        JointDistribution.from_records(empty, ["sex", "arm"])


def test_raking_ipf_no_aligned_targets_raises():
    joint = JointDistribution.from_records(proxy_with_association(), ["sex", "arm"])
    # Target labels that do not overlap the joint's categories at all.
    bogus = {"sex": {"Nonbinary": 1.0}}
    with pytest.raises(ValueError, match="nothing to calibrate"):
        raking_ipf(joint, bogus)


def test_generate_calibrated_unknown_backbone_dimension_raises():
    d = target_dict()
    # A joint whose dimension ("ghost") is not a variable in the dictionary.
    ghost = JointDistribution.from_records(
        pd.DataFrame({"ghost": ["p", "q", "p", "q"]}), ["ghost"]
    )
    with pytest.raises(ValueError, match="not present in the dictionary"):
        generate_calibrated(d, ghost, n=10)


def test_targets_from_dictionary_sums_duplicate_labels():
    # Two distinct values (int 1 and str "1") render to the same label "1".
    spec = {
        "name": "dup",
        "n_records": 100,
        "variables": [
            {
                "name": "code",
                "type": "categorical",
                "values": [
                    {"value": 1, "count": 30},
                    {"value": "1", "count": 10},
                    {"value": 2, "count": 60},
                ],
            }
        ],
    }
    d = DataDictionary.from_dict(spec)
    t = targets_from_dictionary(d, ["code"])["code"]
    assert abs(t["1"] - 0.40) < 1e-9  # 0.30 + 0.10, not silently overwritten
    assert abs(t["2"] - 0.60) < 1e-9


def test_zero_mass_joint_raises_everywhere():
    jd = JointDistribution(dimensions=["x"], categories={"x": ["a", "b"]}, table=np.zeros(2))
    with pytest.raises(ValueError, match="no mass"):
        jd.marginal("x")
    with pytest.raises(ValueError, match="no mass"):
        jd.probabilities()
    with pytest.raises(ValueError, match="no mass"):
        jd.sample(5)
