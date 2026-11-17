"""Null-code classifier, the null-code map, and the not-applicable fraction."""
import json
from pathlib import Path

import pandas as pd
import pytest

from synthpediatric import nullcodes as nc
from synthpediatric.cli import main
from synthpediatric.config import ConfigError
from synthpediatric.nccr_rdf import build_dictionary, load_graph
from synthpediatric.recipe import run_recipe, write_run

DATA = Path(__file__).parent / "data"
TTL = str(DATA / "na_fraction.ttl")


def kind(desc, code="", **kw):
    return nc.classify(code, desc, **kw).kind


@pytest.mark.parametrize("desc, expected", [
    ("Not applicable: Information not collected for this case", "not_applicable"),
    ("Not Applicable-Patient Reported as Deceased", "not_applicable"),
    ("Not applicable for this case", "not_applicable"),
    ("Classification For This Diagnosis Does Not Include This Level", "not_applicable"),
    ("Diagnosed prior to 2023", "not_applicable"),
    ("Not documented in medical record\n Gleason Tertiary Pattern not assessed", "unknown"),
    ("Unknown", "unknown"),
    ("Unknown or not applicable", "unknown"),
    ("It is unknown if radiation therapy was recommended or administered.", "unknown"),
    ("Radiation therapy was recommended, but it is unknown if it was administered.", "unknown"),
    ("Missing", "no_data"),
    ("No Data Available for Patient for This Month at Time of Linkage", "no_data"),
    ("Not coded", "no_data"),
    ("No prostatectomy done", "not_performed"),
    ("No needle core biopsy/TURP performed", "not_performed"),
    ("Surgery of the primary site was not performed because the patient died", "not_performed"),
    ("Male", "real"),
    ("1-89 nodes were examined (code the exact number of regional lymph nodes examined)", "real"),
])
def test_classifier_kinds(desc, expected):
    assert kind(desc) == expected


@pytest.mark.parametrize("desc", [
    "Ie Unspecified and other specified leukemias",
    "XII OTHER AND UNSPECIFIED MALIGNANT NEOPLASMS",
    "IIIf Unspecified intracranial and intraspinal neoplasms",
    "Not classified by SEER or in situ",
    "Not classified by ICCC or in situ",
    "Primary pattern 3, secondary pattern unknown",
    "Bilateral involvement at time of diagnosis, lateral origin unknown for a single primary",
    "Sequence unknown, but both surgery and radiation were given",
    "Sequence indicator for patient with at least one radiation record with missing start date",
    "Non-Hispanic American Indian/Alaska Native",
    "Refused (1988+)",
])
def test_classifier_false_positives_stay_real(desc):
    res = nc.classify("9", desc)
    assert res.kind == "real"


def test_it_is_unknown_is_not_an_iccc_group():
    # 'It' starts like a Roman numeral; the ICCC rule must not swallow it.
    assert kind("It is unknown whether nodes were examined; not stated") == "unknown"


def test_borderline_is_flagged():
    assert nc.classify("9", "Unknown or not applicable").borderline
    assert not nc.classify("X8", "Not applicable: Information not collected").borderline


def test_overrides_beat_rules_and_most_specific_wins(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"overrides": {
        "*.*.77": {"kind": "no_data", "reason": "site code"},
        "CTC.age.77": {"kind": "real", "reason": "77 years"},
    }}))
    ov = nc.load_overrides(f)
    assert nc.classify("77", "Site-specific codes", source="MCE", variable="x", overrides=ov).kind \
        == "no_data"
    assert nc.classify("77", "77 years", source="CTC", variable="age", overrides=ov).kind == "real"
    assert nc.classify("78", "77 years", source="CTC", variable="age", overrides=ov).kind == "real"


def test_overrides_file_is_validated(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"overrides": {"CTC.x.9": {"kind": "maybe"}}}))
    with pytest.raises(ValueError, match="valid kinds"):
        nc.load_overrides(f)
    f.write_text(json.dumps({"overrides": {"x": {"kind": "real"}}}))
    with pytest.raises(ValueError, match="SOURCE.variable.code"):
        nc.load_overrides(f)


def test_map_on_fixture_and_summary():
    codes = nc.collect_codes(load_graph([TTL]))
    data = nc.build_map(codes, nc.load_overrides(), generated_from="fixture")
    gl = data["sources"]["CTC"]["gleason"]
    assert gl["null_codes"]["X8"]["kind"] == "not_applicable"
    assert gl["null_codes"]["X9"]["kind"] == "unknown"
    assert gl["n_real"] == 2
    assert data["counts"]["CTC"]["not_applicable"] == 2  # gleason X8, stage 8
    text = nc.summary_markdown(data)
    assert "Values per source and kind" in text and "False positives" in text


