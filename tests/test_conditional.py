"""Tests for the `conditional` rule (group -> conditional targets, age and ICCC consistency).

Every number in this file is an obvious PLACEHOLDER chosen to make the arithmetic easy to
read. None of them comes from a real table.
"""
import copy
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric.conditional import (
    DERIVATION_FILE,
    MIX_FILE,
    VERIFY_FILE,
    DisclosureRefusal,
    parse_band,
    verification_summary,
)
from synthpediatric.config import ConfigError, normalize_config
from synthpediatric.dictionary import DataDictionary
from synthpediatric.recipe import run_recipe, write_run

SNAPSHOT = Path(
    "/Users/robotinr2/Github/NCI-DCCPS/AI-Work/SEER RFI-RFP/Jamboree-Handoff/demo/artifacts/"
    "nccr_instances.ttl"
)

ALPHA, BETA, GAMMA, DELTA = "I. Alpha", "II. Beta", "III. Gamma", "IV. Delta"


def _var(name, labels_weights):
    return {
        "name": name,
        "values": [{"value": k, "count": v} for k, v in labels_weights.items()],
    }


def _single_year():
    out = {f"{y:02d} years": 1 + y for y in range(20)}
    out["20+ years"] = 5
    out["Unknown"] = 3
    return out


DICTIONARY = {
    "name": "placeholder",
    "variables": [
        _var("icccMajor", {ALPHA: 10, BETA: 8, GAMMA: 6, DELTA: 4}),
        _var("sex", {"Male": 5, "Female": 5}),
        _var("ageA", {
            "00 years": 5, "01-04 years": 20, "05-09 years": 15, "10-14 years": 30,
            "15-19 years": 25, "20+ years": 10, "Unknown": 10,
        }),
        _var("ageB", {
            "00-04 years": 5, "05-09 years": 5, "10-14 years": 5, "15-19 years": 5,
            "20+ years": 5, "Unknown": 5,
        }),
        _var("ageSingle", _single_year()),
        _var("icccSub", {
            "Ia Alpha one": 3, "Ib Alpha two": 1, "IIa Beta one": 2, "IIb Beta two": 2,
            "IIIa Gamma one": 4, "IIIb Gamma two": 0, "IVa Delta one": 1, "IVb Delta two": 1,
        }),
        _var("icccExt", {
            "Ia1 Alpha one one": 1, "Ia2 Alpha one two": 2, "IIa1 Beta one one": 1,
            "IIIa1 Gamma one one": 1, "IVa1 Delta one one": 1,
        }),
        _var("race", {"A": 5, "B": 3, "C": 2}),
        _var("stage", {"early": 4, "late": 6}),
    ],
}

PCT = {
    ALPHA: {"0-4": 50, "5-14": 30, "15-19": 20},
    BETA: {"0-4": 20, "5-14": 50, "15-19": 30},
    GAMMA: {"0-4": 10, "5-14": 40, "15-19": 50},
}
MIX = {ALPHA: 1000, BETA: 600, GAMMA: 400}
SEX = {
    ALPHA: {"Male": 600, "Female": 400},
    BETA: {"Male": 360, "Female": 230},  # sums to 590, group count is 600
    GAMMA: {"Male": 150, "Female": 250},
}
BINS = {"0-4": {"years": [0, 4]}, "5-14": {"years": [5, 14]}, "15-19": {"years": [15, 19]}}
SCALE = {ALPHA: 10, BETA: 6, GAMMA: 4}
AGE_COUNTS = {g: {b: v * SCALE[g] for b, v in row.items()} for g, row in PCT.items()}


@pytest.fixture
def meta(tmp_path):
    path = tmp_path / "dictionary.json"
    path.write_text(json.dumps(DICTIONARY))
    return str(path)


def conditional(**over):
    cond = {
        "provenance": {
            "source": "placeholder table", "date": "2000-01-01", "origin": "assumption",
            "note": "PLACEHOLDER numbers",
        },
        "group": {"variable": "icccMajor", "mix": {"basis": "counts", "values": dict(MIX)}},
        "age": {"anchor": "ageA", "bins": copy.deepcopy(BINS)},
        "targets": [
            {"variable": "ageA", "basis": "percent", "by_group": copy.deepcopy(PCT)},
            {"variable": "sex", "basis": "counts", "by_group": copy.deepcopy(SEX)},
        ],
        "uncovered": {"groups": {DELTA: {"share": "exclude"}}},
    }
    cond.update(over)
    return cond


def config(meta, cond=None, n=2000, seed=3, **extra):
    cfg = {
        "metadata": meta, "n": n, "seed": seed,
        "targets": {"conditional": cond if cond is not None else conditional()},
    }
    cfg.update(extra)
    return cfg


def details(bundle):
    return [r for r in bundle["rules"] if r["name"] == "conditional"][0]["details"]


def target_p(bundle, group, target):
    t = bundle["extra_tables"][VERIFY_FILE]
    t = t[(t["group"] == group) & (t["target"] == target)]
    return dict(zip(t["category"], t["target_p"]))


