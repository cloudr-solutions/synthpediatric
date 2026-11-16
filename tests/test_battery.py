"""Tests for the DRAFT clinical consistency battery (offline)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric import DataDictionary, generate
from synthpediatric.battery import (
    FAMILIES,
    BatteryError,
    battery_from_dict,
    distribution_detail,
    kaplan_meier,
    load_battery,
    run_battery,
    write_report,
)
from synthpediatric.constraints import RuleSet
from synthpediatric.recipe import run_recipe

ROOT = Path(__file__).parent.parent
BATTERY = ROOT / "examples" / "battery" / "ctc_battery_draft.json"
VOCAB = json.loads((Path(__file__).parent / "data" / "ctc_battery_vocab.json").read_text("utf-8"))

CERVIX = "XIf7 Carcinomas of cervix uteri"
ALL_GROUP = "Ia1 Precursor cell leukemias"
RB = "V RETINOBLASTOMA"


def _dictionary() -> DataDictionary:
    """Real CTC column names and labels (from the published metadata), published counts."""
    spec = {
        "name": "ctc-battery-vocab",
        "variables": [
            {"name": col, "values": [{"value": k, "count": v} for k, v in vals.items()]}
            for col, vals in VOCAB.items()
        ],
    }
    return DataDictionary.from_dict(spec)


@pytest.fixture(scope="module")
def battery():
    return load_battery(BATTERY)


def _raw_cohort(n=4000, seed=1) -> pd.DataFrame:
    return generate(_dictionary(), n=n, rng=seed).data


def _referenced_values(battery):
    refs = []
    for c in battery.constraints:
        refs += [(c.trigger_col, v) for v in c.trigger_values]
        refs += [(c.target_col, v) for v in c.allowed_values]
    for k in battery.checks:
        refs += [(k["group_col"], v) for v in k.get("group_values", [])]
        refs += [(k["target_col"], v) for v in k.get("focus_values", [])]
        for level in k.get("stage_order", []):
            refs += [(k["stage_col"], v) for v in level]
    return refs


# ---- file structure ------------------------------------------------------------------

def test_file_is_draft_everywhere_and_covers_all_families(battery):
    assert battery.meta["status"] == "draft"
    statuses = [m["status"] for m in battery.constraint_meta.values()]
    statuses += [c["status"] for c in battery.checks]
    assert set(statuses) == {"draft"}
    fams = {m["family"] for m in battery.constraint_meta.values()}
    fams |= {c["family"] for c in battery.checks} | {r["family"] for r in battery.roadmap}
    assert fams == set(FAMILIES)


def test_every_column_and_value_is_real_ctc_metadata(battery):
    """Targets of repairs included: a repair may only write a real permissible value."""
    for col, value in _referenced_values(battery):
        assert col in VOCAB, col
        assert value in VOCAB[col], (col, value)
    for c in battery.constraints:
        assert set(c.allowed_values) <= set(VOCAB[c.target_col])


def test_ids_are_unique_and_malformed_files_are_rejected(battery):
    ids = battery.ids()
    assert len(ids) == len(set(ids))
    spec = json.loads(BATTERY.read_text("utf-8"))
    spec["constraints"][0]["status"] = "maybe"
    with pytest.raises(BatteryError):
        battery_from_dict(spec)
    spec = json.loads(BATTERY.read_text("utf-8"))
    del spec["constraints"][0]["source_statement"]
    with pytest.raises(BatteryError):
        battery_from_dict(spec)


def test_worksheet_lists_every_statement_id(battery):
    text = (ROOT / "docs" / "battery-verification.md").read_text("utf-8")
    for item_id in battery.ids():
        assert f"| {item_id} |" in text, item_id


def test_status_filter_drops_rejected_rules():
    spec = json.loads(BATTERY.read_text("utf-8"))
    spec["constraints"][0]["status"] = "rejected"
    b = battery_from_dict(spec)
    assert b.ruleset(statuses=("draft", "verified")).constraints == []
    assert len(b.ruleset().constraints) == 1


# ---- hard rules: repair and check ----------------------------------------------------

def test_hard_rule_repairs_violating_records_and_check_agrees(battery):
    raw = _raw_cohort()
    before = run_battery(raw, battery, min_cell=1)
    row = before[before["id"] == "S1.3"].iloc[0]
    assert row["n_flagged"] > 0 and row["result"] == "VIOLATIONS"

    result = generate(_dictionary(), n=4000, rng=1, ruleset=battery.ruleset())
    assert result.repairs["cervical_carcinoma_is_female"] == int(row["n_flagged"])
    after = run_battery(result.data, battery, min_cell=1)
    row = after[after["id"] == "S1.3"].iloc[0]
    assert row["n_flagged"] == 0 and row["result"] == "ok"
    cervix = result.data[result.data["iccc2017ExtendedRecode"] == CERVIX]
    assert len(cervix) > 0 and (cervix["sex"] == "Female").all()


def test_each_hard_rule_repairs_a_hand_built_violation(battery):
    for c in battery.constraints:
        df = pd.DataFrame({
            c.trigger_col: [c.trigger_values[0]] * 3,
            c.target_col: ["__not_allowed__"] * 3,
        })
        assert c.find_violations(df).sum() == 3
        fixed, summary = battery.ruleset().apply(df, np.random.default_rng(0))
        assert summary[c.name] == 3
        assert fixed[c.target_col].isin(c.allowed_values).all()
        assert c.find_violations(fixed).sum() == 0


def test_battery_file_runs_through_the_config_path(tmp_path):
    d = {"name": "v", "variables": [
        {"name": col, "values": [{"value": k, "count": v} for k, v in vals.items()]}
        for col, vals in VOCAB.items()]}
    (tmp_path / "dict.json").write_text(json.dumps(d), encoding="utf-8")
    bundle = run_recipe({
        "name": "battery", "metadata": str(tmp_path / "dict.json"), "n": 3000, "seed": 5,
        "constraints": {"file": str(BATTERY)},
    })
    assert bundle["result"].repairs["cervical_carcinoma_is_female"] > 0
    data = bundle["data"]
    assert (data.loc[data["iccc2017ExtendedRecode"] == CERVIX, "sex"] == "Female").all()


def test_legacy_rule_loading_ignores_battery_metadata():
    rs = RuleSet.from_json(BATTERY)
    assert [c.name for c in rs.constraints] == ["cervical_carcinoma_is_female"]


# ---- suppression -----------------------------------------------------------------------

def test_small_counts_are_suppressed_and_derived_values_blanked(battery):
    df = _raw_cohort(n=500)
    df = df[df["iccc2017ExtendedRecode"] != CERVIX]
    extra = pd.DataFrame({"iccc2017ExtendedRecode": [CERVIX] * 5, "sex": ["Male"] * 5})
    df = pd.concat([df, extra.reindex(columns=df.columns)], ignore_index=True)
    row = run_battery(df, battery).query("id == 'S1.3'").iloc[0]
    assert np.isnan(row["n_eligible"]) and np.isnan(row["n_flagged"])
    assert np.isnan(row["cohort_value"]) and row["result"] == "suppressed"
    shown = run_battery(df, battery, min_cell=5).query("id == 'S1.3'").iloc[0]
    assert shown["n_flagged"] == 5 and shown["result"] == "VIOLATIONS"


def test_zero_counts_are_shown(battery):
    df = pd.DataFrame({"iccc2017ExtendedRecode": [CERVIX] * 20, "sex": ["Female"] * 20})
    row = run_battery(df, battery).query("id == 'S1.3'").iloc[0]
    assert row["n_flagged"] == 0 and row["n_eligible"] == 20 and row["result"] == "ok"


def test_default_threshold_is_16(battery):
    df = pd.DataFrame({"iccc2017ExtendedRecode": [CERVIX] * 15, "sex": ["Female"] * 15})
    row = run_battery(df, battery).query("id == 'S1.3'").iloc[0]
    assert np.isnan(row["n_eligible"])


# ---- probabilistic checks ----------------------------------------------------------------

def _age_cohort(ages, group=RB):
    return pd.DataFrame({"iccc2017ExtendedRecode": group, "ageRecode19Groups": ages})


def test_distribution_check_needs_reference_then_compares(battery):
    cohort = _age_cohort(["00 years"] * 30 + ["01-04 years"] * 30)
    table = run_battery(cohort, battery)
    assert table.query("id == 'S2.1'").iloc[0]["result"] == "needs_reference"
    same = run_battery(cohort, battery, reference=cohort).query("id == 'S2.1'").iloc[0]
    assert same["result"] == "compared" and same["tvd"] == pytest.approx(0.0)
    other = _age_cohort(["15-19 years"] * 60)
    far = run_battery(cohort, battery, reference=other).query("id == 'S2.1'").iloc[0]
    assert far["tvd"] == pytest.approx(1.0)
    pub = run_battery(cohort, battery, published={"S2.1": {"00 years": 1, "01-04 years": 1}})
    assert pub.query("id == 'S2.1'").iloc[0]["tvd"] == pytest.approx(0.0)


def test_distribution_detail_suppresses_small_cells(battery):
    check = next(c for c in battery.checks if c["id"] == "S2.1")
    cohort = _age_cohort(["00 years"] * 30 + ["01-04 years"] * 3)
    detail = distribution_detail(cohort, check, reference=cohort)
    small = detail[detail["value"] == "01-04 years"].iloc[0]
    assert np.isnan(small["n_cohort"]) and np.isnan(small["share_cohort"])


def test_focus_share_is_reported(battery):
    group = pd.DataFrame({
        "iccc2017ExtendedRecode": ALL_GROUP,
        "radiationRecode": ["None/Unknown"] * 45 + ["Beam radiation"] * 15,
    })
    row = run_battery(group, battery, reference=group).query("id == 'S3.3'").iloc[0]
    assert row["cohort_value"] == pytest.approx(0.75)
    assert row["difference"] == pytest.approx(0.0)


def test_age_outlier_flag_counts_records_far_from_reference(battery):
    ref = _age_cohort(["00 years"] * 50 + ["01-04 years"] * 50 + ["05-09 years"] * 50)
    far = _age_cohort(["00 years"] * 20 + ["65-69 years"] * 20)
    row = run_battery(far, battery, reference=ref).query("id == 'S2.7'").iloc[0]
    assert row["n_flagged"] == 20 and row["cohort_value"] == pytest.approx(0.5)
    assert row["reference_value"] == pytest.approx(0.0)
    assert run_battery(far, battery).query("id == 'S2.7'").iloc[0]["result"] == "needs_reference"


def test_kaplan_meier_matches_hand_value():
    t = np.array([1.0, 2.0, 3.0, 4.0])
    e = np.array([1, 0, 1, 0])
    assert kaplan_meier(t, e, 10) == pytest.approx((1 - 1 / 4) * (1 - 1 / 2))
    assert kaplan_meier(t, e, 0.5) == 1.0


def _surv(n, deaths, group=ALL_GROUP, stage="Localized only", gcol="iccc2017ExtendedRecode"):
    event = np.zeros(n, dtype=int)
    event[:deaths] = 1
    return pd.DataFrame({
        gcol: group, "icccMajor": "I. Leukemias, Myeloproliferative And Myelodysplastic Diseases",
        "combinedSsPubDetailed": stage, "months": np.full(n, 12.0), "event": event,
    })


def test_survival_check_without_survival_columns_is_not_evaluable(battery):
    row = run_battery(_age_cohort(["00 years"] * 40), battery).query("id == 'S4.2'").iloc[0]
    assert row["result"] == "not_evaluable"


def test_five_year_survival_uses_draft_target_unless_reference_given(battery):
    cohort = _surv(100, 20)
    row = run_battery(cohort, battery).query("id == 'S4.2'").iloc[0]
    assert row["cohort_value"] == pytest.approx(0.8)
    assert row["reference_source"] == "draft_target" and row["reference_value"] == 0.9
    row = run_battery(cohort, battery, reference=_surv(100, 10)).query("id == 'S4.2'").iloc[0]
    assert row["reference_source"] == "reference_data"
    assert row["difference"] == pytest.approx(-0.1)


def test_stage_monotonicity_flags_groups_out_of_order(battery):
    ordered = pd.concat([
        _surv(40, 2, stage="Localized only"),
        _surv(40, 10, stage="Regional lymph nodes involved only"),
        _surv(40, 25, stage="Distant site(s)/node(s) involved"),
    ])
    row = run_battery(ordered, battery).query("id == 'S4.1'").iloc[0]
    assert row["n_eligible"] == 1 and row["n_flagged"] == 0
    flipped = pd.concat([
        _surv(40, 25, stage="Localized only"),
        _surv(40, 2, stage="Distant site(s)/node(s) involved"),
    ])
    row = run_battery(flipped, battery).query("id == 'S4.1'").iloc[0]
    assert row["n_flagged"] == 1 and row["cohort_value"] == 1.0


def test_roadmap_items_are_listed_as_not_implementable(battery):
    table = run_battery(_raw_cohort(n=200), battery)
    road = table[table["kind"] == "roadmap"]
    assert len(road) == len(battery.roadmap)
    assert set(road["result"]) == {"not_implementable"}
    assert road["note"].str.len().min() > 0


def test_report_runs_end_to_end_and_writes_csv(battery, tmp_path):
    result = generate(_dictionary(), n=3000, rng=2, ruleset=battery.ruleset())
    table = run_battery(result.data, battery)
    assert list(table["status"].unique()) == ["draft"]
    assert table.query("id == 'S1.3'").iloc[0]["result"] in ("ok", "suppressed")
    out = write_report(table, tmp_path / "sub" / "report.csv")
    assert len(pd.read_csv(out)) == len(table)