def test_shipped_map_is_consistent_with_the_rules():
    data = nc.load_map()
    assert data["schema"] == nc.MAP_SCHEMA
    ov = nc.load_overrides()
    n = 0
    for sid, variables in data["sources"].items():
        for var, spec in variables.items():
            for code, e in spec["null_codes"].items():
                assert e["kind"] in nc.NULL_KINDS
                again = nc.classify(code, e["description"], source=sid, variable=var, overrides=ov)
                assert again.kind == e["kind"]
                n += 1
    assert n == data["totals"]["null_type"]
    assert set(data["counts"]) == {
        "CTC", "ABM", "CCDI", "COG", "MCD", "MCE", "MCP", "PHARM", "RO"}


def test_nullcodes_command(tmp_path, capsys):
    out, summary = tmp_path / "map.json", tmp_path / "summary.md"
    assert main(["nullcodes", TTL, "--source", "CTC", "-o", str(out),
                 "--summary", str(summary)]) == 0
    data = json.loads(out.read_text())
    assert list(data["sources"]) == ["CTC"]
    assert summary.read_text().startswith("# Null-code map")
    assert "null-type" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The fraction
# --------------------------------------------------------------------------- #

def run(tmp_path, n=4000, **extra):
    cfg = {"metadata": TTL, "source": "CTC", "n": n, "seed": 5, "profile": "marginals_only"}
    cfg.update(extra)
    bundle = run_recipe(cfg)
    out = write_run(bundle, tmp_path)
    return bundle, json.loads((out / "manifest.json").read_text()), out


def test_loader_attaches_counts_and_kinds():
    d = build_dictionary(load_graph([TTL]), "CTC")
    info = d.variables["gleason"].na_info
    assert info["covered"] == 50 and info["total"] == 10000
    assert info["kinds"]["Not applicable"] == "not_applicable"
    assert d.variables["sex"].na_info["covered"] == 10000


def test_fraction_on_the_fixture(tmp_path):
    bundle, m, out = run(tmp_path)
    df = bundle["data"]
    n = len(df)
    fr = m["na_fraction"]["variables"]
    # sub-population with an uncounted not-applicable code: that code
    g = fr["gleason"]
    assert g["status"] == "applied" and g["blank"] is False and g["code"] == "Not applicable"
    assert g["covered_share"] == pytest.approx(0.005)
    assert (df["gleason"] == "Not applicable").mean() == pytest.approx(0.995, abs=1 / n)
    assert g["generated_share"] == pytest.approx(0.995, abs=1 / n)
    assert set(df["gleason"].dropna()) <= {"Score 6", "Score 7", "Not applicable"}
    # no not-applicable code: blank, never 'Unknown'
    p = fr["psa"]
    assert p["blank"] is True and p["code"] is None
    assert df["psa"].isna().mean() == pytest.approx(0.99, abs=1 / n)
    assert "Unknown" not in set(df["psa"].dropna())
    # fully covered and suppression-only: untouched
    assert "sex" not in fr and df["sex"].notna().all()
    assert fr["grade"]["status"] == "skipped" and fr["grade"]["reason"] == "suppression_only"
    assert df["grade"].notna().all()
    # its not-applicable code already carries a count: the same code takes the uncovered
    # share once. 1000 counted of 10000, plus the 2000 uncovered: 30% in all.
    s = fr["stage"]
    assert s["status"] == "applied" and s["code"] == "Not applicable" and s["code_counted"]
    assert s["generated_share"] == pytest.approx(0.2, abs=1 / n)
    assert (df["stage"] == "Not applicable").mean() == pytest.approx(0.2 + 0.8 * 1 / 8, abs=0.03)
    # the share of the code in the table: the uncovered 20% plus the published 10%
    assert s["code_share_target"] == pytest.approx(0.3)
    assert s["code_share_generated"] == (df["stage"] == "Not applicable").mean()
    assert fr["gleason"]["code_share_target"] == pytest.approx(0.995)
    assert m["na_fraction"]["settings"]["mode_supplied_by"] == "default"


def test_conformance_and_fidelity_report_the_fraction(tmp_path):
    bundle, m, out = run(tmp_path, n=20000)
    conf = pd.read_csv(out / "conformance.csv")
    assert (conf["n_out_of_vocabulary"] == 0).all()
    nulls = dict(zip(conf["variable"], conf["n_null"]))
    assert nulls["psa"] == m["na_fraction"]["variables"]["psa"]["generated_rows"] > 0
    assert m["coverage_null_counts"]["psa"] == nulls["psa"]
    fid = pd.read_csv(out / "fidelity.csv").set_index("variable")
    # among the rows that kept a counted value the split is 30:20 for gleason, 40:60 for psa
    assert fid.loc["gleason", "tv_distance"] < 0.2
    assert fid.loc["psa", "tv_distance"] < 0.2