# ---------------------------------------------------------------- schema ---

def _bad(mutate):
    cond = conditional()
    mutate(cond)
    return cond


@pytest.mark.parametrize(
    "cond, text",
    [
        (_bad(lambda c: c.pop("group")), "missing required key 'group'"),
        (_bad(lambda c: c.update(bogus=1)), "unknown key 'bogus'"),
        (_bad(lambda c: c["provenance"].update(origin="rumour")), "provenance.origin"),
        (_bad(lambda c: c["group"]["mix"].update(basis="shares")), "group.mix.basis"),
        (_bad(lambda c: c["group"]["mix"].update(basis="published_marginal")),
         "not allowed with basis 'published_marginal'"),
        (_bad(lambda c: c["group"]["mix"].pop("values")), "requires 'values'"),
        (_bad(lambda c: c.update(targets=[])), "non-empty list"),
        (_bad(lambda c: c["targets"].append(dict(c["targets"][1]))), "listed twice"),
        (_bad(lambda c: c["targets"][1].update(file="x.csv")), "exactly one of 'by_group'"),
        (_bad(lambda c: c["targets"][1].update(basis="ratio")), "basis"),
        (_bad(lambda c: c.update(scope={"age_years": [0, 19]}) or c.pop("age")),
         "requires an 'age' section"),
        (_bad(lambda c: c["age"]["bins"].update({"x": {"years": [9, 3]}})), "lo must be <= hi"),
        (_bad(lambda c: c["age"].update(split={"5-14": {"05-09 years": -1}})), "must be > 0"),
        (_bad(lambda c: c["uncovered"]["groups"][DELTA].update(share="some")), "share"),
        (_bad(lambda c: c["uncovered"]["groups"][DELTA].update(
            targets={"sex": "exclude"}, share=5)), "treatment 'exclude'"),
        (_bad(lambda c: c["targets"][0].update(variable="icccMajor")),
         "group variable|anchor"),
    ],
)
def test_schema_errors(meta, cond, text):
    with pytest.raises(ConfigError) as exc:
        normalize_config(config(meta, cond))
    assert re.search(text, str(exc.value))


def test_conditional_is_in_standard_and_full_profiles_only(meta):
    for profile, expected in (("standard", "applied"), ("full", "applied"),
                              ("marginals_only", "disabled")):
        cfg = normalize_config(config(meta, profile=profile))
        from synthpediatric.rules import resolve_rules

        status = {r["name"]: r["status"] for r in resolve_rules(cfg)}
        assert status["conditional"] == expected


# ------------------------------------------------------------- age and split ---

def test_union_default_split_is_restricted_published_weights(meta):
    d = details(run_recipe(config(meta, n=50)))
    split = d["age"]["split"]
    assert d["age"]["scope_labels"] == [
        "00 years", "01-04 years", "05-09 years", "10-14 years", "15-19 years"
    ]
    assert split["0-4"]["source"] == "published_restricted"
    assert split["0-4"]["labels"] == pytest.approx({"00 years": 0.2, "01-04 years": 0.8})
    assert split["5-14"]["labels"] == pytest.approx(
        {"05-09 years": 15 / 45, "10-14 years": 30 / 45}
    )
    assert split["15-19"]["labels"] == {"15-19 years": 1.0}


def test_config_split_overrides_published(meta):
    cond = conditional()
    cond["age"]["split"] = {"5-14": {"05-09 years": 1, "10-14 years": 3}}
    d = details(run_recipe(config(meta, cond, n=50)))
    assert d["age"]["split"]["5-14"]["source"] == "config"
    assert d["age"]["split"]["5-14"]["labels"] == pytest.approx(
        {"05-09 years": 0.25, "10-14 years": 0.75}
    )


def test_unaligned_bin_is_an_error(meta):
    cond = conditional()
    cond["age"]["bins"]["0-4"] = {"years": [0, 3]}
    with pytest.raises(ConfigError, match=r"years \[0, 3\] do not start and end on anchor band"):
        run_recipe(config(meta, cond))


def test_overlapping_and_missing_bins(meta):
    cond = conditional()
    cond["age"]["bins"]["5-14"] = ["05-09 years", "10-14 years", "01-04 years"]
    with pytest.raises(ConfigError, match="'01-04 years' is in both '0-4' and '5-14'"):
        run_recipe(config(meta, cond))
    cond = conditional()
    cond["scope"] = {"age_years": [0, 19]}
    del cond["age"]["bins"]["15-19"]
    for row in cond["targets"][0]["by_group"].values():
        del row["15-19"]
    with pytest.raises(ConfigError, match="Scope bands missing from the bins: .*15-19 years"):
        run_recipe(config(meta, cond))


