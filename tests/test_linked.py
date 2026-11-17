"""Linked generation of all nine sources on an offline fixture (tests/data/linked_sources.ttl)."""
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from synthpediatric.cli import main
from synthpediatric.config import ConfigError
from synthpediatric.linked import (
    CHILD_ORDER,
    LinkageError,
    run_linked,
    verify_linked,
)
from synthpediatric.nccr_rdf import load_graph, source_columns
from synthpediatric.recipe import run_recipe, write_run

TTL = str(Path(__file__).parent / "data" / "linked_sources.ttl")
SOURCES = ("CTC",) + CHILD_ORDER
CHILDREN = {
    "ABM": {},
    "COG": {"coverage": 1.0, "rows_per_patient": 1.0},
    "MCE": {"coverage": 1.0, "rows_per_patient": 1.0},
    "CCDI": {"coverage": 0.2, "rows_per_patient": 2.0},
    "RO": {"coverage": 0.1, "rows_per_patient": 2.0},
    "PHARM": {"coverage": 0.5, "rows_per_patient": 3.0},
    "MCD": {"coverage": 0.4, "rows_per_patient": 4.0},
    "MCP": {"coverage": 0.4, "rows_per_patient": 2.0},
}


@pytest.fixture(scope="module")
def raw_dir(tmp_path_factory):
    """RAW-JSON files: nccrId first, plus one RAW-only and one RDF-only column in CTC."""
    directory = tmp_path_factory.mktemp("raw")
    graph = load_graph([TTL])
    for source in SOURCES:
        names = [n for n in source_columns(graph, source) if n != "tumorRecordNumber"]
        if source == "CTC":
            names.remove("scope9802Public")  # RDF-only: the dictionary does not list it
            names = ["sex", "tumorRecordNumber", "referenceId1"] + [
                n for n in names if n != "sex"
            ]
        elif source == "ABM":
            names = ["tumorRecordNumber"] + names
        names = ["nccrId"] + names
        lengths = {"nccrId": 64, "tumorRecordNumber": "2", "recordId": "8"}
        elements = [
            {
                "Column_Name_at_Source": n,
                "Column_DataType_at_Source": {
                    "Field_Length": lengths.get(n, 10), "Semantic_Type": "string",
                },
                "Item_Description": "",
            }
            for n in names
        ]
        (directory / f"{source.lower()}_metadata.json").write_text(
            json.dumps({"Dictionary_Elements": elements})
        )
    return directory


def config(raw_dir, **extra):
    cfg = {
        "metadata": TTL, "source": "CTC", "n": 200, "seed": 11, "profile": "marginals_only",
        "linked": {"dictionaries": str(raw_dir), "tumors_per_patient": 1.5,
                   "children": CHILDREN},
    }
    cfg.update(extra)
    return cfg


@pytest.fixture(scope="module")
def linked(raw_dir):
    return run_linked(config(raw_dir))


def frames(linked):
    return {s: linked["tables"][s]["data"] for s in linked["order"]}


def test_all_nine_sources_are_generated(linked):
    assert linked["order"] == list(SOURCES)
    assert all(c["passed"] for c in linked["checks"])


def test_keys_present_and_first(linked):
    for src, df in frames(linked).items():
        assert df.columns[0] == "nccrId", src
        if src in ("CTC", "ABM"):
            assert df.columns[1] == "tumorRecordNumber", src


def test_every_child_nccr_id_exists_in_the_parent(linked):
    t = frames(linked)
    ids = set(t["CTC"]["nccrId"])
    for src in CHILD_ORDER:
        assert set(t[src]["nccrId"]) <= ids, src


def test_abm_pairs_equal_ctc_pairs(linked):
    t = frames(linked)
    ctc = list(zip(t["CTC"]["nccrId"], t["CTC"]["tumorRecordNumber"]))
    assert list(zip(t["ABM"]["nccrId"], t["ABM"]["tumorRecordNumber"])) == ctc
    assert len(set(ctc)) == len(ctc)


def test_key_formats(linked):
    ctc = frames(linked)["CTC"]
    assert ctc["nccrId"].str.fullmatch("[0-9a-f]{64}").all()
    assert ctc["tumorRecordNumber"].str.fullmatch("[0-9]{2}").all()
    for _, group in ctc.groupby("nccrId"):
        assert sorted(group["tumorRecordNumber"]) == [f"{i:02d}" for i in range(1, len(group) + 1)]


def test_configured_coverage_and_rows_per_patient(linked):
    t = frames(linked)
    patients = t["CTC"]["nccrId"].nunique()
    assert patients == 133
    for src, opts in CHILDREN.items():
        if src == "ABM":
            continue
        covered = t[src]["nccrId"].nunique()
        assert abs(covered / patients - opts["coverage"]) <= 0.05 * opts["coverage"] + 1 / patients
        assert abs(len(t[src]) / covered - opts["rows_per_patient"]) <= (
            0.05 * opts["rows_per_patient"] + 1 / covered
        )


