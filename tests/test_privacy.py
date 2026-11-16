"""Tests for the privacy tier (synthpediatric.privacy) and the `validate:` run wiring.

Statistical assertions use ranges, never exact floats, so they hold on macOS and Linux.
"""
import json

import numpy as np
import pandas as pd
import pytest

from synthpediatric import privacy as P
from synthpediatric import validate as V
from synthpediatric.cli import main
from synthpediatric.config import PRIVACY_THRESHOLD_KEYS, ConfigError, normalize_config
from synthpediatric.recipe import run_recipe, write_run

DICT = "examples/nccr_ctc_dictionary.json"
ALL_PRIVACY = list(V.METRIC_NAMES["privacy"])


def make_cohort(seed: int, n: int = 600) -> pd.DataFrame:
    """Mixed records: a dependency (b follows a), two numeric columns, and `s`, a field
    that is independent of everything else (so it cannot be inferred beyond its marginal)."""
    rng = np.random.default_rng(seed)
    a = rng.choice(["A", "B", "C", "D"], size=n, p=[0.4, 0.3, 0.2, 0.1])
    b = np.where(rng.random(n) < 0.7, a, rng.choice(["A", "B", "C", "D"], size=n))
    c = rng.choice(["u", "v", "w"], size=n, p=[0.5, 0.3, 0.2])
    s = rng.choice(["p", "q", "r"], size=n, p=[0.5, 0.3, 0.2])
    shift = pd.Series(a).map({"A": 0, "B": 1, "C": 2, "D": 3}).to_numpy()
    x = rng.normal(loc=shift, scale=1.0)
    y = rng.normal(loc=0.0, scale=2.0, size=n)
    return pd.DataFrame({"a": a, "b": b, "c": c, "s": s, "x": x, "y": y})


def priv(real, syn, holdout=None, **kw):
    kw.setdefault("privacy", ALL_PRIVACY)
    kw.setdefault("sensitive", ["s"])
    return V.validate_cohorts(real, syn, metrics=[], holdout=holdout, seed=3, **kw)


@pytest.fixture(scope="module")
def neutral():
    return priv(make_cohort(1), make_cohort(3), holdout=make_cohort(2))


@pytest.fixture(scope="module")
def leaky():
    real = make_cohort(1)
    copy = real.sample(frac=1.0, random_state=0).reset_index(drop=True)
    return priv(real, copy, holdout=make_cohort(2))


# ------------------------------------------------------------ sanity properties


def test_independent_cohort_scores_near_neutral_values(neutral):
    p = neutral["privacy"]
    ident = p["identifiability"]
    assert abs(ident["reference_if_independent"] - 0.5) < 0.01
    assert 0.35 <= ident["score"] <= 0.65
    assert 0.8 <= p["nn_distance_ratio"]["ratio"] <= 1.25
    assert p["nn_distance_ratio"]["share_synthetic_identical_to_a_real_record"] == 0.0
    assert 0.4 <= p["membership_inference"]["auc"] <= 0.6
    field = p["attribute_inference"]["fields"][0]
    assert field["sensitive_field"] == "s"
    assert field["lift"] <= 0.1          # no better than guessing the most common value
    assert field["lift"] >= -0.25        # the attack is noisier than the mode guess, not broken
    assert neutral["skipped"] == []


def test_exact_copies_are_detected_clearly(leaky):
    p = leaky["privacy"]
    assert p["identifiability"]["score"] >= 0.9
    assert p["nn_distance_ratio"]["ratio"] <= 0.05
    assert p["nn_distance_ratio"]["share_synthetic_identical_to_a_real_record"] >= 0.95
    assert p["membership_inference"]["auc"] >= 0.9
    field = p["attribute_inference"]["fields"][0]
    assert field["accuracy"] >= 0.9 and field["lift"] >= 0.3


def test_same_seed_repeats(neutral):
    again = priv(make_cohort(1), make_cohort(3), holdout=make_cohort(2))
    for name, key in [("identifiability", "score"), ("membership_inference", "auc"),
                      ("nn_distance_ratio", "ratio")]:
        assert again["privacy"][name][key] == pytest.approx(neutral["privacy"][name][key])