def test_scope_larger_than_the_bins_and_scope_edges(meta):
    cond = conditional(scope={"age_years": [0, 19]})
    assert details(run_recipe(config(meta, cond, n=50)))["age"]["scope_labels"][-1] == "15-19 years"
    bad = conditional(scope={"age_years": [0, 21]})
    with pytest.raises(ConfigError, match="scope.age_years"):
        run_recipe(config(meta, bad))


def test_missing_and_extra_bin_in_an_age_row(meta):
    cond = conditional()
    del cond["targets"][0]["by_group"][BETA]["15-19"]
    with pytest.raises(ConfigError, match=r"must name every bin. Missing: \['15-19'\]"):
        run_recipe(config(meta, cond))
    cond = conditional()
    cond["targets"][0]["by_group"][BETA]["5-15"] = 0
    with pytest.raises(ConfigError, match="unknown bin '5-15'.*Did you mean '5-14'"):
        run_recipe(config(meta, cond))


# --------------------------------------------------------------- labels ---

def test_did_you_mean_on_group_anchor_and_sex_labels(meta):
    cond = conditional()
    cond["group"]["mix"]["values"]["I. Alpa"] = cond["group"]["mix"]["values"].pop(ALPHA)
    with pytest.raises(ConfigError, match="unknown group 'I. Alpa'.*Did you mean 'I. Alpha'"):
        run_recipe(config(meta, cond))
    cond = conditional()
    cond["age"]["anchor"] = "ageAA"
    cond["targets"][0]["variable"] = "ageAA"
    with pytest.raises(ConfigError, match="unknown variable 'ageAA'.*Did you mean 'ageA'"):
        run_recipe(config(meta, cond))
    cond = conditional()
    cond["targets"][1]["by_group"][ALPHA]["Femal"] = cond["targets"][1]["by_group"][ALPHA].pop(
        "Female"
    )
    with pytest.raises(ConfigError, match="unknown category 'Femal'.*Did you mean 'Female'"):
        run_recipe(config(meta, cond))


def test_group_labels_map_user_labels_to_dictionary_labels(meta):
    cond = conditional()
    cond["group"]["labels"] = {"leukemia": ALPHA, "other": BETA, "third": GAMMA}
    cond["group"]["mix"]["values"] = {"leukemia": 1000, "other": 600, "third": 400}
    for t in cond["targets"]:
        t["by_group"] = {
            {ALPHA: "leukemia", BETA: "other", GAMMA: "third"}[g]: row
            for g, row in t["by_group"].items()
        }
    bundle = run_recipe(config(meta, cond, n=500))
    assert set(bundle["data"]["icccMajor"]) <= {ALPHA, BETA, GAMMA}
    bad = copy.deepcopy(cond)
    bad["group"]["labels"]["third"] = "III. Gama"
    with pytest.raises(ConfigError, match="Did you mean 'III. Gamma'"):
        run_recipe(config(meta, bad))


# ----------------------------------------------- percent, counts, crosstab ---

def test_percent_counts_and_crosstab_give_the_same_conditional(meta, tmp_path):
    pct = run_recipe(config(meta, n=100))
    cnt_cond = conditional()
    cnt_cond["targets"][0] = {
        "variable": "ageA", "basis": "counts", "by_group": copy.deepcopy(AGE_COUNTS),
    }
    cnt = run_recipe(config(meta, cnt_cond, n=100))
    rows = []
    for g, row in PCT.items():  # anchor-level counts consistent with the published split
        scale = SCALE[g]
        rows += [
            (g, "00 years", row["0-4"] * 0.2 * scale), (g, "01-04 years", row["0-4"] * 0.8 * scale),
            (g, "05-09 years", row["5-14"] / 3 * scale),
            (g, "10-14 years", row["5-14"] * 2 / 3 * scale),
            (g, "15-19 years", row["15-19"] * scale),
        ]
    csv = tmp_path / "age.csv"
    pd.DataFrame(rows, columns=["icccMajor", "ageA", "count"]).to_csv(csv, index=False)
    file_cond = conditional()
    file_cond["targets"][0] = {"variable": "ageA", "basis": "counts", "file": str(csv)}
    file_cond.pop("age")
    file_cond["age"] = {"anchor": "ageA", "bins": copy.deepcopy(BINS)}
    fil = run_recipe(config(meta, file_cond, n=100))
    for g in PCT:
        a, b, c = (target_p(x, g, "ageA") for x in (pct, cnt, fil))
        assert a == pytest.approx(b) and a == pytest.approx(c)
    assert str(csv) in fil["input_files"]


def test_crosstab_file_errors(meta, tmp_path):
    csv = tmp_path / "bad.csv"
    pd.DataFrame({"icccMajor": [ALPHA], "sex": ["Male"], "n": [5]}).to_csv(csv, index=False)
    cond = conditional()
    cond["targets"][1] = {"variable": "sex", "basis": "counts", "file": str(csv)}
    with pytest.raises(ConfigError, match=r"lacks column\(s\) \['count'\]"):
        run_recipe(config(meta, cond))
    frame = pd.DataFrame({"icccMajor": [ALPHA], "sex": ["Male"], "count": ["many"]})
    frame.to_csv(csv, index=False)
    with pytest.raises(ConfigError, match="non-numeric count 'many'"):
        run_recipe(config(meta, cond))


