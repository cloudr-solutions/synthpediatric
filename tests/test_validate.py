"""Tests for the validation toolkit (synthpediatric.validate).

Statistical assertions use ranges, never exact floats, so they hold on macOS and Linux.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric import validate as V
from synthpediatric.cli import main
from synthpediatric.dictionary import DataDictionary
from synthpediatric.generate import generate

ROOT = Path(__file__).resolve().parent.parent
CTC_DICT = ROOT / "examples" / "nccr_ctc_dictionary.json"
CHEAP = ["tvd", "ks", "assoc_diff"]


def make_cohort(seed: int, n: int = 2500) -> pd.DataFrame:
    """A small cohort with a real dependency (b follows a) and a numeric column (x)."""
    rng = np.random.default_rng(seed)
    a = rng.choice(["A", "B", "C", "D"], size=n, p=[0.4, 0.3, 0.2, 0.1])
    other = rng.choice(["A", "B", "C", "D"], size=n)
    b = np.where(rng.random(n) < 0.7, a, other)
    c = rng.choice(["u", "v", "w"], size=n, p=[0.5, 0.3, 0.2])
    x = rng.normal(loc=pd.Series(a).map({"A": 0, "B": 1, "C": 2, "D": 3}).to_numpy(), scale=1.0)
    return pd.DataFrame({"a": a, "b": b, "c": c, "x": x})


def shuffled(df: pd.DataFrame, col: str, seed: int) -> pd.DataFrame:
    out = df.copy()
    out[col] = np.random.default_rng(seed).permutation(out[col].to_numpy())
    return out


def disc(report):
    return report["discriminator"]["auc"]


# ------------------------------------------------------------------ metric names


def test_metric_names_closed_list():
    assert V.check_metric_names(["tvd", "ks", "tvd"]) == ("tvd", "ks")
    with pytest.raises(V.MetricNameError, match="unknown metric 'nope'"):
        V.check_metric_names(["tvd", "nope"])
    with pytest.raises(V.MetricNameError):
        V.check_metric_names("tvd")
    with pytest.raises(V.MetricNameError):
        V.check_metric_names(["tvd"], group="privacy")  # tvd is not a privacy metric
    block = {"fidelity": ["tvd"], "utility": [], "privacy": [], "suppression_min": 16}
    assert V.check_validate_block(block)["fidelity"] == ("tvd",)
    with pytest.raises(V.MetricNameError):
        V.check_validate_block({"fidelity": ["bogus"]})


def test_default_min_count_matches_config():
    from synthpediatric.config import DEFAULT_SUPPRESSION_MIN

    assert V.DEFAULT_MIN_COUNT == DEFAULT_SUPPRESSION_MIN == 16


# --------------------------------------------------------------- measure building blocks


def test_distance_functions():
    a = pd.Series(["x"] * 50 + ["y"] * 50)
    b = pd.Series(["x"] * 75 + ["y"] * 25)
    assert V.tv_distance(a, a) == pytest.approx(0.0)
    assert V.tv_distance(a, b) == pytest.approx(0.25)
    assert V.tv_distance(a, pd.Series(["z"] * 10)) == pytest.approx(1.0)
    u = np.arange(100, dtype=float)
    assert V.ks_distance(u, u) == pytest.approx(0.0)
    assert V.ks_distance(u, u + 1000) == pytest.approx(1.0)
    assert np.isnan(V.ks_distance(u, np.array([np.nan])))


def test_association_measures():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 4, 4000)
    indep = rng.integers(0, 4, 4000)
    assert V.cramers_v(a, 4, indep, 4) < 0.05
    assert V.cramers_v(a, 4, a, 4) > 0.95
    x = a + rng.normal(0, 0.1, 4000)
    assert V.correlation_ratio(a, 4, x) > 0.9
    assert V.correlation_ratio(a, 4, rng.normal(size=4000)) < 0.1
    assert V._abs_spearman(x, -x) > 0.99


def test_detect_types():
    df = pd.DataFrame({"n": np.arange(100.0), "few": np.arange(100) % 3, "s": ["a", "b"] * 50})
    assert V.detect_types([df], ["n", "few", "s"]) == {
        "n": "numeric", "few": "categorical", "s": "categorical",
    }
    d = DataDictionary.from_dict({"variables": [
        {"name": "few", "type": "numeric", "values": [{"value": 1, "count": 1}]},
        {"name": "n", "type": "categorical", "values": [{"value": 1, "count": 1}]},
    ]})
    assert V.detect_types([df], ["n", "few"], d) == {"n": "categorical", "few": "numeric"}
    # a column that is text in the synthetic cohort cannot be numeric
    other = df.assign(n=df["n"].astype(str))
    assert V.detect_types([df, other], ["n"])["n"] == "categorical"


# ------------------------------------------------------------------ sanity properties


def test_same_generator_different_seeds_looks_alike():
    real = make_cohort(1)
    reps = [make_cohort(s) for s in (2, 3, 4)]
    rep = V.validate_cohorts(real, reps, label="v0", seed=7)
    assert 0.40 <= disc(rep) <= 0.60
    assert rep["discriminator"]["auc_fold_std"] < 0.1
    assert len(rep["discriminator"]["auc_by_replicate"]) == 3
    assert rep["univariate"]["summary"]["max"] < 0.08
    assert rep["dependency"]["summary"]["max_abs_diff"] < 0.08
    env = rep["replicate_envelope"]
    assert env["available"] and env["fraction_inside"] >= 0.3


def test_shuffled_column_is_detected():
    real = make_cohort(1)
    good = V.validate_cohorts(real, make_cohort(2), label="good", seed=3)
    bad = V.validate_cohorts(real, shuffled(make_cohort(2), "b", 0), label="bad", seed=3)
    assert disc(bad) > 0.6
    assert disc(bad) > disc(good) + 0.1
    bad_dep = bad["dependency"]["summary"]["max_abs_diff"]
    assert bad_dep > 0.4
    assert bad_dep > 5 * good["dependency"]["summary"]["max_abs_diff"]
    worst = bad["dependency"]["worst_pairs"][0]
    assert "b" in (worst["a"], worst["b"])
    assert bad["discriminator"]["top_columns"][0]["column"] in ("a", "b", "x")
    # the marginals were not touched, so the univariate distance stays small
    assert bad["univariate"]["summary"]["max"] < 0.08
    assert bad["replicate_envelope"]["available"] is False  # one replicate only


def test_envelope_separates_bias_from_noise():
    real = make_cohort(1)
    fine = [make_cohort(s) for s in (11, 12, 13, 14)]
    broken = [shuffled(r, "b", i) for i, r in enumerate(fine)]
    metrics = ["assoc_diff", "replicate_envelope"]
    ok = V.validate_cohorts(real, fine, label="ok", metrics=metrics)["replicate_envelope"]
    env = V.validate_cohorts(real, broken, label="bad", metrics=metrics)["replicate_envelope"]
    assert env["expected_fraction_inside_if_unbiased"] == pytest.approx(0.6)
    worst_bad = env["families"]["dependency"]["worst_outside"]
    assert worst_bad and worst_bad[0]["statistic"] == "association[a|b]"
    assert worst_bad[0]["gap"] > 0.3  # real bias: far outside the replicate range
    # sampling noise: anything outside the range is only just outside
    ok_gaps = [w["gap"] for fam in ok["families"].values() for w in fam["worst_outside"]]
    assert max(ok_gaps, default=0.0) < 0.05


def test_changed_marginal_is_detected():
    real = make_cohort(1)
    changed = make_cohort(2)
    changed["c"] = np.random.default_rng(5).choice(
        ["u", "v", "w"], size=len(changed), p=[0.2, 0.3, 0.5]
    )
    changed["x"] = changed["x"] + 1.5
    rep = V.validate_cohorts(real, changed, label="m", seed=3)
    assert rep["univariate"]["summary"]["max"] > 0.3
    assert {w["variable"] for w in rep["univariate"]["summary"]["worst"][:2]} == {"c", "x"}
    assert disc(rep) > 0.65


def test_ctc_dictionary_same_config_two_seeds():
    d = DataDictionary.load(CTC_DICT)
    real = generate(d, n=3000, rng=101).data
    syn = generate(d, n=3000, rng=202).data
    rep = V.validate_cohorts(real, syn, label="ctc", dictionary=d, seed=1)
    assert 0.40 <= disc(rep) <= 0.60
    assert rep["dependency"]["summary"]["max_abs_diff"] < 0.1


def test_unequal_sizes_balanced_and_seeded():
    real = make_cohort(1, n=3000)
    syn = make_cohort(2, n=900)
    kw = dict(label="u", seed=11, metrics=["discriminator_auc"])
    r1 = V.validate_cohorts(real, syn, **kw)
    r2 = V.validate_cohorts(real, syn, **kw)
    assert r1["discriminator"]["rows_per_class"] == 900
    assert r1["discriminator"]["rows_available"] == {"real": 3000, "synthetic": 900}
    assert disc(r1) == pytest.approx(disc(r2), abs=1e-6)
    cap = V.validate_cohorts(real, syn, max_rows_per_class=400, **kw)
    assert cap["discriminator"]["rows_per_class"] == 400


def test_missing_values_and_mismatched_columns():
    real = make_cohort(1)
    syn = make_cohort(2)
    real.loc[real.sample(200, random_state=0).index, "c"] = None
    real["only_real"] = 1
    syn["only_syn"] = 1
    rep = V.validate_cohorts(real, syn, label="m", seed=1, exclude=["a"], metrics=CHEAP)
    assert rep["data"]["columns_only_in_real"] == ["only_real"]
    assert rep["data"]["columns_only_in_synthetic"] == ["only_syn"]
    assert rep["data"]["columns_excluded"] == ["a"]
    assert "a" not in rep["data"]["types"]
    # 200 of 2500 values went missing in the real cohort only: the distance must show it
    c_row = [r for r in rep["univariate"]["per_variable"] if r["variable"] == "c"][0]
    assert c_row["distance"] > 0.05


def test_without_discriminator_needs_no_sklearn(monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn", None)
    rep = V.validate_cohorts(make_cohort(1), make_cohort(2), label="x", metrics=CHEAP)
    assert "discriminator" not in rep and "dependency" in rep
    with pytest.raises(ImportError, match=r"synthpediatric\[validate\]"):
        V.validate_cohorts(make_cohort(1), make_cohort(2), label="x")


def test_bad_inputs():
    real = make_cohort(1)
    with pytest.raises(V.ValidationError, match="label"):
        V.validate_cohorts(real, real, label="../x", metrics=["tvd"])
    with pytest.raises(V.ValidationError, match="share no columns"):
        V.validate_cohorts(real, pd.DataFrame({"zz": [1, 2]}), label="x", metrics=["tvd"])
    with pytest.raises(V.ValidationError, match="threshold"):
        V.validate_cohorts(real.head(5), real, label="x", metrics=["tvd"])
    with pytest.raises(V.MetricNameError):
        V.validate_cohorts(real, real, label="x", metrics=["pmse"])


def test_generate_replicates():
    seen = []

    def fn(seed):
        seen.append(seed)
        return make_cohort(seed, n=50)

    reps = V.generate_replicates(fn, 3, seed=10)
    assert len(reps) == 3 and seen == [11, 12, 13]


# ----------------------------------------------------------------------- disclosure


def test_category_detail_suppresses_small_counts():
    real = pd.Series(["big"] * 500 + ["mid"] * 40 + ["rare1"] * 5 + ["rare2"] * 3)
    syn = pd.Series(["big"] * 480 + ["mid"] * 45 + ["synonly"] * 30 + ["rare1"] * 2)
    det = V.category_detail(real, syn, 16)
    labels = [lv["level"] for lv in det["levels"]]
    assert "rare1" not in labels and "rare2" not in labels  # small in both cohorts: pooled
    assert "synonly" in labels  # visible in the synthetic cohort
    by = {lv["level"]: lv for lv in det["levels"]}
    assert by["synonly"]["real_n"] is None  # real count 0 is below the threshold
    assert by["big"]["real_n"] == 500
    assert by[V.POOLED_LABEL]["real_n"] is None  # 8 real rows pooled, still below 16
    for lv in det["levels"]:
        for key in ("real_n", "synthetic_n"):
            assert lv[key] is None or lv[key] >= 16
    V.audit_report({"category_detail": {"v": det}}, 16)


def test_complementary_suppression():
    assert V._suppress([500, 3, 40], 16) == [False, True, True]  # smallest other cell too
    assert V._suppress([500, 3, 4, 40], 16) == [False, True, True, False]
    assert V._suppress([500, 40], 16) == [False, False]


def test_threshold_is_configurable():
    real = pd.Series(["a"] * 100 + ["b"] * 30)
    low = V.category_detail(real, real, 10)
    high = V.category_detail(real, real, 50)
    assert [lv["real_n"] for lv in low["levels"]] == [100, 30]
    assert all(lv["real_n"] is None or lv["real_n"] >= 50 for lv in high["levels"])


def test_envelope_levels_hide_small_remainder():
    real = pd.Series(["a"] * 100 + ["b"] * 40 + ["c"] * 5)
    assert V._envelope_levels(real, 16) == ["a"]  # b dropped so c (5) cannot be derived
    assert V._envelope_levels(pd.Series(["a"] * 100 + ["b"] * 40), 16) == ["a", "b"]


def test_audit_catches_leaks():
    with pytest.raises(V.ValidationError, match="unsuppressed"):
        V.audit_report({"x": [{"real_n": 3}]}, 16)
    with pytest.raises(V.ValidationError, match="not an aggregate"):
        V.audit_report({"x": list(range(5000))}, 16)


def test_report_holds_no_row_level_data(tmp_path):
    real = make_cohort(1)
    real["pid"] = [f"PID{i:05d}" for i in range(len(real))]  # row-level identifier
    real.loc[:4, "c"] = "SECRETRARE"  # five rows: a small cell
    syn = make_cohort(2)
    syn["pid"] = [f"SYN{i:05d}" for i in range(len(syn))]
    rep = V.validate_cohorts(real, syn, label="v0", seed=1, exclude=["pid"])
    paths = V.write_report(rep, tmp_path)
    text = paths["report"].read_text() + paths["summary"].read_text()
    assert "PID0" not in text and "SYN0" not in text
    assert "SECRETRARE" not in text
    assert paths["report"].stat().st_size < 100_000
    # even if an identifier column is NOT excluded, none of its values is released
    rep2 = V.validate_cohorts(real, syn, label="v1", seed=1, metrics=CHEAP)
    dumped = json.dumps(rep2) + V.render_summary(rep2)
    assert "PID0" not in dumped and "SYN0" not in dumped


# ------------------------------------------------------------------------- history


def test_history_appends_and_flags_duplicates(tmp_path):
    real, syn = make_cohort(1), make_cohort(2)
    hist = tmp_path / "h.csv"
    for label in ("v0", "v1"):
        rep = V.validate_cohorts(real, syn, label=label, seed=1, metrics=CHEAP)
        assert V.append_history(hist, rep) is False
    assert V.append_history(hist, rep) is True
    df = V.read_history(hist)
    assert list(df["label"]) == ["v0", "v1", "v1"]
    assert {"auc", "univariate_mean", "dependency_max"} <= set(df.columns)
    hist.write_text("label,other\nv0,1\n")
    with pytest.raises(V.ValidationError, match="different columns"):
        V.append_history(hist, rep)


# ------------------------------------------------------------------------------ CLI


def test_cli_end_to_end(tmp_path, capsys):
    d = DataDictionary.load(CTC_DICT)
    real = generate(d, n=4000, rng=1).data
    real_path = tmp_path / "real.csv"
    real.to_csv(real_path, index=False)
    syn_paths = []
    for i, seed in enumerate((2, 3, 4)):
        df = generate(d, n=2500, rng=seed).data
        if i == 0:
            p = tmp_path / "syn0.parquet"
            df.to_parquet(p, index=False)
        else:
            p = tmp_path / f"syn{i}.csv"
            df.to_csv(p, index=False)
        syn_paths.append(str(p))
    out = tmp_path / "out"
    for label in ("v0", "v1"):
        rc = main([
            "validate", str(real_path), *syn_paths, "--dictionary", str(CTC_DICT),
            "--label", label, "--out-dir", str(out), "--min-count", "20", "--seed", "5",
        ])
        assert rc == 0
    assert (out / "report_v0.json").exists() and (out / "summary_v1.txt").exists()
    report = json.loads((out / "report_v1.json").read_text())
    assert report["settings"]["min_count"] == 20
    assert report["data"]["n_replicates"] == 3
    assert 0.4 <= report["discriminator"]["auc"] <= 0.6
    assert report["replicate_envelope"]["available"] is True
    hist = pd.read_csv(out / "history.csv")
    assert list(hist["label"]) == ["v0", "v1"]
    shown = capsys.readouterr().out
    assert "HEADLINE" in shown and "discriminator AUC" in shown
    # no row-level data: every list is short and every count is suppressed or >= 20
    V.audit_report(report, 20)
    assert (out / "report_v1.json").stat().st_size < 150_000


def test_cli_rejects_bad_input(tmp_path):
    real = tmp_path / "r.csv"
    make_cohort(1, n=100).to_csv(real, index=False)
    out = str(tmp_path / "o")
    with pytest.raises(SystemExit, match="unknown metric"):
        main(["validate", str(real), str(real), "--label", "v0", "--out-dir", out,
              "--metrics", "pmse"])
    with pytest.raises(SystemExit, match="label"):
        main(["validate", str(real), str(real), "--label", "a/b", "--out-dir", out,
              "--metrics", "tvd"])
