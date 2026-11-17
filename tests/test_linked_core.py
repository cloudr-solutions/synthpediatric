"""The pure linking functions: plan, keys, sequence columns, assembly, checks."""
import numpy as np
import pandas as pd
import pytest

from synthpediatric.linked import (
    LinkageError,
    assemble,
    check_linked,
    child_patients,
    make_keys,
    plan_cardinality,
    sequence_columns,
    unique_ids,
    verify_linked,
)

KEY_DEFS = {"nccrId": {"length": 64}, "tumorRecordNumber": {"length": 2}}
CHILDREN = {"ABM": {}, "COG": {"coverage": 1.0, "rows_per_patient": 1.0},
            "PHARM": {"coverage": 0.5, "rows_per_patient": 3.0}}
VALUE_MAPS = {
    "recordNumberRecode": {"01": "R1", "02": "R2"},
    "sequenceNumberCentral": {"00": "S0", "01": "S1", "02": "S2"},
    "numberOfPrimaries": {"1": "N1", "2": "N2", "3": "N3", "5": "N5"},
}


def keys_for(n=300, tpp=1.5, seed=4):
    plan = plan_cardinality(n, tpp, CHILDREN, seed)
    return plan, make_keys(plan, seed, KEY_DEFS)


def test_plan_totals_are_exact():
    plan, _ = keys_for()
    assert plan.n_patients == 200
    assert int(plan.tumor_counts.sum()) == 300
    assert plan.tumor_counts.min() == 1
    pharm = plan.children["PHARM"]
    assert len(pharm.patients) == 100 and pharm.n_rows == 300
    assert plan.children["ABM"].n_rows == 300
    assert plan.children["COG"].n_rows == 200
    assert len(child_patients(pharm)) == 300


def test_keys_format_and_ranks():
    plan, keys = keys_for()
    assert all(len(i) == 64 and set(i) <= set("0123456789abcdef") for i in keys.ids)
    assert len(set(keys.ids)) == plan.n_patients
    numbers = keys.record_numbers()
    pairs = set(zip(keys.parent_ids(), numbers))
    assert len(pairs) == 300
    assert set(numbers) <= {f"{i:02d}" for i in range(1, 100)}
    for patient in range(plan.n_patients):
        rows = np.flatnonzero(keys.row_patient == patient)
        assert list(keys.row_rank[rows]) == list(range(1, len(rows) + 1))


def test_seed_reproducibility():
    a_plan, a = keys_for(seed=4)
    b_plan, b = keys_for(seed=4)
    _, c = keys_for(seed=5)
    assert list(a.ids) == list(b.ids) and list(a.ids) != list(c.ids)
    assert list(a_plan.tumor_counts) == list(b_plan.tumor_counts)


def test_one_tumor_per_patient_gives_all_01():
    plan = plan_cardinality(50, 1.0, {}, 1)
    keys = make_keys(plan, 1, KEY_DEFS)
    assert plan.n_patients == 50
    assert set(keys.record_numbers()) == {"01"}


@pytest.mark.parametrize("k", [1, 2, 3])
def test_sequence_columns_for_patients_with_k_tumors(k):
    plan = plan_cardinality(k, float(k), {}, 1)
    keys = make_keys(plan, 1, KEY_DEFS)
    df = pd.DataFrame({"x": range(k)})
    warnings = sequence_columns(df, keys, VALUE_MAPS)
    assert warnings == []
    assert list(df["tumorOrder"]) == [str(j) for j in range(1, k + 1)]
    assert list(df["recordNumberRecode"]) == ["R1"] + ["R2"] * (k - 1)
    first = "S0" if k == 1 else "S1"
    assert list(df["sequenceNumberCentral"]) == [first] + ["S2"] * (k - 1)
    assert set(df["numberOfPrimaries"]) == {f"N{k}"}


def test_number_of_primaries_is_capped_at_an_existing_notation():
    plan = plan_cardinality(4, 4.0, {}, 1)
    keys = make_keys(plan, 1, KEY_DEFS)
    df = pd.DataFrame({"x": range(4)})
    sequence_columns(df, keys, VALUE_MAPS)
    assert set(df["numberOfPrimaries"]) == {"N3"}  # 4 is not a notation: the largest below it


def test_missing_notation_leaves_the_column_and_warns():
    plan = plan_cardinality(2, 2.0, {}, 1)
    keys = make_keys(plan, 1, KEY_DEFS)
    df = pd.DataFrame({"recordNumberRecode": ["keep", "keep"]})
    maps = {k: v for k, v in VALUE_MAPS.items() if k != "recordNumberRecode"}
    warnings = sequence_columns(df, keys, maps)
    assert list(df["recordNumberRecode"]) == ["keep", "keep"]
    assert any("recordNumberRecode" in w for w in warnings)


def test_assemble_order_and_blanks():
    df = pd.DataFrame({"b": [1, 2], "a": [3, 4]})
    ids = np.array(["x", "y"], dtype=object)
    out = assemble(df, ["nccrId", "a", "missing", "b"], {"nccrId": ids})
    assert list(out.columns) == ["nccrId", "a", "missing", "b"]
    assert out["missing"].isna().all() and list(out["a"]) == [3, 4]


def test_unique_ids():
    ids = unique_ids(1, 500, 8)
    assert len(set(ids)) == 500 and all(len(i) == 8 and i[0] != "0" for i in ids)
    with pytest.raises(LinkageError):
        unique_ids(1, 10, 1)


def build_tables(plan, keys):
    parent = pd.DataFrame({"nccrId": keys.parent_ids(), "tumorRecordNumber": keys.record_numbers()})
    abm = parent.copy()
    pharm = pd.DataFrame({"nccrId": keys.ids[child_patients(plan.children["PHARM"])]})
    cog = pd.DataFrame({"nccrId": keys.ids[child_patients(plan.children["COG"])]})
    return {"CTC": parent, "ABM": abm, "COG": cog, "PHARM": pharm}


def test_checks_pass_and_catch_a_broken_link():
    plan, keys = keys_for()
    tables = build_tables(plan, keys)
    expected = {s: list(t.columns) for s, t in tables.items()}
    assert all(r["passed"] for r in check_linked(tables, plan, expected))
    verify_linked(tables, plan, expected)

    broken = {**tables, "PHARM": tables["PHARM"].copy()}
    broken["PHARM"].loc[0, "nccrId"] = "f" * 64
    with pytest.raises(LinkageError, match="exists in CTC"):
        verify_linked(broken, plan, expected)

    swapped = {**tables, "ABM": tables["ABM"].iloc[::-1].reset_index(drop=True)}
    with pytest.raises(LinkageError, match="ABM"):
        verify_linked(swapped, plan, expected)

    short = {**tables, "PHARM": tables["PHARM"].iloc[:60]}
    with pytest.raises(LinkageError, match="within tolerance"):
        verify_linked(short, plan, expected)

    reordered = {**tables, "CTC": tables["CTC"][["tumorRecordNumber", "nccrId"]]}
    with pytest.raises(LinkageError, match="key columns first"):
        verify_linked(reordered, plan, {**expected, "CTC": list(reordered["CTC"].columns)})

    duplicated = {**tables, "CTC": pd.concat([tables["CTC"], tables["CTC"].iloc[:1]])}
    with pytest.raises(LinkageError, match="unique"):
        verify_linked(duplicated, plan, expected)