def test_sex_counts_act_as_a_ratio_and_the_difference_is_recorded(meta):
    bundle = run_recipe(config(meta, n=100))
    assert target_p(bundle, BETA, "sex") == pytest.approx(
        {"Male": 360 / 590, "Female": 230 / 590}
    )
    note = [
        n for n in details(bundle)["provenance_notes"]
        if n["group"] == BETA and n["target"] == "sex"
    ][0]
    assert note["row_sum"] == 590 and note["group_count"] == 600 and note["difference"] == -10


def test_percent_rows_must_sum_to_100(meta):
    cond = conditional()
    cond["targets"][0]["by_group"][ALPHA]["0-4"] = 60
    with pytest.raises(ConfigError, match=r"percentages sum to 110"):
        run_recipe(config(meta, cond))


# --------------------------------------------------------- uncovered groups ---

def _with_uncovered(entry):
    cond = conditional()
    cond["uncovered"] = {"groups": {DELTA: entry}}
    return cond


def test_uncovered_group_is_required_and_listed(meta):
    cond = conditional()
    del cond["uncovered"]
    with pytest.raises(ConfigError, match=r"does not cover group\(s\) \['IV. Delta'\]"):
        run_recipe(config(meta, cond))
    with pytest.raises(ConfigError, match="no treatment for target"):
        run_recipe(config(meta, _with_uncovered({"share": 100})))
    with pytest.raises(ConfigError, match=r"unknown target variable 'sx'.*Did you mean 'sex'"):
        run_recipe(config(meta, _with_uncovered(
            {"share": 100, "targets": {"sx": "published_marginal"}}
        )))
    with pytest.raises(ConfigError, match="only applies to the age anchor"):
        run_recipe(config(meta, _with_uncovered({
            "share": 100,
            "targets": {"ageA": "published_age_mix", "sex": "published_age_mix"},
        })))


def test_uncovered_exclude_generates_no_records_of_the_group(meta):
    bundle = run_recipe(config(meta, n=3000))
    assert DELTA not in set(bundle["data"]["icccMajor"])
    assert details(bundle)["excluded_groups"] == [DELTA]


def test_uncovered_treatments(meta):
    entry = {
        "share": 500,
        "targets": {"ageA": "published_age_mix", "sex": "same_as_covered_total"},
    }
    bundle = run_recipe(config(meta, _with_uncovered(entry), n=3000))
    anchor = DICTIONARY["variables"][2]["values"]
    weights = {v["value"]: v["count"] for v in anchor if v["value"] in (
        "00 years", "01-04 years", "05-09 years", "10-14 years", "15-19 years")}
    total = sum(weights.values())
    p = target_p(bundle, DELTA, "ageA")
    assert p["0-4"] == pytest.approx((weights["00 years"] + weights["01-04 years"]) / total)
    assert p["5-14"] == pytest.approx((weights["05-09 years"] + weights["10-14 years"]) / total)
    male = sum(r["Male"] for r in SEX.values())
    female = sum(r["Female"] for r in SEX.values())
    assert target_p(bundle, DELTA, "sex")["Male"] == pytest.approx(male / (male + female))
    share = bundle["extra_tables"][MIX_FILE].set_index("group")["target_share"]
    assert share[DELTA] == pytest.approx(500 / 2500)
    assert details(bundle)["uncovered"][0]["as_assumption"] is True

    entry = {
        "share": 100,
        "targets": {
            "ageA": {"values": {"0-4": 25, "5-14": 25, "15-19": 50}},
            "sex": "published_marginal",
        },
    }
    bundle = run_recipe(config(meta, _with_uncovered(entry), n=300))
    assert target_p(bundle, DELTA, "ageA") == pytest.approx(
        {"0-4": 0.25, "5-14": 0.25, "15-19": 0.5}
    )
    assert target_p(bundle, DELTA, "sex") == pytest.approx({"Male": 0.5, "Female": 0.5})
    bad = {"share": 100, "targets": {"ageA": {"values": {"0-4": 100}}, "sex": "published_marginal"}}
    with pytest.raises(ConfigError, match="values must name every age bin"):
        run_recipe(config(meta, _with_uncovered(bad)))


def test_same_as_covered_total_for_percent_basis_is_mix_weighted(meta):
    cond = conditional()
    cond["targets"][1] = {
        "variable": "sex", "basis": "percent",
        "by_group": {ALPHA: {"Male": 60, "Female": 40}, BETA: {"Male": 50, "Female": 50},
                     GAMMA: {"Male": 20, "Female": 80}},
    }
    cond["uncovered"] = {"groups": {DELTA: {"share": 100, "targets": {
        "ageA": "same_as_covered_total", "sex": "same_as_covered_total"}}}}
    bundle = run_recipe(config(meta, cond, n=100))
    male = (1000 * 0.6 + 600 * 0.5 + 400 * 0.2) / 2000
    assert target_p(bundle, DELTA, "sex")["Male"] == pytest.approx(male)


