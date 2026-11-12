"""A config that names something the data does not have is refused up front (offline).

Variable names, category labels, survival groups and constraint columns are checked
against the resolved dictionary before any record is generated or file written.
"""
import json

import pytest

from synthpediatric.cli import main
from synthpediatric.config import ConfigError, fmt_valid, unknown_message
from synthpediatric.recipe import run_recipe, write_run

DICT = "examples/nccr_ctc_dictionary.json"
AGE = "Valid categories: 00-04, 05-09, 10-14, 15-19, 20-24, 25-29, 30-34, 35-39"
CROSSTAB = "examples/profiles/crosstab_sex_age.csv"


def _cfg(**sections):
    return {"metadata": DICT, "n": 200, "seed": 1, **sections}


def _marginals(table, var="age_group"):
    return {"targets": {"marginals": {var: table}}}


def _cohort(*filters):
    return {"cohort": {"filters": list(filters)}}


def _equals(var, *values):
    return {"variable": var, "op": "equals", "values": list(values)}


def _survival(specs, group_col="iccc_category"):
    return {"targets": {"survival": {"group_col": group_col, "specs": specs}}}


def _rules_file(tmp_path, column="gleasonScoreClinicalRecode"):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"constraints": [{
        "type": "allowed_values", "name": "gleason_male_only",
        "trigger_col": "sex", "trigger_values": ["Female"],
        "target_col": column, "allowed_values": ["Not applicable"],
    }]}))
    return str(path)


# ------------------------------------------------ the seven reported problems ---

