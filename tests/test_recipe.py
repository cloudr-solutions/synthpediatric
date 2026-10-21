"""Tests for the config-driven recipe runner (offline, JSON dictionary)."""

import json

from synthpediatric.recipe import run_recipe, write_run


def _recipe():
    return {
        "name": "test run",
        "metadata": "examples/nccr_ctc_dictionary.json",
        "n": 500,
        "seed": 1,
        "override_marginals": {"sex": {"Male": 700, "Female": 300}},
        "cohort": {
            "filters": [{"variable": "vital_status", "op": "equals", "values": ["Alive"]}]
        },
    }


def test_run_recipe_applies_override_and_cohort():
    bundle = run_recipe(_recipe())
    df = bundle["data"]
    assert len(df) == 500
    assert (df["vital_status"] == "Alive").all()        # cohort filter applied
    assert (df["sex"] == "Male").mean() > 0.6           # override shifted the split


def test_write_run_emits_all_artifacts(tmp_path):
    bundle = run_recipe(_recipe())
    out = write_run(bundle, tmp_path, fmt="csv")
    for fname in [
        "cohort.csv", "coverage.csv", "conformance.csv",
        "fidelity.csv", "dictionary.json", "manifest.json",
    ]:
        assert (out / fname).exists(), f"missing {fname}"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["n_records"] == 500
    assert manifest["tool"] == "synthpediatric"
    assert "recipe_sha256" in manifest


def test_recipe_with_survival_adds_columns():
    recipe = {
        "metadata": "examples/nccr_ctc_dictionary.json",
        "n": 400,
        "seed": 2,
        "survival": {
            "group_col": "iccc_category",
            "horizon_months": 120,
            "specs": {"__default__": 0.8},
        },
    }
    df = run_recipe(recipe)["data"]
    assert "months" in df.columns and "event" in df.columns
    assert set(df["event"].unique()).issubset({0, 1})
