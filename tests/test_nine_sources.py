"""All nine NCCR sources as standalone, unlinked tables.

The offline tests run on ``tests/data/nine_sources.ttl``, a small Turtle file that has the
quirks of the real metadata. ``test_real_metadata_all_sources`` runs on the published
metadata and is skipped unless ``SYNTHPEDIATRIC_NETWORK_TESTS=1``.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric.cli import main
from synthpediatric.config import ConfigError, config_hash, normalize_config
from synthpediatric.conformance import generation_report
from synthpediatric.evaluate import fidelity_summary, overall_score
from synthpediatric.nccr_rdf import KNOWN_SOURCES, build_dictionary, load_graph
from synthpediatric.recipe import run_recipe, write_run
from synthpediatric.rules import resolve_rules
from synthpediatric.source_policy import resolve_source_policy

TTL = str(Path(__file__).parent / "data" / "nine_sources.ttl")
SOURCES = sorted(KNOWN_SOURCES)
COUNT_LABELS = {"19163", "207907", "637337"}  # PHARM duration: the label is the record count


def run(source, tmp_path, **extra):
    cfg = {"metadata": TTL, "source": source, "n": 300, "seed": 3, "profile": "marginals_only"}
    cfg.update(extra)
    bundle = run_recipe(cfg)
    out = write_run(bundle, tmp_path)
    return bundle, json.loads((out / "manifest.json").read_text()), out


@pytest.mark.parametrize("source", SOURCES)
def test_each_source_runs_and_is_labelled(source, tmp_path):
    bundle, manifest, out = run(source, tmp_path)
    assert manifest["table_type"] == "unlinked_single_source"
    assert manifest["source"] == source
    assert "participant key" in manifest["linkage"]
    assert "cannot be joined" in manifest["linkage"]
    report = manifest["generation_report"]
    assert report["source"] == source
    assert set(report) == {"source", "published", "dropped", "invented", "invented_handling"}
    assert manifest["source_policy"]["source"] == source
    assert manifest["source_policy"]["known_source"] is True
    conf = pd.read_csv(out / "conformance.csv")
    assert (conf["n_out_of_vocabulary"] == 0).all()
    assert len(bundle["data"]) == 300


def test_dropped_and_invented_are_reported_with_reasons(tmp_path):
    _, ctc, _ = run("CTC", tmp_path / "ctc")
    assert ctc["generation_report"]["dropped"] == {
        "scope9802Public": "too_few_values",
        "tumorRecordNumber": "no_value_set",
    }
    assert ctc["generation_report"]["invented"] == []
    _, mcp, _ = run("MCP", tmp_path / "mcp")
    assert mcp["generation_report"]["dropped"] == {
        "claimProcedureCode": "no_value_set",
        "claimProcedureMod1": "no_value_set",
    }
    _, ro, _ = run("RO", tmp_path / "ro")
    assert ro["generation_report"]["invented"] == ["sequenceId"]
    assert ro["generation_report"]["dropped"] == {"recordId": "no_value_set"}


def test_mce_blanks_uncounted_columns_by_default(tmp_path):
    bundle, manifest, out = run("MCE", tmp_path)
    months = [f"enrollMonthPostIndexDx{i}" for i in (1, 2, 3)]
    assert manifest["generation_report"]["invented"] == months
    assert manifest["generation_report"]["invented_handling"] == "nullify"
    assert manifest["no_frequency"] == {"mode": "nullify", "variables": months}
    cohort = pd.read_csv(out / "cohort.csv")
    assert cohort[months].isna().all().all()
    assert cohort["reportedInsuranceEnrollment"].notna().all()
    nf = manifest["source_policy"]["no_frequency"]
    assert nf == {"value": "nullify", "supplied_by": "policy"}
    assert manifest["fidelity"]["invented_columns"] == 0  # blank columns are not scored


def test_explicit_config_beats_policy_and_is_recorded(tmp_path):
    bundle, manifest, _ = run("MCE", tmp_path / "a", no_frequency="uniform")
    nf = manifest["source_policy"]["no_frequency"]
    assert nf == {"value": "uniform", "supplied_by": "config"}
    assert bundle["data"]["enrollMonthPostIndexDx1"].notna().all()
    # the config's source_policy block overrides the built-in default, below an explicit key
    _, m2, _ = run("MCE", tmp_path / "b", source_policy={"no_frequency": "suppress"})
    assert m2["source_policy"]["no_frequency"] == {
        "value": "suppress", "supplied_by": "config.source_policy",
    }
    assert "enrollMonthPostIndexDx1" not in pd.read_csv(tmp_path / "b" / "cohort.csv").columns


def test_invented_columns_do_not_count_as_matches(tmp_path):
    _, manifest, _ = run("MCE", tmp_path, no_frequency="uniform")
    fid = manifest["fidelity"]
    assert fid["published_columns"] == 1
    assert fid["invented_columns"] == 3
    assert manifest["overall_tv_distance"] == fid["overall_tv_distance_published"]
    assert manifest["overall_tv_distance_all_columns"] == fid["overall_tv_distance_all_columns"]
    # the old mean is kept under its own key, and it averages in the invented columns
    assert fid["overall_tv_distance_all_columns"] != fid["overall_tv_distance_published"]


def test_overall_score_helpers():
    report = pd.DataFrame({
        "variable": ["a", "b"], "tv_distance": [0.2, 0.0],
        "frequency_source": ["published", "uniform"],
    })
    assert overall_score(report) == pytest.approx(0.2)
    assert overall_score(report, include_invented=True) == pytest.approx(0.1)
    only_invented = report.iloc[1:]
    assert np.isnan(overall_score(only_invented))
    assert fidelity_summary(only_invented)["overall_tv_distance_published"] is None
    assert overall_score(report.drop(columns="frequency_source")) == pytest.approx(0.1)


def test_pharm_duration_uses_code_mode_by_default(tmp_path):
    bundle, manifest, _ = run("PHARM", tmp_path / "a")
    assert set(bundle["data"]["medicationDispenseDuration"]) <= {"0", "1", "10"}
    entry = manifest["source_policy"]["value_modes"]["medicationDispenseDuration"]
    assert entry == {"value": "code", "supplied_by": "policy"}
    # the label of each value is its record count: label mode returns counts as days
    bundle, manifest, _ = run(
        "PHARM", tmp_path / "b", value_modes={"medicationDispenseDuration": "label"}
    )
    assert set(bundle["data"]["medicationDispenseDuration"]) <= COUNT_LABELS
    entry = manifest["source_policy"]["value_modes"]["medicationDispenseDuration"]
    assert entry == {"value": "label", "supplied_by": "config"}
    # an explicit global value_mode also beats the policy default
    bundle, manifest, _ = run("PHARM", tmp_path / "c", value_mode="label")
    assert set(bundle["data"]["medicationDispenseDuration"]) <= COUNT_LABELS
    assert manifest["source_policy"]["value_modes"] == {}


def test_config_hash_covers_policy_choices_and_ctc_hash_is_unchanged():
    cfg = {"metadata": TTL, "source": "CTC", "n": 50, "seed": 1, "profile": "marginals_only"}
    bundle = run_recipe(cfg)
    canonical = normalize_config(cfg)
    assert bundle["config_sha256"] == config_hash(canonical, resolve_rules(canonical))
    cfg["source"] = "PHARM"
    pharm = run_recipe(cfg)
    canonical = normalize_config(cfg)
    assert pharm["config_sha256"] != config_hash(canonical, resolve_rules(canonical))


def test_value_modes_validation_has_did_you_mean():
    cfg = {"metadata": TTL, "source": "PHARM", "n": 10, "seed": 1,
           "value_modes": {"medicationDispenseDuraton": "code"}}
    with pytest.raises(ConfigError, match="Did you mean 'medicationDispenseDuration'"):
        run_recipe(cfg)
    cfg["value_modes"] = {"medicationDispenseDuration": "codes"}
    with pytest.raises(ConfigError, match="Valid choices: label, code"):
        run_recipe(cfg)
    # a variable the loader skips (no value set) is a known name, not a typo
    cfg["value_modes"] = {"ndc11": "code"}
    run_recipe(cfg)
    with pytest.raises(ConfigError, match="source_policy: unknown key"):
        normalize_config({"source_policy": {"survivals": "allow"}})
    with pytest.raises(ConfigError, match="source_policy.survival"):
        normalize_config({"source_policy": {"survival": "maybe"}})


def survival_cfg(source, group_col, specs, **extra):
    cfg = {"metadata": TTL, "source": source, "n": 100, "seed": 1,
           "targets": {"survival": {"group_col": group_col, "specs": specs}}}
    cfg.update(extra)
    return cfg


def test_survival_is_refused_on_non_person_tables():
    cfg = survival_cfg("MCD", "monthsFromIndexDxToDiagnosisCode", {"0": 0.5})
    with pytest.raises(ConfigError, match="refused for source 'MCD'"):
        run_recipe(cfg)
    cfg["source_policy"] = {"survival": "allow"}
    out = run_recipe(cfg)
    assert {"months", "event"} <= set(out["data"].columns)
    assert out["source_policy"]["survival"]["supplied_by"] == "config.source_policy"


def test_survival_is_allowed_on_ctc_and_can_be_refused_by_config():
    out = run_recipe(survival_cfg("CTC", "vitalStatusRecode", {"Dead": 0.5, "Alive": 0.9}))
    assert {"months", "event"} <= set(out["data"].columns)
    assert out["source_policy"]["survival"] == {"value": "allow", "supplied_by": "policy"}
    cfg = survival_cfg("CTC", "vitalStatusRecode", {"Dead": 0.5})
    cfg["source_policy"] = {"survival": "refuse"}
    with pytest.raises(ConfigError, match="refused for source 'CTC'"):
        run_recipe(cfg)


def test_policy_default_naming_a_missing_variable_is_a_warning():
    policy = resolve_source_policy("PHARM", columns=["canmedDrugCategory"])
    assert policy["value_modes"] == {}
    assert "medicationDispenseDuration" in policy["warnings"][0]


def test_loader_reports_skipped_variables():
    d = build_dictionary(load_graph([TTL]), "PHARM")
    assert d.skipped == {"ndc11": "no_value_set"}
    assert generation_report(d)["dropped"] == {"ndc11": "no_value_set"}


def test_cli_generate_summary_and_blank_columns(tmp_path, capsys):
    out = tmp_path / "mce.csv"
    args = ["generate", TTL, "--source", "MCE", "-n", "50", "--seed", "1", "-o", str(out)]
    assert main(args + ["--evaluate"]) == 0
    text = capsys.readouterr().out
    assert "unlinked, single-source table: MCE" in text
    assert "participant key" in text
    assert "Invented (no published counts), 3, left blank" in text
    assert "no_frequency=nullify (policy)" in text
    assert "invented (uniform fallback)" not in text  # blanked columns are not scored
    assert pd.read_csv(out)["enrollMonthPostIndexDx2"].isna().all()

    out = tmp_path / "pharm.csv"
    args = ["generate", TTL, "--source", "PHARM", "-n", "50", "--seed", "1", "-o", str(out)]
    assert main(args) == 0
    text = capsys.readouterr().out
    assert "Dropped (not generated), 1: ndc11" in text
    assert "medicationDispenseDuration=code (policy)" in text
    assert set(pd.read_csv(out, dtype=str)["medicationDispenseDuration"]) <= {"0", "1", "10"}

    assert main(args + ["--var-value-mode", "medicationDispenseDuration=label"]) == 0
    capsys.readouterr()
    assert set(pd.read_csv(out, dtype=str)["medicationDispenseDuration"]) <= COUNT_LABELS


def test_cli_run_summary_is_labelled(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"metadata": TTL, "source": "RO", "n": 40, "seed": 1}))
    assert main(["run", str(cfg), "--out-dir", str(tmp_path / "o")]) == 0
    text = capsys.readouterr().out
    assert "[unlinked, single-source table: RO]" in text
    assert "Dropped (not generated), 1: recordId" in text
    assert "1, filled with uniform random values: sequenceId" in text


def test_cli_bad_value_mode_is_a_config_error(tmp_path):
    with pytest.raises(SystemExit, match="Did you mean"):
        main(["generate", TTL, "--source", "PHARM", "-o", str(tmp_path / "x.csv"),
              "--var-value-mode", "medicationDispenseDuraton=code"])


@pytest.mark.skipif(
    os.environ.get("SYNTHPEDIATRIC_NETWORK_TESTS") != "1",
    reason="opt-in: set SYNTHPEDIATRIC_NETWORK_TESTS=1 to run on the published NCCR metadata",
)
def test_real_metadata_all_sources(tmp_path):
    lines = []
    for source in SOURCES:
        cfg = {"metadata": "remote", "source": source, "n": 500, "seed": 1,
               "profile": "marginals_only"}
        bundle = run_recipe(cfg)
        out = write_run(bundle, tmp_path / source)
        manifest = json.loads((out / "manifest.json").read_text())
        rep = manifest["generation_report"]
        assert manifest["table_type"] == "unlinked_single_source"
        conf = pd.read_csv(out / "conformance.csv")
        assert (conf["n_out_of_vocabulary"] == 0).all()
        pol = manifest["source_policy"]
        nf = pol["no_frequency"]
        modes = {k: v["value"] for k, v in pol["value_modes"].items()}
        lines.append(
            f"{source}: published {rep['published']}, dropped {len(rep['dropped'])}, "
            f"invented {len(rep['invented'])} ({rep['invented_handling']}), "
            f"no_frequency={nf['value']}/{nf['supplied_by']}, "
            f"survival={pol['survival']['value']}, value_modes={modes}"
        )
    print("\n".join(lines))
    mce = json.loads((tmp_path / "MCE" / "manifest.json").read_text())
    assert mce["generation_report"]["invented_handling"] == "nullify"
    pharm = json.loads((tmp_path / "PHARM" / "manifest.json").read_text())
    assert pharm["source_policy"]["value_modes"]["medicationDispenseDuration"]["value"] == "code"
