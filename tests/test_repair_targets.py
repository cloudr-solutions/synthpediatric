"""Repairs to the variable's own metadata code, NULL repairs, and strict checks of targets."""
import json
from pathlib import Path

import pytest

from synthpediatric import conformance_report
from synthpediatric.cli import main
from synthpediatric.config import ConfigError
from synthpediatric.recipe import run_recipe, write_run

ROOT = Path(__file__).resolve().parents[1]

# A Gleason-like variable whose X8 label has a line break, as gleasonTertiaryPattern does in
# the real metadata, and a PSA-like variable with no not-applicable code.
X8 = (
    "Not applicable: Information not collected for this case  \n"
    " (If this information is required by your standard setter, use of code X8 may result "
    "in an edit error.)"
)
TTL = f"""
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
    skos:notation "1" ; skos:prefLabel "Male"@en ; nccr:recordCount 50 .
nccr-cv:ctc-sex-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-sex ;
    skos:notation "2" ; skos:prefLabel "Female"@en ; nccr:recordCount 50 .
nccr-var:ctc-gl a nccr:Variable ; rdfs:label "Tertiary" ; nccr:sourceColumn "tertiary" ;
    nccr:belongsToSource nccr-ds:ctc ; nccr:hasValueSet nccr-vs:ctc-gl .
nccr-vs:ctc-gl a skos:ConceptScheme .
nccr-cv:ctc-gl-1 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-gl ;
    skos:notation "10" ; skos:prefLabel "Tertiary pattern 1"@en ; nccr:recordCount 40 .
nccr-cv:ctc-gl-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-gl ;
    skos:notation "X8" ; skos:prefLabel {json.dumps(X8)}@en ; nccr:recordCount 0 .
nccr-cv:ctc-gl-3 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-gl ;
    skos:notation "X9" ; skos:prefLabel "Not documented"@en ; nccr:recordCount 60 .
nccr-var:ctc-psa a nccr:Variable ; rdfs:label "PSA" ; nccr:sourceColumn "psa" ;
    nccr:belongsToSource nccr-ds:ctc ; nccr:hasValueSet nccr-vs:ctc-psa .
nccr-vs:ctc-psa a skos:ConceptScheme .
nccr-cv:ctc-psa-1 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-psa ;
    skos:notation "00.1" ; skos:prefLabel "Low"@en ; nccr:recordCount 30 .
nccr-cv:ctc-psa-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-psa ;
    skos:notation "XX.9" ; skos:prefLabel "Unknown"@en ; nccr:recordCount 70 .
"""


def _rule(target, trigger="Female", **extra):
    return {"type": "allowed_values", "name": f"{target}_male_only", "trigger_col": "sex",
            "trigger_values": [trigger], "target_col": target, **extra}


LABEL_RULES = [_rule("tertiary", allowed_values=[X8]), _rule("psa", repair_to_null=True)]
CODE_RULES = [_rule("tertiary", "2", allowed_values=["X8"]),
              _rule("psa", "2", repair_to_null=True)]


@pytest.fixture
def ttl(tmp_path):
    pytest.importorskip("rdflib")
    path = tmp_path / "mini.ttl"
    path.write_text(TTL, encoding="utf-8")
    return str(path)


def _cfg(ttl, rules, **extra):
    return {"metadata": ttl, "source": "CTC", "n": 2000, "seed": 7, "profile": "standard",
            "constraints": {"rules": rules}, **extra}


def test_label_mode_repairs_to_the_exact_metadata_label_and_psa_to_null(ttl):
    bundle = run_recipe(_cfg(ttl, LABEL_RULES))
    df = bundle["data"]
    female = df["sex"] == "Female"
    assert female.sum() > 0
    assert (df.loc[female, "tertiary"] == X8).all()
    assert df.loc[female, "psa"].isna().all()
    assert df.loc[~female, "psa"].notna().all()
    assert bundle["result"].repairs["tertiary_male_only"] > 0
    rep = conformance_report(bundle["dictionary"], df).set_index("variable")
    assert (rep["n_out_of_vocabulary"] == 0).all()