CASES = {
    "1 marginals label": (
        _marginals({"00-04": 0.5, "05-9": 0.5}),
        ["targets.marginals.age_group:", "unknown category '05-9'", "Did you mean '05-09'?", AGE],
    ),
    "2 marginals variable": (
        _marginals({"00-04": 1}, var="agegroup"),
        ["targets.marginals:", "unknown variable 'agegroup'", "Did you mean 'age_group'?",
         "Valid variables: iccc_category, sex, age_group"],
    ),
    "3a cohort variable": (
        _cohort(_equals("agegroup", "00-04")),
        ["cohort.filters[0].variable:", "unknown variable 'agegroup'",
         "Did you mean 'age_group'?"],
    ),
    "3b cohort label (all wrong)": (
        _cohort(_equals("age_group", "05-9")),
        ["cohort.filters[0].values:", "unknown category '05-9'", "Did you mean '05-09'?", AGE],
    ),
    "3c cohort label (one wrong of two)": (
        _cohort(_equals("age_group", "00-04", "05-9")),
        ["cohort.filters[0].values:", "unknown category '05-9'", "Did you mean '05-09'?"],
    ),
    "4 oversample label": (
        {"oversample": {"variable": "iccc_category", "values": ["V Retinoblastom"]}},
        ["oversample.values:", "unknown category 'V Retinoblastom'",
         "Did you mean 'V Retinoblastoma'?", "Valid categories: I Leukemias"],
    ),
    "5 survival group": (
        _survival({"V Retinoblastom": {"s5": 0.97}}),
        ["targets.survival.specs:", "unknown group 'V Retinoblastom'",
         "Did you mean 'V Retinoblastoma'?", "Valid groups: I Leukemias"],
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_mistake_is_a_clear_config_error_and_nothing_is_written(name, tmp_path):
    sections, needles = CASES[name]
    config = tmp_path / "c.json"
    config.write_text(json.dumps(_cfg(**sections)))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["run", str(config), "--out-dir", str(out)])
    message = str(exc.value)
    assert message.startswith("config error: ")
    for needle in needles:
        assert needle in message, f"{needle!r} not in: {message}"
    assert not out.exists()  # no cohort.csv, manifest.json or anything else


def test_constraint_naming_an_absent_column_is_a_config_error(tmp_path):
    cfg = _cfg(constraints={"file": _rules_file(tmp_path)})
    with pytest.raises(ConfigError) as exc:
        run_recipe(cfg)
    message = str(exc.value)
    for needle in ["constraints.file[0].target_col:", "unknown column 'gleasonScoreClinicalRecode'",
                   "constraint 'gleason_male_only'", "rules.json", "Valid columns: iccc_category"]:
        assert needle in message, f"{needle!r} not in: {message}"
    assert not (tmp_path / "out").exists()


def test_inline_constraint_suggests_the_closest_column():
    rule = {"type": "allowed_values", "name": "r", "trigger_col": "sex",
            "trigger_values": ["Female"], "target_col": "agegroup", "allowed_values": ["00-04"]}
    with pytest.raises(ConfigError, match=r"constraints\.rules\[0\]\.target_col.*Did you mean "
                                          r"'age_group'"):
        run_recipe(_cfg(constraints={"rules": [rule]}))


def test_malformed_constraint_is_a_config_error_not_a_key_error():
    with pytest.raises(ConfigError, match=r"constraints\.rules: invalid constraint"):
        run_recipe(_cfg(constraints={"rules": [{"type": "allowed_values", "name": "r"}]}))


def test_misspelled_survival_group_col_is_caught_before_sampling():
    with pytest.raises(ConfigError, match=r"group_col: unknown column 'icccategory'.*"
                                          r"'iccc_category'"):
        run_recipe(_cfg(**_survival({"V Retinoblastoma": 0.9}, group_col="icccategory")))


def test_invalid_survival_spec_is_a_config_error_not_a_value_error():
    with pytest.raises(ConfigError, match=r"specs\.V Retinoblastoma: invalid survival spec"):
        run_recipe(_cfg(**_survival({"V Retinoblastoma": {"s6": 0.9}})))


# --------------------------------------------- overrides, joints, group_col ---

def test_overrides_file_label_and_variable_are_checked(tmp_path):
    label_file = tmp_path / "ages.json"
    label_file.write_text(json.dumps({"age_group": {"00-04": 1, "05-9": 1}}))
    with pytest.raises(ConfigError) as exc:
        run_recipe(_cfg(targets={"overrides": {"tables": str(label_file)}}))
    assert "targets.overrides.age_group: unknown category '05-9' (in ages.json)" in str(exc.value)
    assert "Did you mean '05-09'?" in str(exc.value)

    var_file = tmp_path / "vars.json"
    var_file.write_text(json.dumps({"agegroup": {"00-04": 1}}))
    with pytest.raises(ConfigError, match=r"targets\.overrides: unknown variable 'agegroup' "
                                          r"\(in vars\.json\)\. Did you mean 'age_group'"):
        run_recipe(_cfg(targets={"overrides": {"tables": str(var_file)}}))


def _joints(clique, crosstabs=CROSSTAB):
    return {"targets": {"joints": {"cliques": [clique], "crosstabs": crosstabs}}}


def test_joints_clique_variable_gets_a_suggestion():
    with pytest.raises(ConfigError, match=r"cliques\[0\]: unknown variable 'agegroup'.*"
                                          r"'age_group'"):
        run_recipe(_cfg(**_joints(["sex", "agegroup"])))


def test_joints_crosstab_label_not_in_dictionary_is_an_error(tmp_path):
    table = tmp_path / "x.csv"
    table.write_text("sex,age_group,count\nMale,00-04,5\nMale,05-9,5\nFemale,00-04,5\n"
                     "Female,05-09,5\n")
    with pytest.raises(ConfigError) as exc:
        run_recipe(_cfg(**_joints(["sex", "age_group"], str(table))))
    message = str(exc.value)
    assert "targets.joints.crosstabs.age_group: unknown category '05-9' (in " in message
    assert "Did you mean '05-09'?" in message


# ---------------------------------------------------------- long value lists ---

def test_long_lists_are_truncated_with_a_total():
    choices = [f"c{i:02d}" for i in range(40)]
    listed = fmt_valid(choices)
    assert listed.startswith("c00, c01") and "c14" in listed and "c15" not in listed
    assert listed.endswith("(40 in total)")
    assert fmt_valid(choices[:15]) == ", ".join(choices[:15])  # at the limit: everything
    message = unknown_message("x.y", "category", "c1", choices)
    assert "Valid categories: c00" in message and "(40 in total)" in message


def test_no_suggestion_when_nothing_is_close():
    message = unknown_message("w", "variable", "zzzzzz", ["sex", "age_group"])
    assert "Did you mean" not in message and message.endswith("Valid variables: sex, age_group")


# ------------------------------------------------------------ cohort details ---

def test_cohort_non_numeric_min_and_empty_result_are_config_errors():
    with pytest.raises(ConfigError, match=r"cohort\.filters\[0\]:.*not numeric"):
        run_recipe(_cfg(**_cohort({"variable": "sex", "op": "min", "threshold": 3})))
    with pytest.raises(ConfigError, match=r"cohort\.filters\[0\]:.*removed all categories"):
        run_recipe(_cfg(**_cohort({"variable": "age_group", "op": "max", "threshold": -1})))


def test_second_filter_is_checked_against_what_the_first_left():
    cfg = _cfg(**_cohort(_equals("age_group", "00-04"), _equals("age_group", "05-09")))
    with pytest.raises(ConfigError, match=r"filters\[1\]\.values: category '05-09' exists in the "
                                          r"dictionary but an earlier rule .* removed it"):
        run_recipe(cfg)


def test_oversample_of_a_category_the_cohort_removed_says_so():
    cfg = _cfg(
        **_cohort(_equals("iccc_category", "I Leukemias", "II Lymphomas")),
        oversample={"variable": "iccc_category", "values": ["V Retinoblastoma"]},
    )
    with pytest.raises(ConfigError, match=r"oversample\.values: category 'V Retinoblastoma' exists "
                                          r"in the dictionary but an earlier rule"):
        run_recipe(cfg)


# ------------------------------------------------ valid configs are unaffected ---

def test_stage_aware_references_that_run_today_still_run(tmp_path):
    # An override may name categories a marginals table narrowed away (it replaces the whole
    # variable), a survival spec may name a group the cohort removed, and a cross-tab may
    # keep rows for a category the cohort removed.
    ages = tmp_path / "ages.json"
    ages.write_text(json.dumps({"age_group": {"10-14": 1, "15-19": 1}}))
    cfg = _cfg(
        targets={
            "marginals": {"age_group": {"00-04": 1, "05-09": 1}},
            "overrides": {"tables": str(ages)},
            "survival": {"group_col": "iccc_category", "specs": {
                "V Retinoblastoma": {"s5": 0.9}, "I Leukemias": {"s5": 0.8}}},
        },
        cohort={"filters": [_equals("iccc_category", "I Leukemias", "II Lymphomas")]},
    )
    bundle = run_recipe(cfg)
    assert bundle["warnings"] == [] and set(bundle["data"]["age_group"]) <= {"10-14", "15-19"}

    cfg = _cfg(
        **_joints(["sex", "age_group"]),
        cohort={"filters": [{"variable": "age_group", "op": "max", "threshold": 14}]},
    )
    assert run_recipe(cfg)["warnings"] == []


def test_marginals_may_supply_a_variable_that_no_frequency_suppress_removed():
    cfg = {
        "metadata": "examples/cookbook/mini_nccr.ttl", "source": "CTC", "n": 200, "seed": 1,
        "profile": "marginals_only", "no_frequency": "suppress",
        "targets": {"marginals": {"race": {"White": 3, "Black": 1}}},
    }
    bundle = run_recipe(cfg)
    assert bundle["warnings"] == [] and set(bundle["data"]["race"]) <= {"White", "Black"}
    cfg["targets"]["marginals"] = {"race": {"Whte": 1}}
    with pytest.raises(ConfigError, match=r"targets\.marginals\.race: unknown category 'Whte'"):
        run_recipe(cfg)


def test_default_group_is_not_an_unknown_group():
    assert run_recipe(_cfg(**_survival({"__default__": 0.8})))["warnings"] == []


# -------------------------------------------------------------- __default__ ---

def _event_share(bundle, group):
    df = bundle["data"]
    return df.loc[df["iccc_category"] == group, "event"].mean()


def test_default_spec_applies_to_unlisted_groups():
    listed = {"V Retinoblastoma": {"s5": 0.97}}
    low = run_recipe(_cfg(n=3000, **_survival({**listed, "__default__": 0.2})))
    plain = run_recipe(_cfg(n=3000, **_survival(listed)))
    assert _event_share(low, "I Leukemias") > _event_share(plain, "I Leukemias") + 0.3


def test_default_spec_equal_to_builtin_changes_nothing():
    listed = {"V Retinoblastoma": {"s5": 0.97}}
    a = run_recipe(_cfg(n=500, **_survival(listed)))["data"]
    b = run_recipe(_cfg(n=500, **_survival({**listed, "__default__": 0.80})))["data"]
    assert a.equals(b)


def test_default_spec_is_validated_like_any_spec():
    with pytest.raises(ConfigError, match=r"specs\.__default__: invalid survival spec"):
        run_recipe(_cfg(**_survival({"__default__": {"nope": 1}})))


# ------------------------------------------------------------------- strict ---

def test_strict_must_be_a_boolean():
    with pytest.raises(ConfigError, match=r"strict: expected true or false, got 'no'"):
        run_recipe(_cfg(strict="no"))


def test_strict_false_downgrades_each_mistake_to_a_manifest_warning(tmp_path):
    cfg = _cfg(
        strict=False,
        targets={
            "marginals": {"age_group": {"00-04": 1, "05-9": 1}, "agegroup": {"a": 1}},
            "survival": {"group_col": "iccc_category", "specs": {"V Retinoblastom": 0.5}},
        },
        cohort={"filters": [_equals("age_group", "00-04", "05-09"), _equals("agegrp", "x")]},
        oversample={"variable": "iccc_category", "values": ["V Retinoblastom"]},
        constraints={"file": _rules_file(tmp_path)},
    )
    bundle = run_recipe(cfg)
    warnings = "\n".join(bundle["warnings"])
    for needle in [
        "targets.marginals.age_group: unknown category '05-9'",
        "targets.marginals: unknown variable 'agegroup'",
        "cohort.filters[0].values: category '05-09' exists in the dictionary",
        "cohort.filters[1].variable: unknown variable 'agegrp'",
        "oversample: values not found in 'iccc_category'",
        "targets.survival.specs: unknown group 'V Retinoblastom'",
        "constraints.file[0].target_col: unknown column 'gleasonScoreClinicalRecode'",
    ]:
        assert needle in warnings, f"{needle!r} not in:\n{warnings}"
    assert "agegroup" in bundle["data"].columns  # run goes on as it did before this check
    assert (bundle["warnings"][0].endswith("(strict: false, category kept as written)"))
    manifest = json.loads((write_run(bundle, tmp_path / "o") / "manifest.json").read_text())
    assert manifest["strict"] is False and manifest["warnings"] == bundle["warnings"]
    assert manifest["config"]["strict"] is False


def test_strict_false_still_refuses_what_cannot_run(tmp_path):
    with pytest.raises(ConfigError, match=r"cohort\.filters\[0\]\.values: no value matches"):
        run_recipe(_cfg(strict=False, **_cohort(_equals("age_group", "05-9"))))
    with pytest.raises(ConfigError, match=r"group_col: unknown column"):
        run_recipe(_cfg(strict=False, **_survival({"x": 0.5}, group_col="nope")))
    with pytest.raises(ConfigError, match=r"oversample\.variable: unknown variable"):
        run_recipe(_cfg(strict=False, oversample={"variable": "nope", "values": ["a"]}))


def test_strict_default_is_on_and_recorded(tmp_path):
    bundle = run_recipe(_cfg(**_marginals({"00-04": 1})))
    assert bundle["strict"] is True
    manifest = json.loads((write_run(bundle, tmp_path) / "manifest.json").read_text())
    assert manifest["strict"] is True and "strict" not in manifest["config"]


def test_legacy_style_recipes_stay_lenient_unless_they_ask_otherwise():
    legacy = {
        "metadata": DICT, "n": 100, "seed": 1,
        "override_marginals": {"age_group": {"00-04": 1, "05-9": 1}},
    }
    bundle = run_recipe(legacy)
    assert bundle["strict"] is False
    assert "05-9" in set(bundle["data"]["age_group"]) and bundle["warnings"]
    with pytest.raises(ConfigError, match="unknown category '05-9'"):
        run_recipe({**legacy, "strict": True})
