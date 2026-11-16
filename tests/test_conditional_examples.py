"""The example configs in examples/conditional load and run offline at a small n.

They need the NCCR metadata snapshot (a local file, no network); the tests skip without it.
Set NCCR_SNAPSHOT to the path of nccr_instances.ttl to run them elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from synthpediatric.conditional import DisclosureRefusal
from synthpediatric.config import load_config
from synthpediatric.conformance import conformance_report
from synthpediatric.recipe import run_recipe, write_run

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "conditional"
SNAPSHOT = Path(
    os.environ.get(
        "NCCR_SNAPSHOT",
        "/Users/robotinr2/Github/NCI-DCCPS/AI-Work/SEER RFI-RFP/Jamboree-Handoff/demo/"
        "artifacts/nccr_instances.ttl",
    )
)
pytestmark = pytest.mark.skipif(
    not SNAPSHOT.exists(), reason="NCCR metadata snapshot not available"
)


def _config(name: str, n: int = 2000) -> dict:
    cfg = load_config(EXAMPLES / name)
    cfg["metadata"] = str(SNAPSHOT)
    cfg["n"] = n
    return cfg


@pytest.mark.parametrize(
    "name",
    [
        "one_registry_age_sex_by_iccc.yaml",
        "nccr_age_by_iccc_0_19.yaml",
        "age_sex_by_iccc_placeholder.yaml",
        "age_by_iccc_crosstab_placeholder.yaml",
    ],
)
def test_example_runs_and_is_conformant(name, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)  # the examples use paths relative to the repository root
    bundle = run_recipe(_config(name))
    out = write_run(bundle, tmp_path)
    df = bundle["data"]
    assert len(df) == 2000
    conf = conformance_report(bundle["dictionary"], df)
    # No example applies a consistency rules file, so every value is in the dictionary.
    bad = conf[conf["n_out_of_vocabulary"] > 0]
    assert bad.empty, bad
    assert "Unknown" not in set(df["ageRecode19Groups"])
    if "sex" in df.columns:
        assert "Unknown" not in set(df["sex"])
    assert (out / "conditional_targets_vs_generated.csv").is_file()
    rule = [r for r in bundle["rules"] if r["name"] == "conditional"][0]["details"]
    assert rule["min_cell"]["offending"] == 0


def test_real_examples_record_the_override_and_exclude_open_groups(monkeypatch):
    monkeypatch.chdir(ROOT)
    bundle = run_recipe(_config("one_registry_age_sex_by_iccc.yaml"))
    rule = [r for r in bundle["rules"] if r["name"] == "conditional"][0]["details"]
    assert rule["min_cell"]["value"] == 0
    assert rule["min_cell"]["supplied_by"] == "config"
    assert "team lead" in rule["min_cell"]["override_reason"]
    assert rule["provenance"]["origin"] == "cgc_aggregate"
    assert len(rule["excluded_groups"]) == 2
    groups = set(bundle["data"]["icccMajor"])
    assert not any(g.startswith(("IV.", "Not classified")) for g in groups)


def test_refusal_example_is_refused(monkeypatch):
    monkeypatch.chdir(ROOT)
    with pytest.raises(DisclosureRefusal, match="Nothing was generated"):
        run_recipe(_config("age_sex_by_iccc_refusal_placeholder.yaml"))
