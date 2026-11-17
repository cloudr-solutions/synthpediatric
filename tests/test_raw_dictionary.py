"""The RAW-JSON dictionary loader and its reconciliation with the RDF column list."""
import json
import os
from pathlib import Path

import pytest

from synthpediatric.config import ConfigError
from synthpediatric.raw_dictionary import key_definition, load_raw_dictionary, reconcile

RAW_JSON = Path(
    os.environ.get("NCCR_RAW_JSON", "/Users/robotinr2/Github/NCI-DCCPS/nccr-metadata/RAW-JSON")
)
SNAPSHOT = Path(
    os.environ.get(
        "NCCR_SNAPSHOT",
        "/Users/robotinr2/Github/NCI-DCCPS/AI-Work/SEER RFI-RFP/Jamboree-Handoff/demo/"
        "artifacts/nccr_instances.ttl",
    )
)


def write_raw(directory, source, columns):
    elements = [
        {
            "Column_Name_at_Source": name,
            "Column_DataType_at_Source": {"Field_Length": length, "Semantic_Type": "string"},
            "Item_Description": f"{name} description",
        }
        for name, length in columns
    ]
    path = Path(directory) / f"{source.lower()}_metadata.json"
    path.write_text(json.dumps({"Dictionary_Elements": elements}))
    return path


def test_load_and_key_definition(tmp_path):
    write_raw(tmp_path, "CTC", [("nccrId", 64), ("sex", 1), ("tumorRecordNumber", "2")])
    raw = load_raw_dictionary(tmp_path, "ctc")
    assert raw.names == ["nccrId", "sex", "tumorRecordNumber"]
    assert key_definition(raw, "nccrId")["length"] == 64
    assert key_definition(raw, "tumorRecordNumber")["length"] == 2


def test_missing_file_and_missing_key_are_config_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_raw_dictionary(tmp_path, "CTC")
    write_raw(tmp_path, "CTC", [("sex", 1), ("nccrId", 64)])
    with pytest.raises(ConfigError, match="nccrId"):
        load_raw_dictionary(tmp_path, "CTC")


def test_reconcile_orders_keys_then_raw_then_rdf_only(tmp_path):
    write_raw(tmp_path, "CTC", [
        ("nccrId", 64), ("sex", 1), ("tumorRecordNumber", 2), ("referenceId1", 20), ("age", 3),
    ])
    raw = load_raw_dictionary(tmp_path, "CTC")
    rec = reconcile(raw, ["age", "sex", "tumorRecordNumber", "zeta", "alpha"])
    assert rec.columns == [
        "nccrId", "tumorRecordNumber", "sex", "referenceId1", "age", "alpha", "zeta"
    ]
    assert rec.raw_only == ["nccrId", "referenceId1"]
    assert rec.ttl_only == ["alpha", "zeta"]


def test_reconcile_source_without_tumor_key(tmp_path):
    write_raw(tmp_path, "COG", [("nccrId", 64), ("flag", 1)])
    rec = reconcile(load_raw_dictionary(tmp_path, "COG"), ["flag"])
    assert rec.columns == ["nccrId", "flag"]


@pytest.mark.skipif(
    not (RAW_JSON.is_dir() and SNAPSHOT.exists()), reason="NCCR metadata not available"
)
def test_real_metadata_column_totals():
    from synthpediatric.nccr_rdf import load_graph, source_columns

    graph = load_graph([SNAPSHOT])
    totals = {"CTC": 114, "ABM": 6, "CCDI": 4, "COG": 8, "MCD": 4, "MCE": 364, "MCP": 9,
              "PHARM": 17, "RO": 15}
    for source, expected in totals.items():
        rec = reconcile(load_raw_dictionary(RAW_JSON, source), source_columns(graph, source))
        assert len(rec.columns) == expected, source
        assert rec.columns[0] == "nccrId"
