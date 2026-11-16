"""The measure toolkit: suppression, audit, formats, config errors and the round trip."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric import measure as M
from synthpediatric.analyze import kaplan_meier
from synthpediatric.cli import main
from synthpediatric.config import ConfigError
from synthpediatric.measure import (
    MeasureAuditError,
    MeasureError,
    audit_outputs,
    measure_config_hash,
    normalize_measure_config,
    run_measure,
    suppress_table,
)
from synthpediatric.recipe import run_recipe

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = ROOT / "examples" / "nccr_ctc_dictionary.json"


# ------------------------------------------------------------------ small fixtures

def _extract(n: int = 3000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sex = rng.choice(["1", "2"], size=n)
    age = rng.uniform(0, 20, size=n).round(1)
    group = rng.choice(["A", "B"], size=n, p=[0.6, 0.4]).astype(object)
    group[:5] = "RARE"  # five participants: below the threshold
    time = rng.exponential(120, size=n)
    status = np.where(rng.uniform(size=n) < 0.3, "Dead", "Alive")
    return pd.DataFrame(
        {"SEX_CODE": sex, "age_years": age, "dx": group, "months": time.round(0), "status": status}
    )


def _config(tmp_path: Path, **over) -> dict:
    _extract().to_csv(tmp_path / "extract.csv", index=False)
    cfg = {
        "data": str(tmp_path / "extract.csv"),
        "rename": {"SEX_CODE": "sex", "dx": "diagnosis"},
        "labels": {"sex": {"1": "Male", "2": "Female"}},
        "bins": {"age_years": {"edges": [0, 10, 20.1], "labels": ["00-09", "10-19"]}},
        "frequencies": ["sex", "age_years", "diagnosis"],
        "crosstabs": [{"name": "sex_age", "variables": ["sex", "age_years"]}],
        "survival": [{
            "name": "surv", "group": "diagnosis", "time": "months", "event": "status",
            "event_values": ["Dead"], "time_points": [12, 60], "median": True,
        }],
        "outputs": {"dir": str(tmp_path / "out")},
    }
    cfg.update(over)
    return cfg


# ------------------------------------------------------------------ suppression

def test_lone_small_cell_in_a_one_way_table_also_loses_the_smallest_other():
    kept, stats = suppress_table({("a",): 5, ("b",): 40, ("c",): 20, ("d",): 100}, 16)
    assert set(kept) == {("b",), ("d",)}  # a (small) and c (smallest other) are gone
    assert stats["suppressed_primary"] == 1
    assert stats["suppressed_complementary"] == 1


def test_two_small_cells_need_no_complementary_suppression():
    kept, stats = suppress_table({("a",): 5, ("b",): 9, ("c",): 20, ("d",): 100}, 16)
    assert set(kept) == {("c",), ("d",)}
    assert stats["suppressed_complementary"] == 0


def test_cells_at_the_threshold_are_kept():
    kept, _ = suppress_table({("a",): 16, ("b",): 15, ("c",): 14, ("d",): 100}, 16)
    assert set(kept) == {("a",), ("d",)}


def test_crosstab_complementary_suppression_covers_rows_and_columns():
    counts = {
        ("m", "x"): 3, ("m", "y"): 50, ("m", "z"): 60,
        ("f", "x"): 40, ("f", "y"): 45, ("f", "z"): 55,
    }
    kept, stats = suppress_table(counts, 16)
    assert stats["suppressed_primary"] == 1
    assert stats["suppressed_complementary"] >= 2
    hidden = set(counts) - set(kept)
    # no row and no column has exactly one hidden cell
    for axis in (0, 1):
        for value in {c[axis] for c in counts}:
            assert sum(1 for c in hidden if c[axis] == value) != 1


def test_random_tables_never_leave_a_line_with_one_hidden_cell():
    rng = np.random.default_rng(3)
    for _ in range(30):
        shape = (rng.integers(2, 5), rng.integers(2, 5), rng.integers(2, 4))
        counts = {
            (i, j, k): int(rng.choice([2, 8, 30, 90]))
            for i in map(str, range(shape[0]))
            for j in map(str, range(shape[1]))
            for k in map(str, range(shape[2]))
        }
        kept, _ = suppress_table(counts, 16)
        assert all(v >= 16 for v in kept.values())
        hidden = set(counts) - set(kept)
        for axis in range(3):
            lines = {}
            for c in counts:
                lines.setdefault(c[:axis] + c[axis + 1:], []).append(c)
            for line in lines.values():
                assert sum(1 for c in line if c in hidden) != 1 or len(line) == 1


# ------------------------------------------------------------------ outputs and formats

def test_outputs_formats_and_suppression_on_a_small_extract(tmp_path):
    manifest = run_measure(_config(tmp_path))
    out = tmp_path / "out"
    sex = json.loads((out / "freqs/sex.json").read_text())
    assert set(sex["sex"]) == {"Male", "Female"}
    assert all(isinstance(v, int) and v >= 16 for v in sex["sex"].values())
    diag = json.loads((out / "freqs/diagnosis.json").read_text())["diagnosis"]
    assert "RARE" not in diag  # 5 participants: a value with no count is not listed
    cross = pd.read_csv(out / "crosstabs/sex_age.csv")
    assert list(cross.columns) == ["sex", "age_years", "count"]
    assert set(cross["age_years"]) == {"00-09", "10-19"}
    specs = json.loads((out / "survival/surv.json").read_text())
    assert set(specs) == {"A", "B"}  # RARE has 5 participants: not exported
    assert [p[0] for p in specs["A"]["points"]] == [12, 60]
    summary = pd.read_csv(out / "survival/surv_summary.csv")
    assert set(summary["group"]) == {"A", "B"} and (summary["n"] >= 16).all()
    freq_entry = next(e for e in manifest["outputs"] if e["variables"] == ["diagnosis"])
    assert freq_entry["suppressed_primary"] == 1
    assert freq_entry["suppressed_complementary"] == 1
    surv_entry = next(e for e in manifest["outputs"] if e["kind"] == "survival")
    assert surv_entry["groups_dropped_small"] == 1


def test_survival_values_match_kaplan_meier_on_the_extract(tmp_path):
    cfg = _config(tmp_path)
    run_measure(cfg)
    data = _extract()
    sub = data[data["dx"] == "A"]
    km = kaplan_meier(sub["months"].clip(upper=120), (sub["status"] == "Dead").astype(int))
    specs = json.loads((tmp_path / "out/survival/surv.json").read_text())
    got = dict((t, s) for t, s in specs["A"]["points"])
    assert got[60] == pytest.approx(km.survival_at(60), abs=1e-3)


def test_survival_value_is_withheld_when_too_few_remain_at_risk(tmp_path):
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "g": ["A"] * 300, "t": rng.uniform(1, 40, 300).round(0), "e": rng.integers(0, 2, 300),
    })
    df.to_csv(tmp_path / "s.csv", index=False)
    cfg = {
        "data": str(tmp_path / "s.csv"),
        "survival": [{"group": "g", "time": "t", "event": "e", "time_points": [12, 60]}],
        "outputs": {"dir": str(tmp_path / "o")},
    }
    run_measure(cfg)
    specs = json.loads((tmp_path / "o/survival/survival_by_g.json").read_text())
    assert [p[0] for p in specs["A"]["points"]] == [12]  # nobody is at risk at 60 months


def test_small_event_counts_are_withheld(tmp_path):
    df = pd.DataFrame({
        "g": ["A"] * 400, "t": np.arange(400) % 90 + 1,
        "e": [1 if i < 4 else 0 for i in range(400)],
    })
    df.to_csv(tmp_path / "s.csv", index=False)
    cfg = {
        "data": str(tmp_path / "s.csv"),
        "survival": [{"group": "g", "time": "t", "event": "e", "time_points": [12]}],
        "outputs": {"dir": str(tmp_path / "o")},
    }
    manifest = run_measure(cfg)
    entry = manifest["outputs"][0]
    assert entry["groups_exported"] == 0  # 4 events in total: a small count
    assert not (tmp_path / "o/survival/survival_by_g.json").exists()


def test_manifest_has_hash_threshold_counts_and_no_participant_data(tmp_path):
    cfg = _config(tmp_path)
    manifest = run_measure(cfg)
    on_disk = json.loads((tmp_path / "out/measure_manifest.json").read_text())
    assert on_disk["measure_config_sha256"] == measure_config_hash(normalize_measure_config(cfg))
    assert on_disk["threshold"] == 16
    assert on_disk["suppressed_cells_total"] == manifest["suppressed_cells_total"] > 0
    text = json.dumps(on_disk)
    assert "RARE" not in text  # no suppressed value
    assert str(len(_extract())) not in {str(v) for v in on_disk.values()}  # no total N


def test_threshold_is_configurable(tmp_path):
    run_measure(_config(tmp_path, threshold=3000, outputs={"dir": str(tmp_path / "hi")}))
    assert not (tmp_path / "hi/freqs/sex.json").exists()  # every cell is below 3000


# ------------------------------------------------------------------ audit

def test_audit_refuses_a_frequency_table_with_a_small_count(tmp_path):
    (tmp_path / "freqs").mkdir()
    (tmp_path / "freqs/x.json").write_text(json.dumps({"x": {"a": 40, "b": 5}}))
    with pytest.raises(MeasureAuditError, match="below the threshold"):
        audit_outputs(tmp_path, 16)


def test_audit_refuses_a_crosstab_with_a_small_or_blank_count(tmp_path):
    (tmp_path / "crosstabs").mkdir()
    path = tmp_path / "crosstabs/x.csv"
    path.write_text("a,b,count\nx,y,40\nx,z,3\n")
    with pytest.raises(MeasureAuditError, match="below the threshold"):
        audit_outputs(tmp_path, 16)
    path.write_text("a,b,count\nx,y,40\nx,z,\n")
    with pytest.raises(MeasureAuditError, match="numeric"):
        audit_outputs(tmp_path, 16)


def test_audit_refuses_unexpected_files_and_survival_groups_without_a_summary_row(tmp_path):
    (tmp_path / "participants.csv").write_text("id\n1\n")
    with pytest.raises(MeasureAuditError, match="unexpected file"):
        audit_outputs(tmp_path, 16)
    (tmp_path / "participants.csv").unlink()
    (tmp_path / "survival").mkdir()
    (tmp_path / "survival/s.json").write_text('{"A": {"s5": 0.9}}')
    with pytest.raises(MeasureAuditError, match="summary"):
        audit_outputs(tmp_path, 16)
    (tmp_path / "survival/s_summary.csv").write_text("group,n,s5\nA,9,0.9\n")
    with pytest.raises(MeasureAuditError, match="below the threshold"):
        audit_outputs(tmp_path, 16)


def test_audit_accepts_a_clean_directory(tmp_path):
    run_measure(_config(tmp_path))
    assert "freqs/sex.json" in audit_outputs(tmp_path / "out", 16)


def test_run_leaves_nothing_behind_when_the_audit_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "suppress_table", lambda counts, t: (dict(counts), {
        "cells": len(counts), "suppressed_primary": 0, "suppressed_complementary": 0,
    }))
    with pytest.raises(MeasureAuditError):
        run_measure(_config(tmp_path))
    assert not (tmp_path / "out").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["extract.csv"]  # staging is gone too


# ------------------------------------------------------------------ did-you-mean errors

def test_missing_variable_gets_a_did_you_mean_error(tmp_path):
    cfg = _config(tmp_path, frequencies=["sexx"])
    with pytest.raises(MeasureError, match=r"unknown variable 'sexx'.*Did you mean 'sex'"):
        run_measure(cfg)


def test_unexpected_label_is_an_error_with_a_dictionary_and_a_warning_when_not_strict(tmp_path):
    df = pd.DataFrame({"sex": ["Male"] * 40 + ["Femal"] * 40})
    df.to_csv(tmp_path / "d.csv", index=False)
    cfg = {
        "data": str(tmp_path / "d.csv"), "dictionary": str(DICTIONARY), "frequencies": ["sex"],
        "outputs": {"dir": str(tmp_path / "o")},
    }
    with pytest.raises(MeasureError, match=r"unknown category 'Femal'.*Did you mean 'Female'"):
        run_measure(cfg)
    manifest = run_measure({**cfg, "strict": False})
    assert manifest["label_warnings"] == 1


def test_continuous_variable_needs_bins(tmp_path):
    cfg = _config(tmp_path, bins={})
    with pytest.raises(MeasureError, match="continuous.*bins"):
        run_measure(cfg)


def test_config_key_typos_and_empty_measure_are_rejected(tmp_path):
    with pytest.raises(ConfigError, match="unknown key 'frequences'"):
        normalize_measure_config({"data": "x.csv", "frequences": ["a"]})
    with pytest.raises(MeasureError, match="nothing to measure"):
        normalize_measure_config({"data": "x.csv"})
    with pytest.raises(MeasureError, match="beyond horizon"):
        normalize_measure_config({
            "data": "x.csv",
            "survival": [{"group": "g", "time": "t", "event": "e", "time_points": [200]}],
        })


def test_non_empty_output_dir_is_refused_unless_overwrite(tmp_path):
    cfg = _config(tmp_path)
    run_measure(cfg)
    with pytest.raises(MeasureError, match="not empty"):
        run_measure(cfg)
    run_measure(cfg, overwrite=True)


def test_cohort_filter_restricts_the_measured_rows(tmp_path):
    cfg = _config(tmp_path, cohort={
        "filters": [{"variable": "age_years", "op": "min", "threshold": 10}],
    }, crosstabs=[], survival=[], frequencies=["age_years"])
    run_measure(cfg)
    table = json.loads((tmp_path / "out/freqs/age_years.json").read_text())["age_years"]
    assert set(table) == {"10-19"}


def test_cli_runs_and_reports(tmp_path, capsys):
    cfg = _config(tmp_path)
    path = tmp_path / "measure.json"
    path.write_text(json.dumps(cfg))
    assert main(["measure", str(path)]) == 0
    assert "Audit passed" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not empty"):
        main(["measure", str(path)])


# ------------------------------------------------------------------ round trip

def test_round_trip_measured_files_reproduce_the_real_cohort(tmp_path):
    stand_in = {
        "name": "stand-in", "metadata": str(DICTIONARY), "n": 30000, "seed": 7,
        "profile": "full",
        "targets": {
            "joints": {
                "cliques": [["sex", "age_group"]],
                "crosstabs": str(ROOT / "examples/profiles/crosstab_sex_age.csv"),
            },
            "survival": {
                "group_col": "iccc_category", "horizon_months": 120,
                "specs": {
                    "I Leukemias": {"points": {12: 0.97, 60: 0.88, 120: 0.82}},
                    "III CNS": {"median_months": 150},
                    "__default__": {"s5": 0.85},
                },
            },
        },
    }
    real = run_recipe(stand_in)["data"]
    real.to_csv(tmp_path / "real.csv", index=False)

    out = tmp_path / "agg"
    variables = ["iccc_category", "sex", "age_group", "diagnosis_year_group", "vital_status"]
    run_measure({
        "data": str(tmp_path / "real.csv"),
        "frequencies": variables,
        "crosstabs": [{"name": "sex_age", "variables": ["sex", "age_group"]}],
        "survival": [{
            "name": "by_iccc", "group": "iccc_category", "time": "months", "event": "event",
            "time_points": [12, 36, 60], "form": "points",
        }],
        "outputs": {"dir": str(out)},
    })

    generator = {
        "name": "from measured", "metadata": str(DICTIONARY), "n": 30000, "seed": 11,
        "profile": "full",
        "targets": {
            "overrides": {"tables": str(out / "freqs")},
            "joints": {
                "cliques": [["sex", "age_group"]],
                "crosstabs": str(out / "crosstabs/sex_age.csv"),
            },
            "survival": {
                "group_col": "iccc_category", "horizon_months": 120,
                "specs": str(out / "survival/by_iccc.json"),
            },
        },
    }
    new = run_recipe(generator)["data"]

    def share(df, col):
        return df[col].value_counts(normalize=True)

    for col in variables:  # marginals: total variation distance within sampling noise
        a, b = share(real, col), share(new, col)
        tvd = 0.5 * a.sub(b, fill_value=0).abs().sum()
        assert tvd < 0.02, (col, tvd)

    def cells(df):
        return df.groupby(["sex", "age_group"]).size() / len(df)

    diff = cells(real).sub(cells(new), fill_value=0).abs().max()
    assert diff < 0.012, diff  # cross-tab cells

    measured = json.loads((out / "survival/by_iccc.json").read_text())
    for group in ("I Leukemias", "III CNS", "XI Epithelial/melanoma"):
        r = real[real["iccc_category"] == group]
        n = new[new["iccc_category"] == group]
        s_real = kaplan_meier(r["months"], r["event"]).survival_at(60)
        s_new = kaplan_meier(n["months"], n["event"]).survival_at(60)
        assert abs(s_real - s_new) < 0.04, (group, s_real, s_new)
        assert group in measured