def test_mix_as_percent_and_published_marginal(meta):
    cond = conditional()
    cond["group"]["mix"] = {"basis": "percent", "values": {ALPHA: 50, BETA: 30, GAMMA: 20}}
    shares = run_recipe(config(meta, cond, n=100))["extra_tables"][MIX_FILE]
    assert shares.set_index("group")["target_share"].to_dict() == pytest.approx(
        {ALPHA: 0.5, BETA: 0.3, GAMMA: 0.2}
    )
    cond = conditional()
    cond["group"]["mix"] = {"basis": "published_marginal"}
    shares = run_recipe(config(meta, cond, n=100))["extra_tables"][MIX_FILE]
    assert shares.set_index("group")["target_share"].to_dict() == pytest.approx(
        {ALPHA: 10 / 24, BETA: 8 / 24, GAMMA: 6 / 24}
    )
    cond["uncovered"] = {"groups": {DELTA: {"share": 20, "targets": {
        "ageA": "published_age_mix", "sex": "published_marginal"}}}}
    shares = run_recipe(config(meta, cond, n=100))["extra_tables"][MIX_FILE]
    assert shares.set_index("group")["target_share"].to_dict() == pytest.approx(
        {ALPHA: 0.8 * 10 / 24, BETA: 0.8 * 8 / 24, GAMMA: 0.8 * 6 / 24, DELTA: 0.2}
    )


def test_unknown_is_never_generated_unless_listed(meta):
    bundle = run_recipe(config(meta, n=4000))
    for column in ("ageA", "ageB", "ageSingle", "sex"):
        assert "Unknown" not in set(bundle["data"][column])
    cond = conditional()
    cond["targets"][1]["by_group"][ALPHA]["Unknown"] = 100
    cond["targets"][1]["by_group"][ALPHA]["Male"] = 0
    # Unknown is not a category of sex, so listing it is an error
    with pytest.raises(ConfigError, match="unknown category 'Unknown'"):
        run_recipe(config(meta, cond))
    cond = conditional()
    cond["targets"].append(
        {"variable": "race", "basis": "counts", "by_group": {
            ALPHA: {"A": 5, "B": 5}, BETA: {"A": 5}, GAMMA: {"B": 5, "C": 1}}}
    )
    bundle = run_recipe(config(meta, cond, n=3000))
    assert set(bundle["data"]["race"]) == {"A", "B", "C"}
    assert "C" not in set(bundle["data"].loc[bundle["data"]["icccMajor"] == ALPHA, "race"])
    assert details(bundle)["absent_cells"]  # zeros filled in and listed


# ----------------------------------------------------------- cohort and joints ---

def test_cohort_filter_on_the_group_drops_table_groups(meta):
    cohort = {"filters": [{"variable": "icccMajor", "op": "equals", "values": [ALPHA, GAMMA]}]}
    bundle = run_recipe(config(meta, n=3000, cohort=cohort))
    assert set(bundle["data"]["icccMajor"]) == {ALPHA, GAMMA}
    assert details(bundle)["dropped_by_cohort"] == [BETA, DELTA]
    shares = bundle["extra_tables"][MIX_FILE].set_index("group")["target_share"]
    assert shares.to_dict() == pytest.approx({ALPHA: 1000 / 1400, GAMMA: 400 / 1400})
    assert shares.sum() == pytest.approx(1.0)


def _crosstab(tmp_path, a, b):
    path = tmp_path / "cross.csv"
    rows = [(x, y, 10) for x in DICT_VALUES[a] for y in DICT_VALUES[b]]
    pd.DataFrame(rows, columns=[a, b, "count"]).to_csv(path, index=False)
    return str(path)


DICT_VALUES = {"race": ["A", "B", "C"], "stage": ["early", "late"], "sex": ["Male", "Female"]}


def test_joints_and_conditional_on_a_shared_variable_is_an_error(meta, tmp_path):
    joints = {"cliques": [["sex", "stage"]], "crosstabs": _crosstab(tmp_path, "sex", "stage")}
    cfg = config(meta)
    cfg["targets"]["joints"] = joints
    with pytest.raises(
        ConfigError, match="targets.joints and targets.conditional both use variable sex"
    ):
        run_recipe(cfg)


def test_joints_on_unrelated_variables_still_runs(meta, tmp_path):
    joints = {"cliques": [["race", "stage"]], "crosstabs": _crosstab(tmp_path, "race", "stage")}
    cfg = config(meta, n=500)
    cfg["targets"]["joints"] = joints
    bundle = run_recipe(cfg)
    assert len(bundle["data"]) == 500 and set(bundle["data"]["race"]) <= {"A", "B", "C"}


# ----------------------------------------------------------------- disclosure ---

