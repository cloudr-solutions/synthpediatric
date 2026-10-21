"""Tests for full-coverage loading (uniform fallback), coverage + conformance."""

import pandas as pd
import pytest

from synthpediatric import (
    assert_conformant,
    conformance_report,
    coverage_report,
    generate,
)

# Inline NCCR-style TTL: 'sex' has record counts; 'race' has a value set but NO counts.
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
    skos:notation "1" ; skos:prefLabel "Female"@en ; nccr:recordCount 60 .
nccr-cv:ctc-sex-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-sex ;
    skos:notation "2" ; skos:prefLabel "Male"@en ; nccr:recordCount 40 .

nccr-var:ctc-race a nccr:Variable ; rdfs:label "Race" ; nccr:sourceColumn "race" ;
    nccr:belongsToSource nccr-ds:ctc ; nccr:hasValueSet nccr-vs:ctc-race .
nccr-vs:ctc-race a skos:ConceptScheme .
nccr-cv:ctc-race-1 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-race ;
    skos:notation "1" ; skos:prefLabel "White"@en .
nccr-cv:ctc-race-2 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-race ;
    skos:notation "2" ; skos:prefLabel "Black"@en .
nccr-cv:ctc-race-3 a skos:Concept, nccr:CodeValue ; skos:inScheme nccr-vs:ctc-race ;
    skos:notation "3" ; skos:prefLabel "Asian"@en .
"""


def _dict():
    rdflib = pytest.importorskip("rdflib")
    from synthpediatric.nccr_rdf import build_dictionary

    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return build_dictionary(g, "CTC")


def test_no_frequency_variable_included_as_uniform():
    d = _dict()
    assert "race" in d.variables  # previously would have been dropped
    race = d.variables["race"]
    assert race.frequency_source == "uniform"
    # uniform across 3 permissible values
    assert race.probabilities.tolist() == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_counted_variable_keeps_published_frequencies():
    d = _dict()
    sex = d.variables["sex"]
    assert sex.frequency_source == "published"
    probs = dict(zip(sex.categories, sex.probabilities))
    assert probs["Female"] == pytest.approx(0.6)


def test_coverage_report_flags_sources():
    d = _dict()
    cov = coverage_report(d).set_index("variable")["frequency_source"].to_dict()
    assert cov["sex"] == "published"
    assert cov["race"] == "uniform"


def test_generated_cohort_is_conformant():
    d = _dict()
    gen = generate(d, n=500, rng=0).data
    rep = conformance_report(d, gen)
    assert (rep["n_out_of_vocabulary"] == 0).all()
    assert_conformant(d, gen)  # should not raise


def test_assert_conformant_detects_bad_values():
    d = _dict()
    bad = pd.DataFrame({"sex": ["Female", "Martian"], "race": ["White", "White"]})
    with pytest.raises(ValueError):
        assert_conformant(d, bad)