def test_same_seed_same_table_and_counted_values_unchanged(tmp_path):
    a, _, _ = run(tmp_path / "a")
    b, _, _ = run(tmp_path / "b")
    pd.testing.assert_frame_equal(a["data"], b["data"])
    off, _, _ = run(tmp_path / "c", na_fraction="off")
    assert off["data"]["sex"].tolist() == a["data"]["sex"].tolist()  # untouched variable
    assert off["data"]["gleason"].notna().all()


def test_switch_off_in_config_is_recorded(tmp_path):
    bundle, m, _ = run(tmp_path, na_fraction=False)  # YAML 'off' arrives as False
    assert bundle["na_plan"] is None
    assert m["na_fraction"]["settings"]["mode"] == "off"
    assert m["na_fraction"]["settings"]["mode_supplied_by"] == "config"
    assert bundle["data"]["psa"].notna().all()


def test_per_variable_off_and_on(tmp_path):
    _, m, _ = run(tmp_path, na_fraction={"variables": {"psa": "off", "grade": "on"}})
    fr = m["na_fraction"]["variables"]
    assert fr["psa"]["status"] == "skipped" and fr["psa"]["reason"] == "off_by_config"
    assert fr["psa"]["supplied_by"] == "config"
    assert fr["grade"]["status"] == "applied" and fr["grade"]["blank"] is True  # forced on
    assert fr["gleason"]["status"] == "applied"
    # global off, one variable forced on
    bundle, m2, _ = run(
        tmp_path / "x", na_fraction={"mode": "off", "variables": {"gleason": "on"}}
    )
    assert bundle["na_plan"].applied == ["gleason"]


def test_min_share_controls_materiality(tmp_path):
    _, m, _ = run(tmp_path, na_fraction={"min_share": 0.999})
    fr = m["na_fraction"]["variables"]
    assert fr["gleason"]["reason"] == "below_min_share"
    assert fr["psa"]["reason"] == "below_min_share"


def test_config_validation():
    base = {"metadata": TTL, "source": "CTC", "n": 50, "seed": 1}
    with pytest.raises(ConfigError, match="Did you mean 'gleason'"):
        run_recipe({**base, "na_fraction": {"variables": {"gleeson": "off"}}})
    with pytest.raises(ConfigError, match="unknown key"):
        run_recipe({**base, "na_fraction": {"enabled": True}})
    with pytest.raises(ConfigError, match="min_share"):
        run_recipe({**base, "na_fraction": {"min_share": 2}})
    with pytest.raises(ConfigError, match="unknown value"):
        run_recipe({**base, "na_fraction": {"variables": {"psa": "maybe"}}})


def test_rule_that_sets_a_distribution_owns_the_variable(tmp_path):
    bundle, m, _ = run(
        tmp_path, targets={"marginals": {"gleason": {"Score 6": 0.5, "Score 7": 0.5}}},
        profile="marginals_only",
    )
    e = m["na_fraction"]["variables"]["gleason"]
    assert e["status"] == "skipped" and e["reason"] == "set_by_rule"
    assert bundle["data"]["gleason"].notna().all()


def test_constraint_repairs_run_after_the_fraction(tmp_path):
    rules = [
        {"type": "allowed_values", "name": "female_gleason", "trigger_col": "sex",
         "trigger_values": ["Female"], "target_col": "gleason",
         "allowed_values": ["Not applicable"]},
        {"type": "allowed_values", "name": "female_psa", "trigger_col": "sex",
         "trigger_values": ["Female"], "target_col": "psa", "repair_to_null": True},
    ]
    bundle, m, _ = run(tmp_path, profile="standard",
                       constraints={"rules": rules})
    df = bundle["data"]
    fem = df[df["sex"] == "Female"]
    assert (fem["gleason"] == "Not applicable").all()
    assert fem["psa"].isna().all()
    # the counted values that survive are still male rows
    assert set(df.loc[df["gleason"] != "Not applicable", "sex"]) <= {"Male"}


def test_json_dictionary_gets_no_fraction(tmp_path):
    spec = {"name": "t", "variables": [{"name": "a", "values": [
        {"value": "x", "count": 1}, {"value": "y", "count": 1}]}]}
    p = tmp_path / "d.json"
    p.write_text(json.dumps(spec))
    bundle = run_recipe({"metadata": str(p), "n": 50, "seed": 1, "profile": "marginals_only"})
    assert bundle["na_plan"] is None
    out = write_run(bundle, tmp_path / "o")
    assert "na_fraction" not in json.loads((out / "manifest.json").read_text())
