"""The example configs in examples/linked: they load everywhere, and run on the real metadata.

The run needs the NCCR metadata snapshot (a local file, no network) and the RAW-JSON
dictionaries; it skips without them. Set NCCR_SNAPSHOT and NCCR_RAW_JSON to run it elsewhere.
"""
import os
from pathlib import Path

import pytest

from synthpediatric.config import load_config, normalize_config
from synthpediatric.linked import CHILD_ORDER, run_linked

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples" / "linked").glob("*.yaml"))
SNAPSHOT = Path(
    os.environ.get(
        "NCCR_SNAPSHOT",
        "/Users/robotinr2/Github/NCI-DCCPS/AI-Work/SEER RFI-RFP/Jamboree-Handoff/demo/"
        "artifacts/nccr_instances.ttl",
    )
)
RAW_JSON = Path(
    os.environ.get("NCCR_RAW_JSON", "/Users/robotinr2/Github/NCI-DCCPS/nccr-metadata/RAW-JSON")
)


def test_examples_exist_and_normalize():
    assert [p.name for p in EXAMPLES] == [
        "nccr_0_19_all_nine_n26106.yaml",
        "one_registry_all_nine_n2393.yaml",
        "one_registry_all_nine_n23930.yaml",
    ]
    for path in EXAMPLES:
        cfg = normalize_config(load_config(path))
        assert cfg["source"] == "CTC"
        assert list(cfg["linked"]["children"]) == list(CHILD_ORDER)
    assert normalize_config(load_config(EXAMPLES[0]))["n"] == 26106
    sizes = {p.stem: normalize_config(load_config(p))["n"] for p in EXAMPLES}
    assert sizes["one_registry_all_nine_n23930"] == 10 * sizes["one_registry_all_nine_n2393"]


@pytest.mark.skipif(
    not (SNAPSHOT.exists() and RAW_JSON.is_dir()), reason="NCCR metadata not available"
)
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_runs_at_a_small_n(path):
    cfg = load_config(path)
    cfg["metadata"] = str(SNAPSHOT)
    cfg["linked"]["dictionaries"] = str(RAW_JSON)
    cfg["n"] = 300
    cfg["linked"]["children"] = {
        name: ({} if name == "ABM" else {"coverage": 0.3, "rows_per_patient": 2})
        for name in CHILD_ORDER
    }
    out = run_linked(cfg)
    assert out["order"] == ["CTC", *CHILD_ORDER]
    assert all(c["passed"] for c in out["checks"])
    assert {s: len(df["data"].columns) for s, df in out["tables"].items()}["CTC"] == 114
