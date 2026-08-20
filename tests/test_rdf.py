"""Smoke test for the NCCR RDF loader, using an inline Turtle snippet (offline)."""

import rdflib

from synthpediatric.nccr_rdf import build_dictionary, list_datasources

TTL = """
@prefix nccr: <https://nccrdataplatform.ccdi.cancer.gov/vocab#> .
@prefix nccr-ds: <https://nccrdataplatform.ccdi.cancer.gov/datasource/> .
@prefix nccr-var: <https://nccrdataplatform.ccdi.cancer.gov/variable/> .
@prefix nccr-vs: <https://nccrdataplatform.ccdi.cancer.gov/valueset/> .
@prefix nccr-cv: <https://nccrdataplatform.ccdi.cancer.gov/code/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

nccr-ds:ctc a nccr:DataSource ;
    nccr:sourceId "CTC" ;
    nccr:sourceLabel "Consolidated Tumor Case" ;
    nccr:totalRecordCount 100 .

nccr-var:ctc-sex a nccr:Variable ;
    rdfs:label "Sex" ;
    nccr:sourceColumn "sex" ;
    nccr:semanticType "lookup_value" ;
    nccr:belongsToSource nccr-ds:ctc ;
    nccr:hasValueSet nccr-vs:ctc-sex .

nccr-vs:ctc-sex a skos:ConceptScheme .

nccr-cv:ctc-sex-1 a skos:Concept, nccr:CodeValue ;
    skos:inScheme nccr-vs:ctc-sex ;
    skos:notation "1" ;
    skos:prefLabel "Female"@en ;
    nccr:recordCount 60 .

nccr-cv:ctc-sex-2 a skos:Concept, nccr:CodeValue ;
    skos:inScheme nccr-vs:ctc-sex ;
    skos:notation "2" ;
    skos:prefLabel "Male"@en ;
    nccr:recordCount 40 .
"""


def _graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def test_list_datasources():
    sources = list_datasources(_graph())
    ctc = next(s for s in sources if s["source_id"] == "CTC")
    assert ctc["total_record_count"] == 100
    assert ctc["label"] == "Consolidated Tumor Case"


def test_build_dictionary_marginals():
    d = build_dictionary(_graph(), "CTC")
    assert d.n_records == 100
    assert "sex" in d.variables
    probs = dict(zip(d.variables["sex"].categories, d.variables["sex"].probabilities))
    assert abs(probs["Female"] - 0.6) < 1e-9
    assert abs(probs["Male"] - 0.4) < 1e-9


def test_value_mode_code():
    d = build_dictionary(_graph(), "CTC", value_mode="code")
    assert set(d.variables["sex"].categories) == {"1", "2"}