def test_sampling_cap_is_applied_and_reported():
    r = priv(make_cohort(1, 400), make_cohort(3, 400), max_records=100, privacy=["identifiability"])
    assert r["privacy"]["identifiability"]["records_per_cohort"] == 100
    assert r["privacy"]["settings"]["max_records"] == 100


def test_replicates_are_averaged_and_listed():
    r = priv(make_cohort(1), [make_cohort(3), make_cohort(4)], privacy=["identifiability"])
    ident = r["privacy"]["identifiability"]
    assert len(ident["score_by_replicate"]) == 2
    assert min(ident["score_by_replicate"]) <= ident["score"] <= max(ident["score_by_replicate"])


# ---------------------------------------------------------------- release gate


def test_no_threshold_is_reported_not_invented(neutral):
    gate = neutral["privacy"]["release_gate"]
    assert gate["metric"] == "identifiability"
    assert gate["threshold"] is None and gate["status"] == P.NO_THRESHOLD
    assert all(g["status"] == P.NO_THRESHOLD for g in neutral["privacy"]["thresholds"])
    assert neutral["privacy"]["identifiability"]["interpretation"]
    text = V.render_summary(neutral)
    assert "no threshold configured" in text and "identifiability score" in text


def test_thresholds_give_pass_and_fail(leaky):
    limits = {"identifiability_max": 0.7, "nn_distance_ratio_min": 0.5}
    ok = priv(make_cohort(1), make_cohort(3), privacy=["identifiability", "nn_distance_ratio"],
              thresholds=limits)
    assert ok["privacy"]["release_gate"]["status"] == "pass"
    status = {g["metric"]: g["status"] for g in ok["privacy"]["thresholds"]}
    assert status["nn_distance_ratio"] == "pass"
    assert status["membership_inference"] == P.NO_THRESHOLD
    real = make_cohort(1)
    bad = priv(real, real.copy(), privacy=["identifiability", "nn_distance_ratio"],
               thresholds=limits)
    assert bad["privacy"]["release_gate"]["status"] == "fail"
    assert {g["metric"]: g["status"] for g in bad["privacy"]["thresholds"]}[
        "nn_distance_ratio"] == "fail"


def test_threshold_for_a_metric_that_did_not_run_is_not_computed():
    r = priv(make_cohort(1), make_cohort(3), privacy=["nn_distance_ratio"],
             thresholds={"membership_auc_max": 0.6})
    status = {g["metric"]: g["status"] for g in r["privacy"]["thresholds"]}
    assert status["membership_inference"] == "not computed"


# ------------------------------------------------------------ skipped, disclosure


def test_metrics_that_cannot_run_are_skipped_with_a_reason():
    r = priv(make_cohort(1), make_cohort(3), sensitive=[])
    reasons = {s["metric"]: s["reason"] for s in r["skipped"]}
    assert "sensitive" in reasons["attribute_inference"]
    assert "holdout" in reasons["membership_inference"]
    assert "attribute_inference" not in r["privacy"] and "membership_inference" not in r["privacy"]
    assert "Requested but not computed" in V.render_summary(r)


def test_numeric_sensitive_field_and_tiny_cohorts_are_skipped():
    r = priv(make_cohort(1), make_cohort(3), sensitive=["x"], privacy=["attribute_inference"])
    assert "numeric" in r["skipped"][0]["reason"]
    small = priv(make_cohort(1, 20), make_cohort(3, 20), privacy=["identifiability"])
    assert "at least 30 records" in small["skipped"][0]["reason"]


def test_reports_hold_aggregates_only(neutral, leaky):
    for report in (neutral, leaky):
        V.audit_report(report, 16)
        text = json.dumps(report, default=V._json_default)
        assert "real_n" not in text and "synthetic_n" not in text
        assert set(report["privacy"]) == {
            "nn_distance_ratio", "identifiability", "attribute_inference",
            "membership_inference", "settings", "thresholds", "release_gate",
        }
        assert len(text) < 30_000


def test_distance_handles_missing_values():
    df = pd.DataFrame({"k": ["a", None, "b", "a"] * 20, "v": [1.0, np.nan, 3.0, 4.0] * 20})
    enc = P._Encoded([df, df], ["k", "v"], {"k": "categorical", "v": "numeric"})
    d, _ = P.nearest_distances(enc.rows(0, np.arange(4)), enc.rows(1, np.arange(4)),
                               enc.kinds, np.ones(2))
    assert np.allclose(d, 0.0)