def _cgc(cond, **prov):
    cond["provenance"]["origin"] = "cgc_aggregate"
    cond["provenance"].update(prov)
    return cond


def test_cgc_aggregate_default_threshold_passes_with_large_cells(meta):
    bundle = run_recipe(config(meta, _cgc(conditional()), n=100))
    mc = details(bundle)["min_cell"]
    assert mc["value"] == 16 and mc["supplied_by"] == "default" and mc["origin"] == "cgc_aggregate"
    assert mc["cells_checked"] > 0 and mc["offending"] == 0


def test_cgc_aggregate_refuses_and_lists_every_offending_cell(meta, tmp_path):
    cond = _cgc(conditional())
    cond["targets"][1]["by_group"][BETA]["Male"] = 5  # counted
    cond["targets"][0]["by_group"][GAMMA] = {"0-4": 2, "5-14": 48, "15-19": 50}  # implied 8
    cond["group"]["mix"]["values"][GAMMA] = 400
    out = tmp_path / "out"
    with pytest.raises(DisclosureRefusal) as exc:
        write_run(run_recipe(config(meta, cond)), out)
    message = str(exc.value)
    assert isinstance(exc.value, ConfigError)
    assert f"{BETA} | sex | Male | 5 | counted" in message
    assert f"{GAMMA} | ageA | 0-4 | 8 | implied" in message
    assert "Nothing was generated." in message and "16" in message and "cgc_aggregate" in message
    assert not out.exists()


def test_a_zero_cell_is_not_disclosive(meta):
    cond = _cgc(conditional())
    cond["targets"][1]["by_group"][BETA]["Male"] = 0
    assert details(run_recipe(config(meta, cond, n=100)))["min_cell"]["offending"] == 0


def test_min_cell_zero_needs_a_reason(meta):
    cond = _cgc(conditional(), min_cell=0)
    cond["targets"][1]["by_group"][BETA]["Male"] = 5
    with pytest.raises(ConfigError, match="override_reason"):
        run_recipe(config(meta, cond))
    cond["provenance"]["override_reason"] = "internal check, not for release"
    mc = details(run_recipe(config(meta, cond, n=100)))["min_cell"]
    assert mc["value"] == 0 and mc["supplied_by"] == "config"
    assert mc["override_reason"] == "internal check, not for release"


def test_assumption_origin_has_no_check_unless_set(meta):
    cond = conditional()
    cond["targets"][1]["by_group"][BETA]["Male"] = 5
    mc = details(run_recipe(config(meta, cond, n=100)))["min_cell"]
    assert mc["value"] is None and "not applicable for origin assumption" in mc["note"]
    cond["provenance"]["min_cell"] = 10
    with pytest.raises(DisclosureRefusal, match="below the minimum cell size 10"):
        run_recipe(config(meta, cond))


def test_implied_counts_not_checkable_without_group_size(meta):
    cond = _cgc(conditional())
    cond["group"]["mix"] = {"basis": "percent", "values": {ALPHA: 50, BETA: 30, GAMMA: 20}}
    cond["targets"][1]["by_group"][BETA]["Male"] = 5  # counted, still checked
    with pytest.raises(DisclosureRefusal) as exc:
        run_recipe(config(meta, cond))
    assert "| 5 | counted" in str(exc.value)
    cond["targets"][1]["by_group"][BETA]["Male"] = 360
    mc = details(run_recipe(config(meta, cond, n=100)))["min_cell"]
    assert "implied counts not checkable: group size unknown" in mc["implied_counts"]


# ---------------------------------------------------- reproduction, consistency ---

def _nested(a, b):
    (alo, ahi), (blo, bhi) = parse_band(a), parse_band(b)
    return (alo <= blo and bhi <= ahi) or (blo <= alo and ahi <= bhi)


def _inconsistent(df, anchor, other):
    pairs = df[[anchor, other]].drop_duplicates()
    bad = [(a, o) for a, o in pairs.itertuples(index=False) if not _nested(a, o)]
    return int(df.merge(pd.DataFrame(bad, columns=[anchor, other])).shape[0]) if bad else 0


def _numeral(label):
    return re.match(r"^([IVX]+)", label).group(1)


def test_reproduction_and_consistency_at_n_40000(meta):
    entry = {"share": 300, "targets": {"ageA": "published_age_mix", "sex": "published_marginal"}}
    cond = _with_uncovered(entry)
    bundle = run_recipe(config(meta, cond, n=40000, seed=11))
    df = bundle["data"]
    tables = bundle["extra_tables"]
    summary = verification_summary(tables)
    assert summary["cells"] == len(tables[VERIFY_FILE]) >= 20
    assert summary["max_z"] < 5
    assert summary["group_mix"]["max_z"] < 5
    assert details(bundle)["achieved"]["max_z"] == pytest.approx(summary["max_z"])
    assert set(summary["per_target"]) == {"ageA", "sex"}
    assert (tables[VERIFY_FILE]["abs_diff"] <= 5 * tables[VERIFY_FILE]["expected_se"] + 1e-12).all()
    for other in ("ageB", "ageSingle"):
        assert _inconsistent(df, "ageA", other) == 0
    in_scope = df["ageA"].isin(
        ["00 years", "01-04 years", "05-09 years", "10-14 years", "15-19 years"]
    )
    assert in_scope.all()
    for sub in ("icccSub", "icccExt"):
        assert (df["icccMajor"].map(_numeral) == df[sub].map(_numeral)).all()
    for column in df.columns:
        assert "Unknown" not in set(df[column])


