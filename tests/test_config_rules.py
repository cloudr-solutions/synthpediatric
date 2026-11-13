"""Tests for YAML/JSON configs, the rule registry, profiles and the run manifest (offline)."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from synthpediatric import recipe as recipe_mod
from synthpediatric.cli import main
from synthpediatric.config import ConfigError, config_hash, normalize_config
from synthpediatric.dictionary import DataDictionary, VariableMarginal
from synthpediatric.recipe import run_recipe, write_run
from synthpediatric.rules import PROFILES, RULES, resolve_rules

DICT = "examples/nccr_ctc_dictionary.json"

# Cohort of a pre-YAML JSON recipe, captured BEFORE this feature was implemented, from
# commit d418aa6 (macOS arm64, numpy 2.5.2, pandas 2.3.3), written with full float
# precision. The recipe includes an oversample value that matches nothing, which must stay
# harmless. Stored as a table instead of one whole-file SHA-256 because the exponential
# survival times (`months`) differ in the last bit on Linux x86-64 (26 of 800 values,
# relative difference <= 2.2e-16), which flips a byte-level hash while every categorical
# and integer column stays identical.
LEGACY_GOLDEN_CSV = Path(__file__).parent / "data" / "legacy_golden.csv"
LEGACY_FLOAT_RTOL = 1e-12  # ~4500 ulp: far above libm noise, far below any real change


def _legacy_recipe():
    return {
        "name": "legacy-local",
        "metadata": DICT,
        "n": 800,
        "seed": 7,
        "override_marginals": {"sex": {"Male": 700, "Female": 300}},
        "oversample": {"variable": "iccc_category", "values": ["__none__"], "factor": 5},
        "survival": {"group_col": "iccc_category", "horizon_months": 120,
                     "specs": {"__default__": 0.8}},
    }


def _all_rules_config(**extra):
    """A config with a section for every rule (spec layout)."""
    cfg = {
        "name": "all rules",
        "metadata": DICT,
        "n": 600,
        "seed": 3,
        "targets": {
            "marginals": {"sex": {"Male": 0.6, "Female": 0.4}},
            "joints": {
                "cliques": [["sex", "age_group"]],
                "crosstabs": "examples/profiles/crosstab_sex_age.csv",
            },
            "survival": {"group_col": "iccc_category", "specs": {"V Retinoblastoma": {"s5": 0.9}}},
        },
        "cohort": {"filters": [{"variable": "vital_status", "op": "equals", "values": ["Alive"]}]},
        "oversample": {"variable": "iccc_category", "values": ["V Retinoblastoma"], "factor": 10},
        "constraints": {"file": "examples/nccr_ctc_rules.json"},
    }
    cfg.update(extra)
    return cfg


def _status(cfg):
    return {r["name"]: r["status"] for r in resolve_rules(normalize_config(cfg))}


# ---------------------------------------------------------------- loading ---

def test_load_yaml_with_comments(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "# a comment\n"
        f"metadata: {DICT}   # inline comment\n"
        "n: 50\nseed: 1\nprofile: marginals_only\n"
    )
    bundle = run_recipe(p)
    assert len(bundle["data"]) == 50
    assert bundle["profile"] == "marginals_only"


def test_load_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"metadata": DICT, "n": 40, "seed": 1}))
    assert len(run_recipe(p)["data"]) == 40


def test_yaml_and_json_resolve_and_hash_identically(tmp_path):
    cfg = _all_rules_config()
    jp, yp = tmp_path / "c.json", tmp_path / "c.yaml"
    jp.write_text(json.dumps(cfg))
    yp.write_text("# same config\n" + yaml.safe_dump(cfg, sort_keys=False))
    a, b = run_recipe(jp), run_recipe(yp)
    assert a["config"] == b["config"]
    assert a["config_sha256"] == b["config_sha256"]
    assert a["data"].equals(b["data"])


def test_legacy_layout_normalizes_to_spec_layout():
    legacy = {
        "metadata": DICT, "n": 10, "seed": 1,
        "override_marginals": {"sex": {"Male": 1, "Female": 1}},
        "rules": "examples/nccr_ctc_rules.json",
        "survival": {"group_col": "iccc_category", "specs": {"x": 0.5}},
    }
    spec = {
        "metadata": DICT, "n": 10, "seed": 1, "profile": "full",
        "targets": {
            "marginals": {"sex": {"Male": 1, "Female": 1}},
            "survival": {"group_col": "iccc_category", "specs": {"x": 0.5}},
        },
        "constraints": {"file": "examples/nccr_ctc_rules.json"},
    }
    a, b = normalize_config(legacy), normalize_config(spec)
    assert a == b
    assert config_hash(a, resolve_rules(a)) == config_hash(b, resolve_rules(b))


def test_canonical_config_is_idempotent():
    cfg = normalize_config(_all_rules_config(validate={"fidelity": ["tvd"]}))
    assert normalize_config(cfg) == cfg


def test_legacy_recipe_output_unchanged():
    """The legacy recipe still gives the pre-refactor cohort: exact for every non-float
    column (categories, event flags, row order), tight tolerance for float columns."""
    df = run_recipe(_legacy_recipe())["data"]
    golden = pd.read_csv(LEGACY_GOLDEN_CSV, float_precision="round_trip",
                         dtype={c: str for c in df.columns if df[c].dtype == object},
                         keep_default_na=False)
    assert list(df.columns) == list(golden.columns), "column set or order changed"
    assert len(df) == len(golden), f"row count changed: {len(df)} != {len(golden)}"
    differing = []
    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            if not np.allclose(df[col].to_numpy(), golden[col].to_numpy(),
                               rtol=LEGACY_FLOAT_RTOL, atol=0.0, equal_nan=True):
                differing.append(f"{col} (float, rtol={LEGACY_FLOAT_RTOL})")
        elif not df[col].astype(str).reset_index(drop=True).equals(golden[col].astype(str)):
            got, want = df[col].astype(str).to_numpy(), golden[col].astype(str).to_numpy()
            n_bad = int((got != want).sum())
            differing.append(f"{col} (exact, {n_bad} of {len(df)} rows differ)")
    assert not differing, "legacy output changed in columns: " + "; ".join(differing)


def test_legacy_layout_and_spec_layout_give_identical_frames(tmp_path):
    """Same environment, so exact equality: the old keys and the new layout (as dict and as
    a YAML file) must generate the same cohort, and a rerun with the same seed must match."""
    legacy = _legacy_recipe()
    spec = {
        "name": "legacy-local", "metadata": DICT, "n": 800, "seed": 7, "profile": "full",
        "strict": False,  # legacy keys imply non-strict: the unmatched oversample value warns
        "targets": {
            "marginals": {"sex": {"Male": 700, "Female": 300}},
            "survival": {"group_col": "iccc_category", "horizon_months": 120,
                         "specs": {"__default__": 0.8}},
        },
        "oversample": {"variable": "iccc_category", "values": ["__none__"], "factor": 5},
    }
    yp = tmp_path / "spec.yaml"
    yp.write_text(yaml.safe_dump(spec, sort_keys=False))
    a = run_recipe(copy.deepcopy(legacy))["data"]
    again = run_recipe(copy.deepcopy(legacy))["data"]
    assert a.equals(again), "same seed twice gave different output"
    assert a.equals(run_recipe(copy.deepcopy(spec))["data"]), "spec layout differs from legacy keys"
    assert a.equals(run_recipe(yp)["data"]), "YAML file differs from legacy keys"


def test_legacy_unmatched_oversample_value_is_warned_not_fatal():
    bundle = run_recipe(_legacy_recipe())
    assert any("__none__" in w for w in bundle["warnings"])


# --------------------------------------------------------------- profiles ---

@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_profile_expands_to_documented_bundle(profile):
    status = _status(_all_rules_config(profile=profile))
    # the test config configures every rule except `overrides` (it needs a file)
    applied = {n for n, s in status.items() if s == "applied"}
    skipped = {n for n, s in status.items() if s == "skipped"}
    in_profile = set(PROFILES[profile])
    assert applied == in_profile - {"overrides"}
    assert skipped == in_profile & {"overrides"}
    assert {n for n, s in status.items() if s == "disabled"} == set(RULES) - in_profile


def test_profile_bundles_are_nested():
    assert set(PROFILES["marginals_only"]) < set(PROFILES["standard"]) < set(PROFILES["full"])
    assert PROFILES["marginals_only"] == ("marginals", "overrides", "cohort")


def test_no_profile_means_full():
    assert normalize_config(_all_rules_config())["profile"] == "full"
    assert _status(_all_rules_config()) == _status(_all_rules_config(profile="full"))


def test_enabled_rule_without_section_is_skipped_not_failed():
    cfg = {"metadata": DICT, "n": 5, "seed": 1, "profile": "standard"}
    assert _status(cfg)["constraints"] == "skipped"


def test_profile_changes_the_output():
    full = run_recipe(_all_rules_config(profile="full"))["data"]
    lean = run_recipe(_all_rules_config(profile="marginals_only"))["data"]
    assert "months" in full.columns and "months" not in lean.columns


# ---------------------------------------------------- toggles / precedence ---

def test_toggle_off_a_rule_in_the_profile():
    status = _status(_all_rules_config(profile="full", rules={"survival": False}))
    assert status["survival"] == "disabled" and status["oversample"] == "applied"
    assert "months" not in run_recipe(_all_rules_config(rules={"survival": False}))["data"].columns


def test_toggle_on_a_rule_outside_the_profile():
    status = _status(_all_rules_config(profile="marginals_only", rules={"survival": True}))
    assert status["survival"] == "applied" and status["constraints"] == "disabled"


def test_toggle_on_without_parameters_is_an_error():
    with pytest.raises(ConfigError, match=r"rules\.survival.*targets\.survival"):
        normalize_and_resolve(
            {"metadata": DICT, "profile": "marginals_only", "rules": {"survival": True}}
        )


def normalize_and_resolve(cfg):
    return resolve_rules(normalize_config(cfg))


def test_execution_order_is_fixed_and_documented():
    order = [r["name"] for r in normalize_and_resolve(_all_rules_config())]
    assert order == [
        "marginals", "overrides", "cohort", "oversample", "joints", "constraints", "survival"
    ]


def test_overrides_take_precedence_over_marginals(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("sex: {Male: 1, Female: 99}\n")
    cfg = {
        "metadata": DICT, "n": 2000, "seed": 1,
        "targets": {"marginals": {"sex": {"Male": 99, "Female": 1}},
                    "overrides": {"tables": str(f)}},
    }
    bundle = run_recipe(cfg)
    assert (bundle["data"]["sex"] == "Female").mean() > 0.9
    assert str(f) in bundle["input_files"]


def test_cohort_applies_before_oversample():
    cfg = {
        "metadata": DICT, "n": 300, "seed": 1,
        "cohort": {"filters": [{"variable": "iccc_category", "op": "equals",
                                "values": ["I Leukemias", "V Retinoblastoma"]}]},
        "oversample": {"variable": "iccc_category", "values": ["V Retinoblastoma"], "factor": 3},
    }
    bundle = run_recipe(cfg)
    assert set(bundle["data"]["iccc_category"]) <= {"I Leukemias", "V Retinoblastoma"}
    after = bundle["oversampling"][0]["proportions_after"]
    assert set(after) == {"I Leukemias", "V Retinoblastoma"}  # reweighted within the cohort


def test_joints_rule_runs_and_records_calibration():
    bundle = run_recipe(_all_rules_config(profile="standard"))
    details = [r for r in bundle["rules"] if r["name"] == "joints"][0]["details"]
    assert details["converged"] and details["clique"] == ["sex", "age_group"]
    assert (bundle["data"]["sex"] == "Male").mean() > 0.5  # marginal target 0.6 honoured


def test_inline_constraints_are_repaired():
    cfg = {
        "metadata": DICT, "n": 800, "seed": 2,
        "constraints": {"rules": [{
            "type": "allowed_values", "name": "rb_young",
            "trigger_col": "iccc_category", "trigger_values": ["V Retinoblastoma"],
            "target_col": "age_group", "allowed_values": ["00-04"],
        }]},
    }
    df = run_recipe(cfg)["data"]
    assert set(df.loc[df["iccc_category"] == "V Retinoblastoma", "age_group"]) <= {"00-04"}


# ----------------------------------------------------------------- errors ---

@pytest.mark.parametrize(
    "cfg, needles",
    [
        ({"rules": {"nope": True}}, ["rules", "'nope'", "marginals", "survival"]),
        ({"profile": "ultra"}, ["profile", "'ultra'", "marginals_only", "standard", "full"]),
        ({"n": "many"}, ["n:", "integer"]),
        ({"n": 0}, ["n:", ">= 1"]),
        ({"bogus": 1}, ["config", "'bogus'", "metadata", "profile"]),
        ({"targets": {"nope": {}}}, ["targets", "'nope'", "marginals", "joints"]),
        ({"rules": {"survival": "yes"}}, ["rules.survival", "true or false"]),
        ({"value_mode": "weird"}, ["value_mode", "label", "code"]),
        ({"no_frequency": "drop"}, ["no_frequency", "uniform", "nullify", "suppress"]),
        ({"missingness": "sometimes"}, ["missingness", "none", "realistic"]),
        ({"cohort": {"filters": [{"variable": "v", "op": "like"}]}},
         ["cohort.filters[0].op", "equals", "min", "max"]),
        ({"cohort": {"filters": [{"variable": "v", "op": "equals", "values": [True]}]}},
         ["YAML boolean", "quote"]),
        ({"targets": {"survival": {"group_col": "g"}}}, ["targets.survival", "'specs'"]),
        ({"targets": {"joints": {"cliques": [["a", "b"], ["c", "d"]], "crosstabs": "x.csv"}}},
         ["targets.joints.cliques", "exactly one"]),
        ({"constraints": {"rules": [{"type": "magic"}]}},
         ["constraints.rules[0].type", "allowed_values"]),
        ({"oversample": {"variable": "v", "values": ["a"], "factor": -1}},
         ["oversample.factor", "> 0"]),
        ({"survival": {"group_col": "g", "specs": {"a": 0.5}},
          "targets": {"survival": {"group_col": "g", "specs": {"a": 0.5}}}},
         ["duplicates", "survival"]),
    ],
)
def test_bad_configs_give_clear_errors(cfg, needles):
    with pytest.raises(ConfigError) as exc:
        normalize_config({"metadata": DICT, **cfg})
    for needle in needles:
        assert needle in str(exc.value), f"{needle!r} not in: {exc.value}"


def test_missingness_realistic_fails_rather_than_being_ignored():
    with pytest.raises(ConfigError, match="not implemented"):
        run_recipe({"metadata": DICT, "missingness": "realistic"})


def test_missing_file_and_bad_syntax_are_clear(tmp_path):
    with pytest.raises(ConfigError, match="file not found"):
        run_recipe(tmp_path / "absent.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\n")
    with pytest.raises(ConfigError, match="could not parse"):
        run_recipe(bad)
    top = tmp_path / "list.yaml"
    top.write_text("- 1\n- 2\n")
    with pytest.raises(ConfigError, match="mapping"):
        run_recipe(top)


# ------------------------------------------------------ uniform / nullify ---

def _dict_with_uniform_variable():
    return DataDictionary(
        name="t", source="t", version="1", n_records=None,
        variables={
            "sex": VariableMarginal("sex", "Sex", "categorical", ["M", "F"], [3, 7]),
            "mystery": VariableMarginal(
                "mystery", "Mystery", "categorical", ["a", "b", "c"], [1, 1, 1],
                frequency_source="uniform",
            ),
        },
    )


@pytest.fixture
def uniform_dictionary(monkeypatch):
    monkeypatch.setattr(recipe_mod, "_load_dictionary", lambda cfg: _dict_with_uniform_variable())


def test_no_frequency_uniform_is_default(uniform_dictionary):
    df = run_recipe({"metadata": DICT, "n": 600, "seed": 1})["data"]
    assert set(df["mystery"]) == {"a", "b", "c"}


def test_no_frequency_nullify_keeps_column_but_blanks_it(uniform_dictionary, tmp_path):
    uni = run_recipe({"metadata": DICT, "n": 600, "seed": 1})["data"]
    bundle = run_recipe({"metadata": DICT, "n": 600, "seed": 1, "no_frequency": "nullify"})
    df = bundle["data"]
    assert df["mystery"].isna().all()
    assert df["sex"].equals(uni["sex"])  # everything else unchanged
    out = write_run(bundle, tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["no_frequency"] == {"mode": "nullify", "variables": ["mystery"]}
    conf = (out / "conformance.csv").read_text()
    assert "mystery" not in conf  # blank is not out-of-vocabulary
    assert manifest["coverage"]["nullified"] == 1


def test_no_frequency_suppress_drops_column(uniform_dictionary):
    for mode in ("suppress", "exclude"):  # 'exclude' is the legacy spelling
        df = run_recipe({"metadata": DICT, "n": 50, "seed": 1, "no_frequency": mode})["data"]
        assert list(df.columns) == ["sex"]


# --------------------------------------------------------------- manifest ---

def test_manifest_records_profile_rules_and_hash(tmp_path):
    bundle = run_recipe(_all_rules_config(profile="standard", rules={"constraints": False}))
    out = write_run(bundle, tmp_path)
    m = json.loads((out / "manifest.json").read_text())
    assert m["profile"] == "standard"
    by_name = {r["name"]: r for r in m["rules"]}
    assert list(by_name) == list(RULES)  # explicit order
    assert by_name["joints"]["status"] == "applied" and by_name["joints"]["params"]["cliques"]
    assert by_name["constraints"]["status"] == "disabled"
    assert by_name["survival"]["status"] == "disabled"
    assert m["config_sha256"] == m["recipe_sha256"] == bundle["config_sha256"]
    assert m["missingness"] == "none"
    # reproducible from the manifest alone: re-running its config gives the same data+hash
    again = run_recipe(m["config"])
    assert again["config_sha256"] == m["config_sha256"]
    assert again["data"].equals(bundle["data"])


def test_oversampling_factors_and_proportions_in_manifest(tmp_path):
    cfg = {
        "metadata": DICT, "n": 200, "seed": 1,
        "oversample": [
            {"variable": "iccc_category", "values": ["V Retinoblastoma", "VII Hepatic"],
             "factor": 10},
            {"variable": "sex", "values": ["Female"], "factor": 2},
        ],
    }
    m = json.loads((write_run(run_recipe(cfg), tmp_path) / "manifest.json").read_text())
    first, second = m["oversampling"]
    assert first["variable"] == "iccc_category" and first["factor"] == 10.0
    assert first["factors_applied"] == {"V Retinoblastoma": 10.0, "VII Hepatic": 10.0}
    assert first["unmatched_values"] == []
    before, after = first["proportions_before"], first["proportions_after"]
    assert abs(sum(after.values()) - 1.0) < 1e-9
    assert after["V Retinoblastoma"] > before["V Retinoblastoma"]
    assert second["factors_applied"] == {"Female": 2.0}


def test_validate_block_round_trips_into_manifest(tmp_path):
    block = {"fidelity": ["tvd", "ks"], "utility": ["pmse"], "privacy": ["nn_distance"],
             "suppression_min": 11}
    m = json.loads((write_run(run_recipe(
        {"metadata": DICT, "n": 20, "seed": 1, "validate": block}), tmp_path) / "manifest.json"
    ).read_text())
    assert m["validate"] == block


def test_validate_block_defaults_and_shape_errors():
    cfg = normalize_config({"metadata": DICT, "validate": {"fidelity": ["tvd"]}})
    assert cfg["validate"] == {
        "fidelity": ["tvd"], "utility": [], "privacy": [], "suppression_min": 16
    }
    assert "validate" not in normalize_config({"metadata": DICT})
    for bad, needle in [
        ({"metrics": []}, "unknown key 'metrics'"),
        ({"fidelity": "tvd"}, "validate.fidelity"),
        ({"suppression_min": 0}, "validate.suppression_min"),
        ({"privacy": [1]}, "validate.privacy[0]"),
    ]:
        with pytest.raises(ConfigError, match=needle.replace("[", r"\[").replace("]", r"\]")):
            normalize_config({"metadata": DICT, "validate": bad})


# --------------------------------------------------------- examples / CLI ---

@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_profile_example_yaml_runs_end_to_end(profile, tmp_path, capsys):
    rc = main(["run", f"examples/profiles/{profile}.yaml", "--out-dir", str(tmp_path)])
    assert rc == 0
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["profile"] == profile
    applied = {r["name"] for r in m["rules"] if r["status"] == "applied"}
    assert applied <= set(PROFILES[profile])
    assert (tmp_path / "cohort.csv").exists()
    assert f"Profile: {profile}" in capsys.readouterr().out


def test_cli_reports_config_errors(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(f"metadata: {DICT}\nprofile: ultra\n")
    with pytest.raises(SystemExit) as exc:
        main(["run", str(bad), "--out-dir", str(tmp_path / "o")])
    assert "config error" in str(exc.value) and "ultra" in str(exc.value)


def test_recipe_ctc_yaml_matches_recipe_ctc_json_config():
    """The CTC YAML example and the JSON recipe describe the same run (offline check)."""
    with open("examples/recipe_ctc.json") as fh:
        j = normalize_config(json.load(fh))
    with open("examples/recipe_ctc.yaml") as fh:
        y = normalize_config(yaml.safe_load(fh))
    for cfg in (j, y):
        cfg.pop("outputs"), cfg.pop("name"), cfg.pop("validate", None)
    assert j == y


def test_config_copy_is_not_mutated():
    cfg = _all_rules_config()
    snapshot = copy.deepcopy(cfg)
    run_recipe(cfg)
    assert cfg == snapshot