# ----------------------------------------------------------------- config wiring


def test_threshold_keys_match_the_config_schema():
    assert set(PRIVACY_THRESHOLD_KEYS) == set(P.THRESHOLDS)


def test_validate_block_new_keys_round_trip_and_defaults_unchanged():
    base = normalize_config({"metadata": DICT, "validate": {"fidelity": ["tvd"]}})
    assert set(base["validate"]) == {"fidelity", "utility", "privacy", "suppression_min"}
    block = {"fidelity": ["tvd"], "real": "r.csv", "holdout": "h.csv", "sensitive": ["sex"],
             "exclude": ["id"], "max_records": 500,
             "thresholds": {"identifiability_max": 0.6}}
    cfg = normalize_config({"metadata": DICT, "validate": block})
    for key, value in block.items():
        assert cfg["validate"][key] == value
    assert normalize_config(cfg) == cfg
    for bad, needle in [
        ({"thresholds": {"identifiability": 0.5}}, "unknown key 'identifiability'"),
        ({"thresholds": {"identifiability_max": "x"}}, "expected a number"),
        ({"sensitive": "sex"}, "validate.sensitive"),
        ({"max_records": 5}, "validate.max_records"),
        ({"real": 3}, "validate.real"),
    ]:
        with pytest.raises(ConfigError, match=needle):
            normalize_config({"metadata": DICT, "validate": bad})


def run(block, **extra):
    return run_recipe({"metadata": DICT, "n": 300, "seed": 5, "validate": block, **extra})


def test_bad_metric_names_get_did_you_mean():
    with pytest.raises(ConfigError, match="Did you mean 'identifiability'"):
        run({"privacy": ["identifiabilty"]})
    with pytest.raises(ConfigError, match=r"validate\.fidelity\[1\].*Did you mean 'assoc_diff'"):
        run({"fidelity": ["tvd", "assoc_dif"]})
    with pytest.raises(ConfigError, match="No utility metrics are available yet"):
        run({"utility": ["pmse"]})


def test_non_strict_drops_unknown_names_with_a_warning():
    bundle = run({"fidelity": ["tvd", "bogus"]}, strict=False)
    assert any("validate.fidelity[1]" in w and "ignored" in w for w in bundle["warnings"])
    assert bundle["validation"]["requested"] == ["tvd"]


def test_missing_reference_file_is_an_error():
    with pytest.raises(ConfigError, match=r"validate\.real: file not found"):
        run({"fidelity": ["tvd"], "real": "does/not/exist.csv"}, strict=False)


def test_run_without_validate_block_is_unchanged(tmp_path):
    out = write_run(run_recipe({"metadata": DICT, "n": 100, "seed": 5}), tmp_path)
    assert "validation" not in json.loads((out / "manifest.json").read_text())
    assert not (out / "validation_report.json").exists()


def test_run_with_empty_lists_writes_no_report(tmp_path):
    out = write_run(run({"fidelity": []}), tmp_path)
    assert not (out / "validation_report.json").exists()


def test_run_without_real_reference_checks_published_frequencies_only(tmp_path):
    out = write_run(
        run({"fidelity": ["tvd", "ks"], "privacy": ["identifiability", "membership_inference"]}),
        tmp_path,
    )
    m = json.loads((out / "manifest.json").read_text())["validation"]
    assert m["mode"] == "dictionary_only"
    assert 0.0 <= m["headline"]["mean_tvd_published"] <= 0.2
    assert [s["metric"] for s in m["skipped"]] == ["ks", "identifiability", "membership_inference"]
    assert all("validate.real" in s["reason"] for s in m["skipped"])
    report = json.loads((out / "validation_report.json").read_text())
    assert report["tvd_published"]["n_columns"] == 5
    assert "not computed" in (out / "validation_summary.txt").read_text()
    V.audit_report(report, 16)


# ------------------------------------------------------------- end to end `run`


