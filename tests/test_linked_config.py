"""The ``linked:`` config block: validation, defaults, idempotence, unchanged old configs."""
import pytest

from synthpediatric.config import ConfigError, config_hash, normalize_config
from synthpediatric.linked import CHILD_ORDER, default_cardinality, default_tumors_per_patient
from synthpediatric.recipe import run_recipe

BASE = {"metadata": "x.ttl", "source": "CTC", "n": 100, "seed": 1}


def cfg(linked):
    return {**BASE, "linked": linked}


def test_defaults_come_from_the_erd_counts():
    out = normalize_config(cfg({"dictionaries": "raw"}))["linked"]
    assert list(out["children"]) == list(CHILD_ORDER)
    assert out["children"]["ABM"] == {}
    assert out["children"]["COG"] == {"coverage": 1.0, "rows_per_patient": 1.0}
    assert out["children"]["MCD"] == default_cardinality("MCD")
    assert abs(out["children"]["MCD"]["coverage"] - 300394 / 1483916) < 1e-6
    assert abs(out["children"]["MCD"]["rows_per_patient"] - 56660564 / 300394) < 1e-3
    assert out["tumors_per_patient"] == default_tumors_per_patient() == pytest.approx(1.0881)
    assert out["tolerance"] == 0.05


def test_listed_children_only_and_partial_options():
    out = normalize_config(cfg({"dictionaries": "raw", "children": {"PHARM": {"coverage": 0.5}}}))
    assert list(out["linked"]["children"]) == ["PHARM"]
    assert out["linked"]["children"]["PHARM"]["coverage"] == 0.5
    assert out["linked"]["children"]["PHARM"]["rows_per_patient"] == pytest.approx(52.2553)


def test_normalize_is_idempotent():
    once = normalize_config(cfg({"dictionaries": "raw", "children": {"RO": {"coverage": 0.2}}}))
    assert normalize_config(once) == once


@pytest.mark.parametrize(
    "linked, message",
    [
        ({"dictionaries": "raw", "children": {"PHRM": {}}}, "Did you mean 'PHARM'"),
        ({"dictionaries": "raw", "children": {"RO": {"coverage": 1.5}}}, "coverage"),
        ({"dictionaries": "raw", "children": {"RO": {"coverage": 0}}}, "coverage"),
        ({"dictionaries": "raw", "children": {"RO": {"rows_per_patient": 0.5}}},
         "rows_per_patient"),
        ({"dictionaries": "raw", "children": {"ABM": {"coverage": 1}}}, "ABM"),
        ({"dictionaries": "raw", "children": {"RO": {"cover": 1}}}, "unknown key"),
        ({"children": {}}, "dictionaries"),
        ({"dictionaries": "raw", "tumors_per_patient": 0.5}, "tumors_per_patient"),
        ({"dictionaries": "raw", "extra": 1}, "unknown key"),
    ],
)
def test_bad_blocks_are_rejected(linked, message):
    with pytest.raises(ConfigError, match=message):
        normalize_config(cfg(linked))


def test_parent_must_be_ctc_on_rdf_metadata():
    with pytest.raises(ConfigError, match="source: CTC"):
        normalize_config({**BASE, "source": "PHARM", "linked": {"dictionaries": "raw"}})
    with pytest.raises(ConfigError, match="RDF metadata"):
        normalize_config({**BASE, "metadata": "d.json", "linked": {"dictionaries": "raw"}})


def test_config_without_linked_is_unchanged():
    canonical = normalize_config(BASE)
    assert "linked" not in canonical
    assert canonical == {
        "metadata": "x.ttl", "source": "CTC", "n": 100, "seed": 1, "value_mode": "label",
        "no_frequency": "uniform", "missingness": "none", "profile": "full",
        "rules": canonical["rules"],
    }
    # the hash this config had before the linked block existed
    assert config_hash(canonical) == (
        "051bcecf64e153620e911fa5b7e818d248d90d61be5f1f33c4c1ab18a09d3260"
    )


def test_run_recipe_refuses_a_linked_config():
    with pytest.raises(ConfigError, match="run_linked"):
        run_recipe(cfg({"dictionaries": "raw"}))