def test_all_dictionary_columns_present_and_blanks_are_empty(linked, raw_dir):
    graph = load_graph([TTL])
    for src, df in frames(linked).items():
        raw = [e["Column_Name_at_Source"] for e in json.loads(
            (raw_dir / f"{src.lower()}_metadata.json").read_text())["Dictionary_Elements"]]
        ttl_only = sorted(set(source_columns(graph, src)) - set(raw))
        assert set(df.columns) == set(raw) | set(ttl_only), src
        assert list(df.columns)[-len(ttl_only):] == ttl_only if ttl_only else True
        for name, entry in linked["info"][src]["blank_columns"].items():
            assert df[name].isna().all()
            assert entry["reason"]
    ctc_blank = linked["info"]["CTC"]["blank_columns"]
    assert ctc_blank["referenceId1"]["reason"] == "not_in_rdf_metadata"
    assert "scope9802Public" in ctc_blank  # in the RDF metadata only: too_few_values
    assert ctc_blank["scope9802Public"]["reason"] == "too_few_values"
    assert frames(linked)["RO"]["recordId"].is_unique


def test_sequence_variables_are_consistent_with_the_keys(linked):
    ctc = frames(linked)["CTC"]
    ctc = ctc.assign(rank=ctc["tumorRecordNumber"].astype(int),
                     count=ctc.groupby("nccrId")["nccrId"].transform("size"))
    assert (ctc["tumorOrder"].astype(int) == ctc["rank"]).all()
    assert (ctc["numberOfPrimaries"].astype(int) == ctc["count"].clip(upper=4)).all()
    first = ctc["rank"] == 1
    first_label = "Record number 01 for patient in database"
    assert (ctc.loc[first, "recordNumberRecode"] == first_label).all()
    assert (ctc.loc[~first, "recordNumberRecode"]
            == "Record number 02 through 98 for patient in database").all()
    single = ctc["count"] == 1
    one_label = "One primary in the patient's lifetime"
    assert (ctc.loc[single, "sequenceNumberCentral"] == one_label).all()
    assert (ctc.loc[~single & first, "sequenceNumberCentral"]
            == "First of two or more primaries").all()
    assert (ctc.loc[~single & ~first, "sequenceNumberCentral"]
            == "Second to fifty-eight primaries").all()


def test_same_seed_same_output_other_seed_differs(raw_dir, linked):
    again = run_linked(config(raw_dir))
    other = run_linked(config(raw_dir, seed=12))
    for src in SOURCES:
        pd.testing.assert_frame_equal(frames(linked)[src], frames(again)[src])
    assert not frames(linked)["CTC"]["nccrId"].equals(frames(other)["CTC"]["nccrId"])


def test_na_fraction_leaves_the_sequence_variables_alone(linked):
    report = linked["tables"]["CTC"]["na_plan"].report()
    entry = report["variables"]["numberOfPrimaries"]
    assert entry["status"] == "skipped" and entry["reason"] == "rule_target"
    assert entry["detail"] == "linked sequence variable"


def test_second_configuration_with_default_children(raw_dir):
    cfg = config(raw_dir)
    cfg["linked"] = {"dictionaries": str(raw_dir), "tumors_per_patient": 1.0,
                     "children": {"ABM": {}, "PHARM": {"coverage": 0.3, "rows_per_patient": 5}}}
    out = run_linked(cfg)
    assert out["order"] == ["CTC", "ABM", "PHARM"]
    assert out["tables"]["CTC"]["data"]["tumorRecordNumber"].eq("01").all()


def test_manifest_says_linked_and_unlinked_configs_do_not(linked, tmp_path):
    out = write_run(linked["tables"]["PHARM"], tmp_path / "p")
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["table_type"] == "linked_source"
    assert "nccrId" in manifest["linkage"] and "cannot be joined" not in manifest["linkage"]
    assert manifest["linked"]["role"] == "child"
    plain = run_recipe({"metadata": TTL, "source": "PHARM", "n": 50, "seed": 1,
                        "profile": "marginals_only"})
    unlinked = json.loads((write_run(plain, tmp_path / "u") / "manifest.json").read_text())
    assert unlinked["table_type"] == "unlinked_single_source"
    assert "cannot be joined" in unlinked["linkage"]
    assert "linked" not in unlinked


def test_cli_writes_one_folder_per_source(raw_dir, tmp_path):
    cfg = config(raw_dir, outputs={"format": "csv", "archive": "zip"})
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg))
    out = tmp_path / "out"
    assert main(["run", str(path), "--out-dir", str(out)]) == 0
    for src in SOURCES:
        with zipfile.ZipFile(out / src / f"{src}.zip") as zf:
            assert zf.namelist() == [f"{src}.csv"]
    manifest = json.loads((out / "linked_manifest.json").read_text())
    assert manifest["checks_passed"] is True
    assert set(manifest["tables"]) == set(SOURCES)


def test_a_broken_link_fails_verification(linked):
    tables = {s: df.copy() for s, df in frames(linked).items()}
    tables["MCD"].loc[0, "nccrId"] = "0" * 64
    expected = {s: list(df.columns) for s, df in frames(linked).items()}
    with pytest.raises(LinkageError):
        verify_linked(tables, linked["plan"], expected)


def test_bad_dictionaries_directory_is_a_config_error(tmp_path):
    cfg = {"metadata": TTL, "source": "CTC", "n": 20, "seed": 1,
           "linked": {"dictionaries": str(tmp_path)}}
    with pytest.raises(ConfigError, match="not found"):
        run_linked(cfg)