def test_sampled_derivation_follows_published_weights(meta):
    bundle = run_recipe(config(meta, n=40000, seed=5))
    df = bundle["data"]
    band = df[df["ageA"] == "01-04 years"]["ageSingle"].value_counts(normalize=True)
    weights = np.array([2, 3, 4, 5], dtype=float)
    weights /= weights.sum()
    got = [band.get(f"{y:02d} years", 0.0) for y in range(1, 5)]
    assert np.allclose(got, weights, atol=0.02)
    table = bundle["extra_tables"][DERIVATION_FILE]
    row = table[(table["variable"] == "ageB") & (table["anchor_or_group_label"] == "00 years")]
    assert row["method"].tolist() == ["deterministic"] and row["probability"].tolist() == [1.0]
    sampled = table[(table["variable"] == "icccSub") & (table["anchor_or_group_label"] == ALPHA)]
    assert sampled["method"].tolist() == ["sampled", "sampled"]
    assert sampled["probability"].tolist() == pytest.approx([0.75, 0.25])


def test_single_year_variables_and_iccc_subgroups_agree_with_each_other(tmp_path):
    spec = copy.deepcopy(DICTIONARY)
    twin = {f"{y:02d} years": 5 + y * y for y in range(20)}  # other weights, other top group
    twin["25+ years"] = 5
    spec["variables"].append(_var("ageSingleTwin", twin))
    ext = spec["variables"][6]["values"]  # icccExt: add the labels icccSub needs
    ext += [{"value": v, "count": 1} for v in ("Ib1 Alpha two one", "IIb1 Beta two one",
                                               "IVb1 Delta two one")]
    path = tmp_path / "twin.json"
    path.write_text(json.dumps(spec))
    bundle = run_recipe(config(str(path), n=20000, seed=4))
    df = bundle["data"]
    assert (df["ageSingle"] == df["ageSingleTwin"]).all()
    assert details(bundle)["age_links"] == {"ageSingleTwin": "ageSingle"}
    assert details(bundle)["hierarchy"]["nested"] == {"icccExt": "icccSub"}
    assert (df["icccExt"].str.extract(r"^([IVX]+[a-z])")[0]
            == df["icccSub"].str.extract(r"^([IVX]+[a-z])")[0]).all()
    assert (df["icccMajor"].map(_numeral) == df["icccExt"].map(_numeral)).all()
    table = bundle["extra_tables"][DERIVATION_FILE]
    linked = table[(table["variable"] == "ageSingleTwin")]
    assert set(linked["method"]) == {"linked to ageSingle", "deterministic"}
    # a subgroup variable that cannot nest (no icccExt label for 'Ib') keeps its own draw
    plain = run_recipe(config(meta_path(tmp_path), n=500, seed=4))
    assert "nested" not in details(plain)["hierarchy"]


def meta_path(tmp_path):
    path = tmp_path / "plain.json"
    path.write_text(json.dumps(DICTIONARY))
    return str(path)


def test_unmappable_age_label_is_an_error(meta, tmp_path):
    bad = copy.deepcopy(DICTIONARY)
    bad["variables"].append(_var("ageGroupName", {"Children": 1, "Adults": 1}))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ConfigError, match="unmappable label 'Children'"):
        run_recipe(config(str(path)))
    bad = copy.deepcopy(DICTIONARY)
    bad["variables"][5]["values"].append({"value": "Mystery", "count": 1})  # icccSub
    path.write_text(json.dumps(bad))
    with pytest.raises(ConfigError, match="unmappable label 'Mystery'"):
        run_recipe(config(str(path)))


def test_a_label_straddling_a_band_edge_is_an_error(meta, tmp_path):
    bad = copy.deepcopy(DICTIONARY)
    bad["variables"].append(_var("ageOdd", {"00-02 years": 1, "03-09 years": 1, "10+ years": 1}))
    path = tmp_path / "odd.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ConfigError, match="straddles the edge of anchor band '01-04 years'"):
        run_recipe(config(str(path)))


def test_same_seed_gives_identical_frames(meta):
    a = run_recipe(config(meta, n=800, seed=9))["data"]
    b = run_recipe(config(meta, n=800, seed=9))["data"]
    c = run_recipe(config(meta, n=800, seed=10))["data"]
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_other_columns_keep_their_stream(meta):
    with_cond = run_recipe(config(meta, n=500, seed=4))["data"]
    plain = run_recipe({"metadata": meta, "n": 500, "seed": 4})["data"]
    for column in ("race", "stage"):
        assert with_cond[column].tolist() == plain[column].tolist()


