"""Rules that repair a violating target to NULL, and NULL-aware conformance and fidelity."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric import conformance_report, generate, marginal_fidelity
from synthpediatric.constraints import AllowedValuesConstraint, RuleSet

ROOT = Path(__file__).resolve().parents[1]

TTL = """
@prefix nccr: <https://nccrdataplatform.ccdi.cancer.gov/vocab#> .
@prefix nccr-ds: <https://nccrdataplatform.ccdi.cancer.gov/datasource/> .
@prefix nccr-var: <https://nccrdataplatform.ccdi.cancer.gov/variable/> .
@prefix nccr-vs: <https://nccrdataplatform.ccdi.cancer.gov/valueset/> .
@prefix nccr-cv: <https://nccrdataplatform.ccdi.cancer.gov/code/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
nccr-ds:ctc a nccr:DataSource ; nccr:sourceId "CTC" ;
    nccr:sourceLabel "Consolidated Tumor Case" ; nccr:totalRecordCount 100 .
nccr-var:ctc-sex a nccr:Variable ; rdfs:label "Sex" ; nccr:sourceColumn "sex" ;
    nccr:belongsToSource nccr-ds:ctc ; nccr:hasValueSet nccr-vs:ctc-sex .
nccr-vs:ctc-sex a skos:ConceptScheme .
nccr-cv:ctc-sex-1 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-sex ;
    skos:notation "1" ; skos:prefLabel "Female"@en ; nccr:recordCount 50 .
nccr-cv:ctc-sex-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-sex ;
    skos:notation "2" ; skos:prefLabel "Male"@en ; nccr:recordCount 50 .
nccr-var:ctc-psa a nccr:Variable ; rdfs:label "PSA" ; nccr:sourceColumn "psa" ;
    nccr:belongsToSource nccr-ds:ctc ; nccr:hasValueSet nccr-vs:ctc-psa .
nccr-vs:ctc-psa a skos:ConceptScheme .
nccr-cv:ctc-psa-1 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-psa ;
    skos:notation "1" ; skos:prefLabel "Low"@en ; nccr:recordCount 30 .
nccr-cv:ctc-psa-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-psa ;
    skos:notation "2" ; skos:prefLabel "High"@en ; nccr:recordCount 70 .