def test_code_mode_repairs_to_the_notation(ttl):
    df = run_recipe(_cfg(ttl, CODE_RULES, value_mode="code"))["data"]
    female = df["sex"] == "2"
    assert female.sum() > 0
    assert (df.loc[female, "tertiary"] == "X8").all()
    assert df.loc[female, "psa"].isna().all()


def test_an_invented_target_label_is_a_config_error_with_a_suggestion(ttl):
    rules = [_rule("tertiary", allowed_values=["Not applicable"])]
    with pytest.raises(ConfigError) as exc:
        run_recipe(_cfg(ttl, rules))
    message = str(exc.value)
    for needle in ["constraints.rules[0].allowed_values", "unknown category 'Not applicable'",
                   "Did you mean", "not a permissible value of 'tertiary'"]:
        assert needle in message, f"{needle!r} not in: {message}"


def test_a_label_without_its_line_break_is_rejected(ttl):
    flat = " ".join(X8.split())
    with pytest.raises(ConfigError, match="Did you mean"):
        run_recipe(_cfg(ttl, [_rule("tertiary", allowed_values=[flat])]))


def test_a_label_in_code_mode_is_rejected(ttl):
    with pytest.raises(ConfigError, match="not a permissible value of 'tertiary'"):
        run_recipe(_cfg(ttl, [_rule("tertiary", "2", allowed_values=[X8])], value_mode="code"))


def test_not_strict_turns_a_bad_target_into_a_warning(ttl):
    bundle = run_recipe(_cfg(ttl, [_rule("tertiary", allowed_values=["Not applicable"])],
                             strict=False))
    assert any("Not applicable" in w and "strict: false" in w for w in bundle["warnings"])


def test_generate_rules_checks_the_target(ttl, tmp_path):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"constraints": [_rule("tertiary", allowed_values=["X8"])]}))
    args = ["generate", ttl, "--source", "CTC", "-n", "50", "--seed", "1",
            "-o", str(tmp_path / "x.csv"), "--rules", str(rules)]
    with pytest.raises(SystemExit, match="config error: .*unknown category 'X8'"):
        main(args)
    rules.write_text(json.dumps({"constraints": LABEL_RULES}))
    assert main(args) == 0


def test_manifest_coverage_has_null_counts_only_when_there_are_nulls(ttl, tmp_path):
    bundle = run_recipe(_cfg(ttl, LABEL_RULES))
    manifest = json.loads((write_run(bundle, tmp_path / "a") / "manifest.json").read_text())
    n_null = int(bundle["data"]["psa"].isna().sum())
    assert manifest["coverage_null_counts"] == {"psa": n_null}
    assert n_null > 0
    plain = run_recipe(_cfg(ttl, [_rule("tertiary", allowed_values=[X8])]))
    manifest = json.loads((write_run(plain, tmp_path / "b") / "manifest.json").read_text())
    assert "coverage_null_counts" not in manifest


def test_shipped_ctc_rules_use_the_metadata_codes():
    for name, x8 in (("ctc_consistency_rules.json", None), ("ctc_consistency_rules_code.json",
                                                            "X8")):
        spec = json.loads((ROOT / "examples" / name).read_text())
        by_target = {c["target_col"]: c for c in spec["constraints"]}
        gleason = [t for t in by_target if t.startswith("gleason")]
        assert len(gleason) == 5
        for target in gleason:
            (value,) = by_target[target]["allowed_values"]
            if x8:
                assert value == x8
            else:
                assert value.startswith("Not applicable: Information not collected for this case")
        assert by_target["psaLabValueRecode"]["repair_to_null"] is True
        assert "allowed_values" not in by_target["psaLabValueRecode"]
    text = (ROOT / "examples" / "ctc_consistency_rules.json").read_text()
    assert text.count("Not applicable: Information not collected for this case  \\n") == 1