def test_constraints_run_last_on_the_final_frame(meta):
    constraints = {"rules": [{
        "trigger_col": "icccMajor", "trigger_values": [GAMMA], "target_col": "sex",
        "allowed_values": ["Female"], "name": "gamma_is_female",
    }]}
    bundle = run_recipe(config(meta, n=4000, constraints=constraints))
    df = bundle["data"]
    assert bundle["result"].repairs["gamma_is_female"] > 0
    assert (df.loc[df["icccMajor"] == GAMMA, "sex"] == "Female").all()
    table = bundle["extra_tables"][VERIFY_FILE]
    row = table[(table["group"] == GAMMA) & (table["target"] == "sex")
                & (table["category"] == "Female")].iloc[0]
    assert row["generated_p"] == 1.0  # measured after the constraints


def test_write_run_writes_the_extra_tables_and_manifest_details(meta, tmp_path):
    out = write_run(run_recipe(config(meta, n=300)), tmp_path / "run")
    for name in (DERIVATION_FILE, MIX_FILE, VERIFY_FILE):
        assert (out / name).exists()
    manifest = json.loads((out / "manifest.json").read_text())
    entry = [r for r in manifest["rules"] if r["name"] == "conditional"][0]
    assert entry["status"] == "applied"
    assert entry["details"]["min_cell"]["origin"] == "assumption"
    assert entry["details"]["achieved"]["cells"] > 0
    assert entry["details"]["provenance"]["source"] == "placeholder table"


def test_runs_without_conditional_write_no_extra_tables(meta, tmp_path):
    out = write_run(run_recipe({"metadata": meta, "n": 50, "seed": 1}), tmp_path / "plain")
    assert not (out / MIX_FILE).exists()


def test_without_an_age_section_targets_are_plain_categories(meta):
    cond = conditional()
    cond.pop("age")
    cond["targets"][0] = {
        "variable": "stage", "basis": "counts", "by_group": {
            ALPHA: {"early": 30, "late": 70}, BETA: {"early": 50, "late": 50},
            GAMMA: {"early": 90, "late": 10}},
    }
    bundle = run_recipe(config(meta, cond, n=100))
    assert details(bundle)["age_variables"] == []
    assert target_p(bundle, GAMMA, "stage") == pytest.approx({"early": 0.9, "late": 0.1})


def test_dictionary_roundtrip_is_valid():
    DataDictionary.from_dict(DICTIONARY)


# ------------------------------------------------------- real snapshot ---

@pytest.mark.skipif(not SNAPSHOT.exists(), reason="NCCR metadata snapshot not available")
def test_real_snapshot_end_to_end():
    major = [
        "I. Leukemias, Myeloproliferative And Myelodysplastic Diseases",
        "II. Lymphomas and reticuloendothelial neoplasms",
        "III. CNS and Miscellaneous Intracranial and Intraspinal Neoplasms",
    ]
    cond = {
        "provenance": {"source": "PLACEHOLDER", "date": "2000-01-01", "origin": "assumption"},
        "group": {"variable": "icccMajor", "mix": {
            "basis": "counts", "values": dict(zip(major, (100, 60, 40)))}},
        "scope": {"age_years": [0, 19]},
        "age": {"anchor": "ageRecode19Groups", "bins": {
            "0-4": {"years": [0, 4]}, "5-14": {"years": [5, 14]}, "15-19": {"years": [15, 19]}}},
        "targets": [
            {"variable": "ageRecode19Groups", "basis": "percent", "by_group": {
                major[0]: {"0-4": 40, "5-14": 40, "15-19": 20},
                major[1]: {"0-4": 10, "5-14": 40, "15-19": 50},
                major[2]: {"0-4": 30, "5-14": 50, "15-19": 20}}},
            {"variable": "sex", "basis": "counts", "by_group": {
                major[0]: {"Male": 55, "Female": 45}, major[1]: {"Male": 30, "Female": 30},
                major[2]: {"Male": 20, "Female": 20}}},
        ],
    }
    meta = str(SNAPSHOT)
    probe = run_recipe({"metadata": meta, "source": "CTC", "n": 5, "seed": 1,
                        "profile": "marginals_only"})
    groups = list(probe["dictionary"].variables["icccMajor"].categories)
    cond["uncovered"] = {"groups": {g: {"share": "exclude"} for g in groups if g not in major}}
    cfg = {"metadata": meta, "source": "CTC", "n": 20000, "seed": 7,
           "targets": {"conditional": cond}}
    bundle = run_recipe(cfg)
    df = bundle["data"]
    summary = details(bundle)["achieved"]
    assert summary["max_z"] < 5
    assert set(df["icccMajor"]) <= set(major)
    assert "Unknown" not in set(df["ageRecode19Groups"])
    assert details(bundle)["hierarchy"]["derived"]