"""

NULL_RULE = {
    "type": "allowed_values",
    "name": "psa_male_only",
    "trigger_col": "sex",
    "trigger_values": ["Female"],
    "target_col": "psa",
    "repair_to_null": True,
}


def _dict():
    rdflib = pytest.importorskip("rdflib")
    from synthpediatric.nccr_rdf import build_dictionary

    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return build_dictionary(g, "CTC")


def _ruleset(max_iterations=5):
    return RuleSet.from_dict({"max_iterations": max_iterations, "constraints": [NULL_RULE]})


def test_rule_repairs_target_to_null():
    d = _dict()
    result = generate(d, 2000, rng=1, ruleset=_ruleset())
    df = result.data
    female = df["sex"] == "Female"
    assert female.sum() > 0
    assert df.loc[female, "psa"].isna().all()
    assert df.loc[~female, "psa"].notna().all()
    assert result.repairs["psa_male_only"] > 0


def test_null_rule_is_stable_and_idempotent():
    df = pd.DataFrame({"sex": ["Female", "Male", "Female"], "psa": ["Low", "High", None]})
    rule = AllowedValuesConstraint.from_dict(NULL_RULE)
    assert rule.find_violations(df).tolist() == [True, False, False]
    rule.repair(df, np.random.default_rng(0))
    assert df["psa"].isna().tolist() == [True, False, True]
    assert not rule.find_violations(df).any()


def test_null_trigger_does_not_crash_or_match():
    df = pd.DataFrame({"sex": [None, "Female"], "psa": ["Low", "Low"]})
    rule = AllowedValuesConstraint.from_dict(NULL_RULE)
    assert rule.find_violations(df).tolist() == [False, True]


def test_null_rule_rejects_allowed_values_and_old_rule_needs_them():
    with pytest.raises(ValueError):
        AllowedValuesConstraint.from_dict({**NULL_RULE, "allowed_values": ["Low"]})
    plain = {k: v for k, v in NULL_RULE.items() if k != "repair_to_null"}
    with pytest.raises(ValueError):
        AllowedValuesConstraint.from_dict(plain)


def test_later_string_rule_on_a_null_target_is_repaired_not_ignored():
    # A null in an allowed_values target is out of range, so the string rule repairs it.
    df = pd.DataFrame({"sex": ["Female"], "psa": [None]})
    rule = AllowedValuesConstraint.from_dict(
        {**{k: v for k, v in NULL_RULE.items() if k != "repair_to_null"}, "allowed_values": ["Low"]}
    )
    assert rule.find_violations(df).tolist() == [True]


def test_string_repair_rule_is_unchanged():
    spec = {k: v for k, v in NULL_RULE.items() if k != "repair_to_null"}
    spec["allowed_values"] = ["Low"]
    df = generate(_dict(), 500, rng=2, ruleset=RuleSet.from_dict({"constraints": [spec]})).data
    assert (df.loc[df["sex"] == "Female", "psa"] == "Low").all()
    assert df["psa"].notna().all()


def test_conformance_does_not_flag_nulls_and_counts_them():
    d = _dict()
    df = generate(d, 1000, rng=3, ruleset=_ruleset()).data
    rep = conformance_report(d, df).set_index("variable")
    assert (rep["n_out_of_vocabulary"] == 0).all()
    assert rep.loc["psa", "n_null"] == int(df["psa"].isna().sum()) > 0
    assert rep.loc["sex", "n_null"] == 0


def test_conformance_without_nulls_has_the_legacy_columns():
    d = _dict()
    df = generate(d, 200, rng=3).data
    assert list(conformance_report(d, df).columns) == [
        "variable", "n_out_of_vocabulary", "examples"
    ]


def test_conformance_still_flags_an_invented_label():
    d = _dict()
    df = generate(d, 100, rng=3).data
    df.loc[df.index[0], "psa"] = "Not applicable"
    rep = conformance_report(d, df).set_index("variable")
    assert rep.loc["psa", "n_out_of_vocabulary"] == 1


def test_fidelity_is_computed_among_non_null_values():
    d = _dict()
    n = 20000
    clean = generate(d, n, rng=4).data
    nulled = clean.copy()
    nulled.loc[nulled["sex"] == "Female", "psa"] = None
    a = marginal_fidelity(d, clean).set_index("variable").loc["psa", "tv_distance"]
    b = marginal_fidelity(d, nulled).set_index("variable").loc["psa", "tv_distance"]
    # Blanking an independent half of the rows leaves the remaining distribution close to
    # the target; counting nulls as a category would add about 0.5.
    assert b < 0.05
    assert abs(a - b) < 0.05


def test_fidelity_of_an_all_null_column_is_nan():
    d = _dict()
    df = generate(d, 100, rng=4).data
    df["psa"] = None
    fid = marginal_fidelity(d, df).set_index("variable")
    assert np.isnan(fid.loc["psa", "tv_distance"])


def test_null_is_written_blank_in_csv_and_null_in_parquet(tmp_path):
    df = generate(_dict(), 300, rng=5, ruleset=_ruleset()).data
    df.to_csv(tmp_path / "c.csv", index=False)
    back = pd.read_csv(tmp_path / "c.csv")
    assert back["psa"].isna().sum() == df["psa"].isna().sum() > 0
    assert "nan" not in (tmp_path / "c.csv").read_text().lower()
    pytest.importorskip("pyarrow")
    df.to_parquet(tmp_path / "c.parquet", index=False)
    assert pd.read_parquet(tmp_path / "c.parquet")["psa"].isna().sum() == df["psa"].isna().sum()


def test_shipped_ctc_rules_repair_prostate_variables_to_null():
    spec = json.loads((ROOT / "examples" / "ctc_consistency_rules.json").read_text())
    nulls = [c for c in spec["constraints"] if c.get("repair_to_null")]
    assert len(nulls) == 6
    assert {c["target_col"] for c in nulls} == {
        "gleasonPatternClinicalRecode", "gleasonPatternPathologicRecode",
        "gleasonScoreClinicalRecode", "gleasonScorePathologicRecode",
        "gleasonTertiaryPattern", "psaLabValueRecode",
    }
    assert "Not applicable" not in json.dumps(spec["constraints"])
    RuleSet.from_dict(spec)


def test_cookbook_null_repair_example_loads_and_runs():
    text = (ROOT / "docs" / "cookbook.md").read_text()
    section = text.split("## Not applicable values: repair to null", 1)[1]
    block = section.split("```json", 1)[1].split("```", 1)[0]
    rule = json.loads(block)
    assert rule["repair_to_null"] is True
    rule.update(target_col="psa")
    result = generate(_dict(), 500, rng=6, ruleset=RuleSet.from_dict({"constraints": [rule]}))
    assert result.data.loc[result.data["sex"] == "Female", "psa"].isna().all()


def test_recipe_g_rules_file_keeps_the_label_repair():
    spec = json.loads((ROOT / "examples" / "ctc_consistency_rules_label.json").read_text())
    labelled = [c for c in spec["constraints"] if c.get("allowed_values") == ["Not applicable"]]
    assert len(labelled) == 6
    assert "ctc_consistency_rules_label.json" in (
        ROOT / "examples" / "cookbook" / "g_consistency_rules.yaml"
    ).read_text()