@pytest.fixture(scope="module")
def stand_in(tmp_path_factory):
    """Offline stand-in 'real' participant-level files, made from the dictionary."""
    root = tmp_path_factory.mktemp("real")
    real = run_recipe({"metadata": DICT, "n": 500, "seed": 101})["data"]
    hold = run_recipe({"metadata": DICT, "n": 500, "seed": 102})["data"]
    real.to_csv(root / "real.csv", index=False)
    hold.to_csv(root / "holdout.csv", index=False)
    return root


FULL = {
    "fidelity": ["tvd", "ks", "assoc_diff", "discriminator_auc", "replicate_envelope"],
    "privacy": ALL_PRIVACY,
    "sensitive": ["vital_status"],
    "thresholds": {"identifiability_max": 0.9},
}


def test_run_end_to_end_with_stand_in_real_files(stand_in, tmp_path, capsys):
    block = {**FULL, "real": str(stand_in / "real.csv"), "holdout": str(stand_in / "holdout.csv")}
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"metadata": DICT, "n": 500, "seed": 7, "validate": block}))
    out = tmp_path / "out"
    assert main(["run", str(cfg), "--out-dir", str(out)]) == 0
    assert "validation_report.json" in capsys.readouterr().out
    manifest = json.loads((out / "manifest.json").read_text())
    v = manifest["validation"]
    assert v["mode"] == "real_reference"
    head = v["headline"]
    assert 0.0 <= head["identifiability"] <= 0.7
    assert 0.35 <= head["membership_auc"] <= 0.65
    assert 0.3 <= head["discriminator_auc"] <= 0.7
    assert "attribute_inference_max_lift" in head and "nn_distance_ratio" in head
    assert head["release_gate_identifiability"] == "pass"
    assert [s["metric"] for s in v["skipped"]] == ["replicate_envelope"]
    assert "2 synthetic replicates" in v["skipped"][0]["reason"]
    assert manifest["validate"]["real"] == block["real"]
    report = json.loads((out / "validation_report.json").read_text())
    V.audit_report(report, 16)
    assert (out / "validation_summary.txt").read_text().startswith("Validation run")


def test_run_skips_discriminator_without_scikit_learn(stand_in, monkeypatch):
    def no_sklearn():
        raise ImportError("no sklearn")

    monkeypatch.setattr(V, "_require_sklearn", no_sklearn)
    bundle = run({"fidelity": ["tvd", "discriminator_auc"], "real": str(stand_in / "real.csv")})
    skipped = {s["metric"]: s["reason"] for s in bundle["validation"]["skipped"]}
    assert "scikit-learn" in skipped["discriminator_auc"]
    assert "discriminator" not in bundle["validation"]


def test_run_reports_privacy_metrics_that_need_more_input(stand_in):
    bundle = run({"privacy": ["membership_inference", "attribute_inference"],
                  "real": str(stand_in / "real.csv")})
    reasons = {s["metric"]: s["reason"] for s in bundle["validation"]["skipped"]}
    assert "holdout" in reasons["membership_inference"]
    assert "sensitive" in reasons["attribute_inference"]


def test_run_with_too_small_real_file_is_a_config_error(tmp_path):
    small = tmp_path / "small.csv"
    pd.DataFrame({"sex": ["Male"] * 5}).to_csv(small, index=False)
    with pytest.raises(ConfigError, match="below the disclosure threshold"):
        run({"fidelity": ["tvd"], "real": str(small)})


def test_validate_cli_privacy_flags(tmp_path, capsys):
    real, hold, syn = make_cohort(1), make_cohort(2), make_cohort(3)
    for name, df in (("real", real), ("hold", hold), ("syn", syn)):
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    rc = main([
        "validate", str(tmp_path / "real.csv"), str(tmp_path / "syn.csv"), "--label", "p0",
        "--out-dir", str(tmp_path / "out"), "--metrics", "tvd", "--privacy", "all",
        "--holdout", str(tmp_path / "hold.csv"), "--sensitive", "s", "--max-records", "300",
    ])
    assert rc == 0
    report = json.loads((tmp_path / "out" / "report_p0.json").read_text())
    assert set(report["privacy"]) >= set(ALL_PRIVACY)
    assert report["privacy"]["settings"]["max_records"] == 300
    assert "PRIVACY" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown metric"):
        main(["validate", str(tmp_path / "real.csv"), str(tmp_path / "syn.csv"), "--label", "p1",
              "--out-dir", str(tmp_path / "out"), "--privacy", "nope"])
