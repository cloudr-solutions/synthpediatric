"""The ``conditional`` rule: sample a grouping variable, then targets given the group.

Config key ``targets.conditional`` (rule order 55, stage ``generate``). The table of a
published source (for example age and sex by cancer group) is read as a mix of groups and,
for each group, one distribution per target. Records are drawn sequentially: the group
from the mix, then each target independently from its conditional given the group.

The rule keeps the output coherent:

- an *age anchor* variable is sampled in user bins (a bin may be a union of several anchor
  bands, split by weights); every other age variable is derived from the anchor value;
- when the group is an ICCC major group, every ICCC subgroup variable is derived from it;
- groups of the dictionary that the table does not cover need an explicit treatment;
- the provenance block carries a minimum-cell disclosure check (default 16 for
  ``origin: cgc_aggregate``) that refuses the whole run before anything is generated.

``apply`` (called by the rule registry) reads and checks the config against the dictionary
and builds a plan; nothing is sampled there. ``finalize`` (called by ``recipe.run_recipe``)
samples the plan on the records ``generate`` produced, applies the consistency rules and
only then the ``constraints`` ruleset. Verification, derivation and mix tables are returned
as extra run outputs in ``Context.extra_tables``.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .config import (
    ConfigError,
    as_int,
    as_label,
    as_number,
    as_str,
    check_choice,
    check_keys,
    file_sha256,
    fmt_choices,
    fmt_valid,
    unknown_message,
)

RULE_ORDER = 55
ORIGINS = ("cgc_aggregate", "seer_stat", "literature", "assumption")
DEFAULT_MIN_CELL = {"cgc_aggregate": 16}
MIX_BASES = ("counts", "percent", "published_marginal")
TARGET_BASES = ("counts", "percent")
TREATMENTS = ("published_age_mix", "same_as_covered_total", "published_marginal", "exclude")
PERCENT_TOLERANCE = 1.0
OPEN_HI = 999  # upper edge of an open band such as '85+ years'
UNKNOWN = "Unknown"

DERIVATION_FILE = "conditional_derivation.csv"
MIX_FILE = "conditional_group_mix.csv"
VERIFY_FILE = "conditional_targets_vs_generated.csv"


class DisclosureRefusal(ConfigError):
    """A count below the minimum cell size: the run is refused and nothing is generated."""


# --------------------------------------------------------------------------- #
# Schema (shape only, no data access)
# --------------------------------------------------------------------------- #

def _norm_provenance(where: str, value: Any) -> Dict[str, Any]:
    check_keys(
        where, value, ("source", "date", "origin", "note", "min_cell", "override_reason"),
        required=("source", "date", "origin"),
    )
    when = value["date"]
    out: Dict[str, Any] = {
        "source": as_str(f"{where}.source", value["source"]),
        "date": when.isoformat() if isinstance(when, _dt.date) else as_str(f"{where}.date", when),
        "origin": check_choice(f"{where}.origin", value["origin"], ORIGINS),
    }
    if value.get("note") is not None:
        out["note"] = as_str(f"{where}.note", value["note"])
    if value.get("override_reason") is not None:
        out["override_reason"] = as_str(f"{where}.override_reason", value["override_reason"])
    if value.get("min_cell") is not None:
        out["min_cell"] = as_int(f"{where}.min_cell", value["min_cell"], 0)
        if out["min_cell"] == 0 and not out.get("override_reason"):
            raise ConfigError(
                f"{where}.min_cell: 0 switches the minimum-cell check off and needs a "
                f"non-empty '{where}.override_reason' stating why"
            )
    return out


def _norm_values(where: str, value: Any, positive: bool = False) -> Dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ConfigError(f"{where}: expected a non-empty mapping of label -> number")
    return {
        str(as_label(f"{where} key", k)): as_number(
            f"{where}[{k!r}]", v, positive=positive, nonneg=not positive
        )
        for k, v in value.items()
    }


def _norm_group(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, ("variable", "labels", "mix"), required=("variable", "mix"))
    out: Dict[str, Any] = {"variable": as_str(f"{where}.variable", value["variable"])}
    if value.get("labels") is not None:
        labels = value["labels"]
        if not isinstance(labels, Mapping) or not labels:
            raise ConfigError(
                f"{where}.labels: expected a mapping of user label -> dictionary label"
            )
        out["labels"] = {
            str(as_label(f"{where}.labels key", k)): str(as_label(f"{where}.labels[{k!r}]", v))
            for k, v in labels.items()
        }
    mix = value["mix"]
    check_keys(f"{where}.mix", mix, ("basis", "values"), required=("basis",))
    basis = check_choice(f"{where}.mix.basis", mix["basis"], MIX_BASES)
    out["mix"] = {"basis": basis}
    if basis == "published_marginal":
        if "values" in mix:
            raise ConfigError(
                f"{where}.mix.values: not allowed with basis 'published_marginal' "
                "(the mix is the published marginal of the group variable)"
            )
    else:
        if "values" not in mix:
            raise ConfigError(f"{where}.mix: basis '{basis}' requires 'values'")
        out["mix"]["values"] = _norm_values(f"{where}.mix.values", mix["values"])
    return out


def _norm_age(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, ("anchor", "bins", "split"), required=("anchor", "bins"))
    bins = value["bins"]
    if not isinstance(bins, Mapping) or not bins:
        raise ConfigError(f"{where}.bins: expected a non-empty mapping of bin label -> definition")
    out_bins: Dict[str, Any] = {}
    for name, spec in bins.items():
        w = f"{where}.bins[{name!r}]"
        key = str(as_label(f"{where}.bins key", name))
        if isinstance(spec, Mapping):
            check_keys(w, spec, ("years",), required=("years",))
            years = spec["years"]
            if not isinstance(years, list) or len(years) != 2:
                raise ConfigError(f"{w}.years: expected [lo, hi]")
            lo, hi = as_int(f"{w}.years[0]", years[0], 0), as_int(f"{w}.years[1]", years[1], 0)
            if lo > hi:
                raise ConfigError(f"{w}.years: lo must be <= hi, got [{lo}, {hi}]")
            out_bins[key] = {"years": [lo, hi]}
        elif isinstance(spec, list) and spec:
            out_bins[key] = [str(as_label(f"{w}[{i}]", lab)) for i, lab in enumerate(spec)]
        else:
            raise ConfigError(
                f"{w}: expected {{years: [lo, hi]}} or a non-empty list of anchor labels"
            )
    out: Dict[str, Any] = {"anchor": as_str(f"{where}.anchor", value["anchor"]), "bins": out_bins}
    if value.get("split") is not None:
        split = value["split"]
        if not isinstance(split, Mapping) or not split:
            raise ConfigError(
                f"{where}.split: expected a mapping of bin -> {{anchor label: weight}}"
            )
        out["split"] = {
            str(as_label(f"{where}.split key", b)): _norm_values(
                f"{where}.split[{b!r}]", weights, positive=True
            )
            for b, weights in split.items()
        }
    return out


def _norm_scope(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, ("age_years",), required=("age_years",))
    years = value["age_years"]
    if not isinstance(years, list) or len(years) != 2:
        raise ConfigError(f"{where}.age_years: expected [lo, hi]")
    lo, hi = as_int(f"{where}.age_years[0]", years[0], 0), as_int(
        f"{where}.age_years[1]", years[1], 0
    )
    if lo > hi:
        raise ConfigError(f"{where}.age_years: lo must be <= hi, got [{lo}, {hi}]")
    return {"age_years": [lo, hi]}


def _norm_targets(where: str, value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: expected a non-empty list of targets")
    out, seen = [], set()
    for i, item in enumerate(value):
        w = f"{where}[{i}]"
        check_keys(
            w, item, ("variable", "basis", "by_group", "file"), required=("variable", "basis")
        )
        var = as_str(f"{w}.variable", item["variable"])
        if var in seen:
            raise ConfigError(f"{w}.variable: '{var}' is listed twice; targets must be unique")
        seen.add(var)
        if ("by_group" in item) == ("file" in item):
            raise ConfigError(f"{w}: give exactly one of 'by_group' (inline) or 'file' (a CSV)")
        entry: Dict[str, Any] = {
            "variable": var, "basis": check_choice(f"{w}.basis", item["basis"], TARGET_BASES),
        }
        if "file" in item:
            entry["file"] = as_str(f"{w}.file", item["file"])
        else:
            by_group = item["by_group"]
            if not isinstance(by_group, Mapping) or not by_group:
                raise ConfigError(f"{w}.by_group: expected a non-empty mapping of group -> row")
            entry["by_group"] = {
                str(as_label(f"{w}.by_group key", g)): _norm_values(f"{w}.by_group[{g!r}]", row)
                for g, row in by_group.items()
            }
        out.append(entry)
    return out


def _norm_uncovered(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, ("groups",), required=("groups",))
    groups = value["groups"]
    if not isinstance(groups, Mapping) or not groups:
        raise ConfigError(f"{where}.groups: expected a non-empty mapping of group -> entry")
    out: Dict[str, Any] = {}
    for name, entry in groups.items():
        w = f"{where}.groups[{name!r}]"
        check_keys(w, entry, ("share", "targets"), required=("share",))
        share = entry["share"]
        share = "exclude" if share == "exclude" else as_number(f"{w}.share", share, nonneg=True)
        item: Dict[str, Any] = {"share": share}
        treatments = entry.get("targets")
        if treatments is not None:
            if not isinstance(treatments, Mapping) or not treatments:
                raise ConfigError(
                    f"{w}.targets: expected a mapping of target variable -> treatment"
                )
            clean: Dict[str, Any] = {}
            for var, treat in treatments.items():
                tw = f"{w}.targets[{var!r}]"
                if isinstance(treat, Mapping):
                    check_keys(tw, treat, ("values",), required=("values",))
                    clean[str(var)] = {"values": _norm_values(f"{tw}.values", treat["values"])}
                else:
                    clean[str(var)] = check_choice(tw, treat, TREATMENTS)
                    if treat == "exclude" and share != "exclude":
                        raise ConfigError(
                            f"{tw}: treatment 'exclude' excludes the group, so its share must "
                            f"be 'exclude' too (got {share!r})"
                        )
            item["targets"] = clean
        out[str(as_label(f"{where}.groups key", name))] = item
    return {"groups": out}


def _norm_conditional(where: str, value: Any) -> Dict[str, Any]:
    """Shape of ``targets.conditional``. Names and labels are checked in ``apply``."""
    check_keys(
        where, value, ("provenance", "group", "scope", "age", "targets", "uncovered"),
        required=("provenance", "group", "targets"),
    )
    out: Dict[str, Any] = {
        "provenance": _norm_provenance(f"{where}.provenance", value["provenance"]),
        "group": _norm_group(f"{where}.group", value["group"]),
    }
    if value.get("scope") is not None:
        if value.get("age") is None:
            raise ConfigError(f"{where}.scope: requires an 'age' section")
        out["scope"] = _norm_scope(f"{where}.scope", value["scope"])
    if value.get("age") is not None:
        out["age"] = _norm_age(f"{where}.age", value["age"])
    out["targets"] = _norm_targets(f"{where}.targets", value["targets"])
    variables = [t["variable"] for t in out["targets"]]
    if out["group"]["variable"] in variables:
        raise ConfigError(
            f"{where}.targets: '{out['group']['variable']}' is the group variable and cannot "
            "also be a target"
        )
    if "age" in out and out["age"]["anchor"] not in variables:
        raise ConfigError(
            f"{where}.age.anchor: '{out['age']['anchor']}' needs an entry in targets "
            f"(targets list: {fmt_valid(variables)})"
        )
    if value.get("uncovered") is not None:
        out["uncovered"] = _norm_uncovered(f"{where}.uncovered", value["uncovered"])
    return out


# --------------------------------------------------------------------------- #
# Age and ICCC label parsing
# --------------------------------------------------------------------------- #

_BAND = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)|(\+))?\s*(?:years?)?\s*$", re.IGNORECASE)
_ICCC_NUMERAL = re.compile(r"^([IVX]+)(?:[a-z]\d*)?[ .]")


def is_unknown(label: object) -> bool:
    return str(label).strip().lower() == UNKNOWN.lower()


def parse_band(label: object) -> Optional[Tuple[int, int]]:
    """Years covered by an age label ('00 years', '01-04 years', '85+ years', '00-04')."""
    m = _BAND.match(str(label))
    if not m:
        return None
    lo = int(m.group(1))
    if m.group(3):
        return lo, OPEN_HI
    return lo, int(m.group(2)) if m.group(2) else lo


def _cats(vm: Any) -> List[str]:
    return [str(c) for c in vm.categories]


def _weights(vm: Any, labels: Sequence[str]) -> np.ndarray:
    """Published weights of ``labels`` restricted and renormalised (uniform if all zero)."""
    by_label = {str(c): float(w) for c, w in zip(vm.categories, vm.weights)}
    w = np.array([by_label.get(lab, 0.0) for lab in labels], dtype=float)
    return w / w.sum() if w.sum() > 0 else np.full(len(labels), 1.0 / len(labels))


def _fmt_bands(bands: Sequence[Tuple[str, int, int]]) -> str:
    return fmt_valid([b[0] for b in bands])


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

@dataclass
class TargetPlan:
    variable: str
    basis: str
    is_age: bool
    cats: List[str]  # categories sampled (anchor labels for the age target)
    p: Dict[str, np.ndarray] = field(default_factory=dict)  # group -> probabilities over cats
    report_cats: List[str] = field(default_factory=list)  # user bins for the age target
    report_of: Dict[str, str] = field(default_factory=dict)  # sampled category -> report one


@dataclass
class Plan:
    group_var: str
    groups: List[str]
    group_p: np.ndarray
    targets: List[TargetPlan]
    anchor: Optional[str]
    # derived variable -> source value -> (labels, probabilities)
    age_derivations: Dict[str, Dict[str, Tuple[List[str], np.ndarray]]]
    hierarchy: Dict[str, Dict[str, Tuple[List[str], np.ndarray]]]
    details: Dict[str, Any]


def _base_variable(ctx: Any, name: str) -> Any:
    """The variable as loaded (before cohort/oversample), else as it is now."""
    return ctx.base_dictionary.variables.get(name, ctx.dictionary.variables[name])


def _need_variable(ctx: Any, where: str, name: str) -> None:
    if name not in ctx.dictionary.variables:
        raise ConfigError(unknown_message(where, "variable", name, ctx.dictionary.variables))


# ----- age bins -------------------------------------------------------------

def _anchor_bands(ctx: Any, anchor: str, where: str) -> List[Tuple[str, int, int]]:
    bands = []
    for label in _cats(ctx.dictionary.variables[anchor]):
        if is_unknown(label):
            continue
        parsed = parse_band(label)
        if parsed is None:
            raise ConfigError(
                f"{where}: unmappable label '{label}' in anchor '{anchor}' "
                "(not a year band such as '01-04 years' or '85+ years')"
            )
        bands.append((label, parsed[0], parsed[1]))
    return sorted(bands, key=lambda b: (b[1], b[2]))


def _bands_for_years(
    bands: Sequence[Tuple[str, int, int]], lo: int, hi: int, where: str
) -> List[str]:
    chosen = [b for b in bands if b[1] >= lo and b[2] <= hi]
    ok = bool(chosen) and chosen[0][1] == lo and chosen[-1][2] == hi
    ok = ok and all(a[2] + 1 == b[1] for a, b in zip(chosen, chosen[1:]))
    if not ok:
        raise ConfigError(
            f"{where}: years [{lo}, {hi}] do not start and end on anchor band edges, or the "
            f"anchor has no band for part of them (bands present after the cohort: "
            f"{_fmt_bands(bands)})"
        )
    return [b[0] for b in chosen]


def _resolve_age(ctx: Any, p: Dict[str, Any], where: str) -> Dict[str, Any]:
    age = p["age"]
    anchor = age["anchor"]
    bands = _anchor_bands(ctx, anchor, f"{where}.age.anchor")
    cats = [b[0] for b in bands]
    bins: Dict[str, List[str]] = {}
    owner: Dict[str, str] = {}
    for name, spec in age["bins"].items():
        w = f"{where}.age.bins[{name!r}]"
        if isinstance(spec, dict):
            labels = _bands_for_years(bands, spec["years"][0], spec["years"][1], w)
        else:
            labels = []
            for lab in spec:
                if lab not in cats:
                    raise ConfigError(unknown_message(w, "anchor label", lab, cats))
                labels.append(lab)
        for lab in labels:
            if lab in owner:
                raise ConfigError(
                    f"{where}.age.bins: anchor label '{lab}' is in both '{owner[lab]}' and "
                    f"'{name}'; bins must be disjoint"
                )
            owner[lab] = name
        bins[name] = sorted(labels, key=cats.index)
    if "scope" in p:
        lo, hi = p["scope"]["age_years"]
        scope = set(_bands_for_years(bands, lo, hi, f"{where}.scope.age_years"))
        missing = [c for c in cats if c in scope and c not in owner]
        extra = [c for c in owner if c not in scope]
        if missing or extra:
            raise ConfigError(
                f"{where}.age.bins: bins must cover exactly the scope [{lo}, {hi}]. "
                f"Scope bands missing from the bins: {missing or 'none'}. "
                f"Bin bands outside the scope: {extra or 'none'}"
            )
    scope_labels = [c for c in cats if c in owner]

    # Split of the anchor labels inside each bin.
    anchor_vm = ctx.dictionary.variables[anchor]
    cfg_split = age.get("split", {})
    for name in cfg_split:
        if name not in bins:
            raise ConfigError(unknown_message(f"{where}.age.split", "bin", name, bins))
    split: Dict[str, Tuple[List[str], np.ndarray]] = {}
    split_info: Dict[str, Any] = {}
    for name, labels in bins.items():
        if name in cfg_split:
            given = cfg_split[name]
            for lab in given:
                if lab not in labels:
                    raise ConfigError(unknown_message(
                        f"{where}.age.split[{name!r}]", "anchor label", lab, labels
                    ))
            absent = [lab for lab in labels if lab not in given]
            if absent:
                raise ConfigError(
                    f"{where}.age.split[{name!r}]: missing weight for anchor label(s) {absent}"
                )
            w = np.array([given[lab] for lab in labels], dtype=float)
            probs, source = w / w.sum(), "config"
        else:
            probs = _weights(anchor_vm, labels)
            published = sum(
                float(x) for c, x in zip(anchor_vm.categories, anchor_vm.weights)
                if str(c) in labels
            )
            source = "published_restricted" if published > 0 else "uniform"
        split[name] = (labels, probs)
        split_info[name] = {
            "labels": {lab: float(pr) for lab, pr in zip(labels, probs)}, "source": source,
        }
    return {
        "anchor": anchor, "bins": bins, "owner": owner, "scope_labels": scope_labels,
        "split": split, "split_info": split_info,
    }


def _age_variables(ctx: Any, where: str) -> List[str]:
    found = []
    for name, vm in ctx.dictionary.variables.items():
        if not name.lower().startswith("age"):
            continue
        for label in _cats(vm):
            if not is_unknown(label) and parse_band(label) is None:
                raise ConfigError(
                    f"{where}: age variable '{name}' has unmappable label '{label}' "
                    "(not a year band or single year), so its consistency with the anchor "
                    "cannot be checked"
                )
        found.append(name)
    return found


def _age_derivation(
    ctx: Any, var: str, scope_labels: Sequence[str], anchor_bands: Mapping[str, Tuple[int, int]],
    where: str,
) -> Tuple[Dict[str, Tuple[List[str], np.ndarray]], List[Dict[str, Any]]]:
    vm = ctx.dictionary.variables[var]
    labels = [(c, parse_band(c)) for c in _cats(vm) if not is_unknown(c)]
    table: Dict[str, Tuple[List[str], np.ndarray]] = {}
    rows: List[Dict[str, Any]] = []
    for a in scope_labels:
        lo, hi = anchor_bands[a]
        containing = [c for c, b in labels if b[0] <= lo and b[1] >= hi]
        inside = [(c, b) for c, b in labels if b[0] >= lo and b[1] <= hi]
        straddle = [
            c for c, b in labels
            if b[0] <= hi and b[1] >= lo and c not in containing and (c, b) not in inside
        ]
        if straddle:
            raise ConfigError(
                f"{where}: label '{straddle[0]}' of '{var}' straddles the edge of anchor "
                f"band '{a}', so '{var}' cannot be derived consistently"
            )
        if len(containing) == 1:
            table[a] = ([containing[0]], np.array([1.0]))
            rows.append({
                "anchor_or_group_label": a, "variable": var, "derived_label": containing[0],
                "method": "deterministic", "probability": 1.0,
            })
            continue
        if len(containing) > 1:
            raise ConfigError(
                f"{where}: '{var}' has several labels containing anchor band '{a}': {containing}"
            )
        inside = sorted(inside, key=lambda x: x[1])
        ok = bool(inside) and inside[0][1][0] == lo and inside[-1][1][1] == hi
        ok = ok and all(x[1][1] + 1 == y[1][0] for x, y in zip(inside, inside[1:]))
        if not ok:
            raise ConfigError(
                f"{where}: '{var}' has no label (or an incomplete set of labels) for anchor "
                f"band '{a}'"
            )
        names = [c for c, _ in inside]
        probs = _weights(vm, names)
        table[a] = (names, probs)
        for c, pr in zip(names, probs):
            rows.append({
                "anchor_or_group_label": a, "variable": var, "derived_label": c,
                "method": "sampled", "probability": float(pr),
            })
    return table, rows


def _hierarchy_derivation(
    ctx: Any, group_var: str, groups: Sequence[str], var: str, where: str
) -> Tuple[Dict[str, Tuple[List[str], np.ndarray]], List[Dict[str, Any]]]:
    base_groups = _cats(_base_variable(ctx, group_var))
    numerals: Dict[str, str] = {}
    not_classified: Optional[str] = None
    for g in base_groups:
        m = re.match(r"^([IVX]+)[ .]", g)
        if m:
            numerals[m.group(1)] = g
        elif g.startswith("Not classified"):
            not_classified = g
    vm = ctx.dictionary.variables[var]
    children: Dict[str, List[str]] = {}
    for label in _cats(vm):
        if is_unknown(label):
            continue
        parent = None
        if label.startswith("Not classified"):
            parent = not_classified
        else:
            m = _ICCC_NUMERAL.match(label)
            if m:
                parent = numerals.get(m.group(1))
        if parent is None:
            raise ConfigError(
                f"{where}: unmappable label '{label}' in '{var}': it names no group of "
                f"'{group_var}' (groups: {fmt_valid(base_groups)})"
            )
        children.setdefault(parent, []).append(label)
    table: Dict[str, Tuple[List[str], np.ndarray]] = {}
    rows: List[Dict[str, Any]] = []
    for g in groups:
        kids = children.get(g)
        if not kids:
            raise ConfigError(f"{where}: '{var}' has no label belonging to group '{g}'")
        probs = _weights(vm, kids)
        table[g] = (kids, probs)
        for c, pr in zip(kids, probs):
            rows.append({
                "anchor_or_group_label": g, "variable": var, "derived_label": c,
                "method": "sampled", "probability": float(pr),
            })
    return table, rows


# ----- table inputs ---------------------------------------------------------

def _check_percent(where: str, row: Mapping[str, float]) -> None:
    total = float(sum(row.values()))
    if abs(total - 100.0) > PERCENT_TOLERANCE:
        raise ConfigError(f"{where}: percentages sum to {total:g}, expected 100 (+-1 point)")


def _read_csv(ctx: Any, where: str, path: str, columns: Sequence[str]) -> pd.DataFrame:
    if not Path(path).is_file():
        raise ConfigError(f"{where}: file not found: {path}")
    ctx.input_files[path] = file_sha256(path)
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    lacking = [c for c in columns if c not in table.columns]
    if lacking:
        raise ConfigError(
            f"{where}: {path} lacks column(s) {lacking}; expected columns: {fmt_choices(columns)}"
        )
    return table


def _as_group_resolver(ctx: Any, p: Dict[str, Any], where: str):
    gvar = p["group"]["variable"]
    in_scope = _cats(ctx.dictionary.variables[gvar])
    base = _cats(ctx.base_dictionary.variables.get(gvar, ctx.dictionary.variables[gvar]))
    umap = p["group"].get("labels", {})
    for user, label in umap.items():
        if label not in base:
            raise ConfigError(
                unknown_message(f"{where}.group.labels[{user!r}]", "category", label, base)
            )
    dropped: set = set()

    def resolve(label: str, at: str) -> Optional[str]:
        """Dictionary label of a group, or None when a cohort filter removed the group."""
        dl = umap.get(label, label)
        if dl not in base:
            raise ConfigError(unknown_message(at, "group", label, list(umap) + base))
        if dl not in in_scope:
            dropped.add(dl)
            return None
        return dl

    return in_scope, resolve, dropped


@dataclass
class _Table:
    variable: str
    basis: str
    is_age: bool
    from_file: bool
    rows: Dict[str, Dict[str, float]]  # group -> category (user bin / anchor label) -> number


def _read_targets(
    ctx: Any, p: Dict[str, Any], where: str, resolve: Any, age: Optional[Dict[str, Any]],
) -> List[_Table]:
    gvar = p["group"]["variable"]
    anchor = age["anchor"] if age else None
    tables: List[_Table] = []
    for i, t in enumerate(p["targets"]):
        var = t["variable"]
        w = f"{where}.targets[{i}]"
        is_age = var == anchor
        rows: Dict[str, Dict[str, float]] = {}
        if "file" in t:
            path = t["file"]
            frame = _read_csv(ctx, f"{w}.file", path, [gvar, var, "count"])
            for g_raw, cat, raw in zip(frame[gvar], frame[var], frame["count"]):
                try:
                    value = float(raw)
                except ValueError as exc:
                    raise ConfigError(f"{w}.file: non-numeric count {raw!r} in {path}") from exc
                if value < 0:
                    raise ConfigError(f"{w}.file: negative count {raw!r} in {path}")
                g = resolve(g_raw, f"{w}.file ({path}) column {gvar}")
                if g is None:
                    continue
                row = rows.setdefault(g, {})
                row[cat] = row.get(cat, 0.0) + value
        else:
            for g_raw, row in t["by_group"].items():
                g = resolve(g_raw, f"{w}.by_group")
                if g is None:
                    continue
                if g in rows:
                    raise ConfigError(
                        f"{w}.by_group: group '{g}' appears twice (after label mapping)"
                    )
                rows[g] = dict(row)
        tables.append(_Table(var, t["basis"], is_age, "file" in t, rows))
    return tables


def _check_categories(ctx: Any, tab: _Table, age: Optional[Dict[str, Any]], where: str) -> None:
    """Category labels of every row against the dictionary (and the bins for the age target)."""
    base = _cats(_base_variable(ctx, tab.variable))
    now = _cats(ctx.dictionary.variables[tab.variable])
    for g, row in tab.rows.items():
        at = f"{where}.{tab.variable}[{g!r}]"
        if tab.is_age and not tab.from_file:
            bins = list(age["bins"])
            missing = [b for b in bins if b not in row]
            extra = [c for c in row if c not in bins]
            if missing or extra:
                if extra:
                    raise ConfigError(unknown_message(at, "bin", extra[0], bins))
                raise ConfigError(f"{at}: the age row must name every bin. Missing: {missing}")
        elif tab.is_age:
            for c in row:
                if c not in age["owner"]:
                    if c in now:
                        raise ConfigError(
                            f"{at}: anchor label '{c}' is not in the age scope "
                            f"(scope bands: {fmt_valid(age['scope_labels'])})"
                        )
                    raise ConfigError(unknown_message(at, "anchor label", c, now))
        else:
            for c in row:
                if c not in base:
                    raise ConfigError(unknown_message(at, "category", c, base))
                if c not in now:
                    raise ConfigError(
                        f"{at}: category '{c}' exists in the dictionary but an earlier rule "
                        f"(marginals, overrides or cohort) removed it"
                    )


def _row_vector(
    row: Mapping[str, float], cats: Sequence[str], age: Optional[Dict[str, Any]], is_age: bool,
    from_file: bool,
) -> np.ndarray:
    """Values over ``cats`` (anchor labels for the age target: a bin value is split)."""
    vec = np.zeros(len(cats), dtype=float)
    index = {c: i for i, c in enumerate(cats)}
    if is_age and not from_file:
        for name, value in row.items():
            labels, probs = age["split"][name]
            for lab, pr in zip(labels, probs):
                vec[index[lab]] += value * pr
    else:
        for c, value in row.items():
            vec[index[c]] += value
    return vec


# ----- the apply step -------------------------------------------------------

def apply(ctx: Any, p: Dict[str, Any]) -> Dict[str, Any]:
    where = "targets.conditional"
    prov = p["provenance"]
    gvar = p["group"]["variable"]
    age_cfg = p.get("age")
    anchor = age_cfg["anchor"] if age_cfg else None
    tvars = [t["variable"] for t in p["targets"]]
    mix = p["group"]["mix"]
    details: Dict[str, Any] = {
        "provenance": {k: prov[k] for k in ("source", "date", "origin", "note") if k in prov},
    }

    # (1) names
    _need_variable(ctx, f"{where}.group.variable", gvar)
    for i, v in enumerate(tvars):
        _need_variable(ctx, f"{where}.targets[{i}].variable", v)
    if anchor:
        _need_variable(ctx, f"{where}.age.anchor", anchor)

    # derived variables (needed for the joints check)
    age_vars: List[str] = _age_variables(ctx, where) if age_cfg else []
    derived_age = [v for v in age_vars if v != anchor]
    hier_vars: List[str] = []
    if gvar.lower().startswith("iccc"):
        hier_vars = [
            v for v in ctx.dictionary.variables if v.lower().startswith("iccc") and v != gvar
        ]
    for v in derived_age + hier_vars:
        if v in tvars:
            raise ConfigError(
                f"{where}.targets: '{v}' is derived from "
                f"{'the age anchor' if v in derived_age else 'the group variable'} and cannot "
                "also be a target"
            )

    # (2) conflict with joints
    if ctx.joint is not None:
        used = {gvar, *tvars, *derived_age, *hier_vars}
        if anchor:
            used.add(anchor)
        clash = [d for d in ctx.joint.dimensions if d in used]
        if clash:
            raise ConfigError("; ".join(
                f"targets.joints and targets.conditional both use variable {v}" for v in clash
            ))

    # group labels
    in_scope, resolve, dropped = _as_group_resolver(ctx, p, where)

    # (3) and (4) age
    age: Optional[Dict[str, Any]] = None
    if age_cfg:
        age = _resolve_age(ctx, p, where)
        details["age"] = {
            "anchor": anchor, "bins": {b: list(ls) for b, ls in age["bins"].items()},
            "scope_labels": list(age["scope_labels"]), "split": age["split_info"],
        }
        details["age_variables"] = age_vars
        anchor_from_file = any(t["variable"] == anchor and "file" in t for t in p["targets"])
        if age_cfg.get("split") and anchor_from_file:
            raise ConfigError(
                f"{where}.age.split: not used when the age target comes from a file "
                "(the counts give the split)"
            )
    # (5) numbers
    tables = _read_targets(ctx, p, where, resolve, age)
    for tab in tables:
        _check_categories(ctx, tab, age, f"{where}.targets")

    mix_vals: Dict[str, float] = {}
    if mix["basis"] != "published_marginal":
        for lbl, v in mix["values"].items():
            g = resolve(lbl, f"{where}.group.mix.values")
            if g is None:
                continue
            if g in mix_vals:
                raise ConfigError(f"{where}.group.mix.values: group '{g}' appears twice")
            mix_vals[g] = v
    table_groups = set(mix_vals)
    for tab in tables:
        table_groups |= set(tab.rows)
    covered = [g for g in in_scope if g in table_groups]
    for tab in tables:
        lacking = [g for g in covered if g not in tab.rows]
        if lacking:
            raise ConfigError(
                f"{where}: target '{tab.variable}' has no row for group(s) {lacking} "
                "that appear elsewhere in the table"
            )
    if mix["basis"] != "published_marginal":
        lacking = [g for g in covered if g not in mix_vals]
        if lacking:
            raise ConfigError(f"{where}.group.mix.values: no value for group(s) {lacking}")

    # row checks: sums, percent
    for tab in tables:
        for g, row in tab.rows.items():
            at = f"{where}.targets[{tab.variable!r}][{g!r}]"
            total = float(sum(row.values()))
            if total <= 0:
                raise ConfigError(f"{at}: the row sums to zero")
            if tab.basis == "percent":
                _check_percent(at, row)

    # (7) uncovered groups
    unc_cfg = p.get("uncovered", {}).get("groups", {})
    unc_entries: Dict[str, Dict[str, Any]] = {}
    for lbl, entry in unc_cfg.items():
        g = resolve(lbl, f"{where}.uncovered.groups")
        if g is None:
            continue
        if g in covered:
            raise ConfigError(
                f"{where}.uncovered.groups: group '{g}' is in the table, so it is not uncovered"
            )
        unc_entries[g] = entry
    uncovered = [g for g in in_scope if g not in covered]
    missing_groups = [g for g in uncovered if g not in unc_entries]
    if missing_groups:
        raise ConfigError(
            f"{where}.uncovered.groups: the table does not cover group(s) {missing_groups} of "
            f"'{gvar}'. State each one with a share (a number or 'exclude') and a treatment for "
            f"every target ({fmt_valid(tvars)})"
        )
    excluded = [g for g in uncovered if unc_entries[g]["share"] == "exclude"]
    open_groups = [g for g in uncovered if g not in excluded]
    for g in open_groups:
        treat = unc_entries[g].get("targets", {})
        for v in treat:
            if v not in tvars:
                raise ConfigError(unknown_message(
                    f"{where}.uncovered.groups[{g!r}].targets", "target variable", v, tvars
                ))
        lacking = [v for v in tvars if v not in treat]
        if lacking:
            raise ConfigError(
                f"{where}.uncovered.groups[{g!r}]: no treatment for target(s) {lacking}"
            )
        for v, tr in treat.items():
            if tr == "published_age_mix" and not (age and v == anchor):
                raise ConfigError(
                    f"{where}.uncovered.groups[{g!r}].targets[{v!r}]: 'published_age_mix' only "
                    "applies to the age anchor target"
                )
            if tr == "exclude":
                raise ConfigError(
                    f"{where}.uncovered.groups[{g!r}].targets[{v!r}]: treatment 'exclude' "
                    "requires the group share to be 'exclude'"
                )

    # (6) the mix
    gvm = ctx.dictionary.variables[gvar]
    size: Dict[str, float] = {}
    if mix["basis"] == "published_marginal":
        shares = {g: unc_entries[g]["share"] for g in open_groups}
        total_unc = sum(shares.values()) / 100.0
        if total_unc >= 1.0 and covered:
            raise ConfigError(
                f"{where}.uncovered.groups: uncovered shares sum to {total_unc * 100:g} percent "
                "of the total, leaving nothing for the covered groups"
            )
        weights = _weights(gvm, covered) if covered else np.array([])
        mixp = {g: float(w) * (1.0 - total_unc) for g, w in zip(covered, weights)}
        for g in open_groups:
            mixp[g] = shares[g] / 100.0
        norm = sum(mixp.values())
        if norm <= 0:
            raise ConfigError(f"{where}: no group is left to generate")
        mixp = {g: v / norm for g, v in mixp.items()}
    else:
        raw_mix = {g: mix_vals[g] for g in covered}
        for g in open_groups:
            raw_mix[g] = unc_entries[g]["share"]
        total = sum(raw_mix.values())
        if total <= 0:
            raise ConfigError(f"{where}.group.mix: no group has a positive value")
        mixp = {g: v / total for g, v in raw_mix.items()}
        if mix["basis"] == "counts":
            size = dict(raw_mix)
        details["mix_input_total"] = float(total)
    generated_groups = [g for g in in_scope if g in mixp]
    if not generated_groups:
        raise ConfigError(f"{where}: no group is left to generate")
    details["dropped_by_cohort"] = sorted(dropped)
    details["groups"] = generated_groups
    details["excluded_groups"] = excluded

    # group sizes from CSV counts when the mix has none
    for tab in tables:
        if tab.from_file and tab.basis == "counts":
            for g in covered:
                size.setdefault(g, float(sum(tab.rows[g].values())))

    # provenance notes: row sums against the group counts
    notes = []
    if mix["basis"] == "counts":
        for tab in tables:
            if tab.basis != "counts":
                continue
            for g in covered:
                row_sum = float(sum(tab.rows[g].values()))
                notes.append({
                    "group": g, "target": tab.variable, "row_sum": row_sum,
                    "group_count": float(mix_vals[g]), "difference": row_sum - float(mix_vals[g]),
                })
    details["provenance_notes"] = notes

    # target plans
    target_plans: List[TargetPlan] = []
    absent: List[str] = []
    treatments_log: List[Dict[str, Any]] = []
    cell_input: List[Tuple[str, str, str, float, str]] = []  # group, target, category, value, kind
    covered_w = {g: mixp[g] for g in covered if g in mixp}
    covered_total = sum(covered_w.values())
    for tab in tables:
        var = tab.variable
        if tab.is_age:
            cats = list(age["scope_labels"])
        else:
            cats = []
            for g in covered:
                cats += [c for c in tab.rows[g] if c not in cats]
            listed = list(cats)
            for g in open_groups:
                tr = unc_entries[g]["targets"][var]
                if isinstance(tr, dict):
                    for c in tr["values"]:
                        if c not in cats:
                            cats.append(c)
        tp = TargetPlan(variable=var, basis=tab.basis, is_age=tab.is_age, cats=cats)
        if tab.is_age:
            tp.report_cats = list(age["bins"])
            tp.report_of = {lab: age["owner"][lab] for lab in cats}
        else:
            tp.report_cats = cats
            tp.report_of = {c: c for c in cats}
        raw: Dict[str, np.ndarray] = {}
        for g in covered:
            row = tab.rows[g]
            raw[g] = _row_vector(row, cats, age, tab.is_age, tab.from_file)
            if not tab.is_age or tab.from_file:
                absent += [f"{g} | {var} | {c}" for c in cats if c not in row]
            _cells_for_row(
                cell_input, g, var, tab, row, age, size.get(g), tab.basis, from_file=tab.from_file
            )
        pooled: Optional[np.ndarray] = None
        for g in open_groups:
            tr = unc_entries[g]["targets"][var]
            if tr == "same_as_covered_total":
                if not covered:
                    raise ConfigError(
                        f"{where}.uncovered.groups[{g!r}].targets[{var!r}]: "
                        "'same_as_covered_total' needs at least one covered group"
                    )
                if pooled is None:
                    if tab.basis == "counts":
                        pooled = sum(raw[c] for c in covered)
                    else:
                        pooled = sum(
                            covered_w[c] / covered_total * (raw[c] / raw[c].sum()) for c in covered
                        )
                vec = pooled
                desc: Any = "same_as_covered_total"
            elif tr in ("published_marginal", "published_age_mix"):
                vm = ctx.dictionary.variables[var]
                if tab.is_age:
                    vec = _weights(vm, cats)
                else:
                    vec = np.zeros(len(cats))
                    idx = [cats.index(c) for c in listed if c in _cats(vm)]
                    labs = [cats[i] for i in idx]
                    if labs:
                        vec[idx] = _weights(vm, labs)
                desc = tr
            else:
                row = tr["values"]
                at = f"{where}.uncovered.groups[{g!r}].targets[{var!r}]"
                if tab.is_age:
                    bins = list(age["bins"])
                    missing = [b for b in bins if b not in row]
                    extra = [c for c in row if c not in bins]
                    if missing or extra:
                        raise ConfigError(
                            f"{at}: values must name every age bin. Missing: {missing}. "
                            f"Unknown: {extra}. Valid bins: {fmt_valid(bins)}"
                        )
                else:
                    base = _cats(ctx.base_dictionary.variables[var])
                    for c in row:
                        if c not in base:
                            raise ConfigError(unknown_message(at, "category", c, base))
                if sum(row.values()) <= 0:
                    raise ConfigError(f"{at}: the values sum to zero")
                if tab.basis == "percent":
                    _check_percent(at, row)
                vec = _row_vector(row, cats, age, tab.is_age, False)
                desc = {"values": dict(row)}
                _cells_for_row(
                    cell_input, g, var, tab, row, age, size.get(g), tab.basis, from_file=False
                )
            raw[g] = np.asarray(vec, dtype=float)
            treatments_log.append({
                "group": g, "target": var, "treatment": desc,
            })
        for g in generated_groups:
            tp.p[g] = raw[g] / raw[g].sum()
        target_plans.append(tp)
    details["absent_cells"] = absent
    details["uncovered"] = [
        {"group": g, "share": unc_entries[g]["share"], "as_assumption": True,
         "treatments": [t for t in treatments_log if t["group"] == g]}
        for g in open_groups
    ] + [{"group": g, "share": "exclude", "as_assumption": True} for g in excluded]

    # group-size cells (counts mix)
    if mix["basis"] == "counts":
        for g in covered:
            cell_input.append((g, "(group size)", "-", float(mix_vals[g]), "counted"))
        for g in open_groups:
            cell_input.append((g, "(group size)", "-", float(unc_entries[g]["share"]), "counted"))

    # DISCLOSURE
    _disclosure(prov, cell_input, details)

    # (5b) consistency plan
    age_derivations: Dict[str, Dict[str, Tuple[List[str], np.ndarray]]] = {}
    hierarchy: Dict[str, Dict[str, Tuple[List[str], np.ndarray]]] = {}
    derivation_rows: List[Dict[str, Any]] = []
    if age is not None:
        bands = {b[0]: (b[1], b[2]) for b in _anchor_bands(ctx, anchor, where)}
        for v in derived_age:
            table, rows = _age_derivation(ctx, v, age["scope_labels"], bands, f"{where}.age")
            age_derivations[v] = table
            derivation_rows += rows
    else:
        details["age_variables"] = []
    if hier_vars:
        for v in hier_vars:
            table, rows = _hierarchy_derivation(ctx, gvar, generated_groups, v, where)
            hierarchy[v] = table
            derivation_rows += rows
        details["hierarchy"] = {"group_variable": gvar, "derived": hier_vars}
    else:
        details["hierarchy"] = "none detected"
    ctx.extra_tables[DERIVATION_FILE] = pd.DataFrame(
        derivation_rows,
        columns=["anchor_or_group_label", "variable", "derived_label", "method", "probability"],
    )

    ctx.conditional = Plan(
        group_var=gvar, groups=generated_groups,
        group_p=np.array([mixp[g] for g in generated_groups]), targets=target_plans,
        anchor=anchor, age_derivations=age_derivations, hierarchy=hierarchy, details=details,
    )
    return details


def _cells_for_row(
    cells: List[Tuple[str, str, str, float, str]], group: str, var: str, tab: _Table,
    row: Mapping[str, float], age: Optional[Dict[str, Any]], size: Optional[float], basis: str,
    from_file: bool,
) -> None:
    """Cells of one row at user-bin level, for the disclosure check (counted or implied)."""
    values: Dict[str, float] = {}
    if tab.is_age and from_file:
        for lab, v in row.items():
            values[age["owner"][lab]] = values.get(age["owner"][lab], 0.0) + v
    else:
        values = dict(row)
    for cat, v in values.items():
        if basis == "counts":
            cells.append((group, var, cat, float(v), "counted"))
        elif size is not None:
            cells.append((group, var, cat, float(v) / 100.0 * size, "implied"))
        else:
            cells.append((group, var, cat, float("nan"), "unchecked"))


# ----- disclosure ----------------------------------------------------------

def _disclosure(
    prov: Mapping[str, Any], cells: List[Tuple[str, str, str, float, str]], details: Dict[str, Any]
) -> None:
    origin = prov["origin"]
    explicit = prov.get("min_cell")
    if explicit is not None:
        threshold, supplied = int(explicit), "config"
    elif origin in DEFAULT_MIN_CELL:
        threshold, supplied = DEFAULT_MIN_CELL[origin], "default"
    else:
        threshold, supplied = None, None
    checkable = [c for c in cells if c[4] != "unchecked"]
    info: Dict[str, Any] = {
        "value": threshold, "supplied_by": supplied, "origin": origin,
        "override_reason": prov.get("override_reason"), "cells_checked": len(checkable),
        "offending": 0, "zero_cells": "not flagged: a zero is not disclosive",
    }
    if len(checkable) != len(cells):
        info["implied_counts"] = "implied counts not checkable: group size unknown"
    if threshold is None:
        info["note"] = f"not applicable for origin {origin}"
        details["min_cell"] = info
        return
    offending = [c for c in checkable if 0 < c[3] < threshold]
    if offending:
        lines = [f"{g} | {t} | {cat} | {v:g} | {kind}" for g, t, cat, v, kind in offending]
        raise DisclosureRefusal(
            f"targets.conditional.provenance: {len(offending)} cell(s) are below the minimum "
            f"cell size {threshold} (origin {origin}, threshold from {supplied}). "
            "Cells (group | target | category | value | counted|implied):\n  "
            + "\n  ".join(lines)
            + "\nNothing was generated."
        )
    details["min_cell"] = info


# --------------------------------------------------------------------------- #
# Finalize
# --------------------------------------------------------------------------- #

def finalize(ctx: Any, result: Any) -> Any:
    """Write the conditional columns on ``result.data``, derive, then apply constraints."""
    plan: Plan = ctx.conditional
    df = result.data
    n = len(df)
    seed = ctx.config.get("seed")
    ss = (
        np.random.SeedSequence([int(seed) % (2 ** 63), RULE_ORDER]) if seed is not None
        else np.random.SeedSequence()
    )
    rng = np.random.default_rng(ss)

    gidx = rng.choice(len(plan.groups), size=n, p=plan.group_p)
    group_col = np.asarray(plan.groups, dtype=object)[gidx]
    df[plan.group_var] = group_col
    for t in plan.targets:
        out = np.empty(n, dtype=object)
        cats = np.asarray(t.cats, dtype=object)
        for gi, g in enumerate(plan.groups):
            rows = np.flatnonzero(gidx == gi)
            if rows.size:
                out[rows] = cats[rng.choice(len(cats), size=rows.size, p=t.p[g])]
        df[t.variable] = out

    def fill(var: str, source: np.ndarray, table: Mapping[str, Tuple[List[str], np.ndarray]]):
        out = np.empty(n, dtype=object)
        for key, (labels, probs) in table.items():
            rows = np.flatnonzero(source == key)
            if not rows.size:
                continue
            if len(labels) == 1:
                out[rows] = labels[0]
            else:
                out[rows] = np.asarray(labels, dtype=object)[
                    rng.choice(len(labels), size=rows.size, p=probs)
                ]
        df[var] = out

    if plan.anchor is not None:
        anchor_col = df[plan.anchor].to_numpy(dtype=object)
        for var, table in plan.age_derivations.items():
            fill(var, anchor_col, table)
    for var, table in plan.hierarchy.items():
        fill(var, group_col, table)

    if ctx.ruleset is not None:
        df, repairs = ctx.ruleset.apply(df, rng)
        result.repairs = repairs
    result.data = df
    _write_tables(ctx, plan, df)
    plan.details["achieved"] = verification_summary(ctx.extra_tables)
    return result


def _write_tables(ctx: Any, plan: Plan, df: pd.DataFrame) -> None:
    counts = df[plan.group_var].value_counts()
    n = len(df)
    mix_rows = []
    for g, target in zip(plan.groups, plan.group_p):
        got = float(counts.get(g, 0)) / n
        se = math.sqrt(target * (1 - target) / n)
        mix_rows.append({
            "group": g, "target_share": float(target), "achieved_share": got,
            "abs_diff": abs(got - target), "n_generated": int(counts.get(g, 0)),
            "expected_se": se, "z": _z(got - target, se),
        })
    ctx.extra_tables[MIX_FILE] = pd.DataFrame(mix_rows)

    rows = []
    for g in plan.groups:
        sub = df[df[plan.group_var] == g]
        n_g = len(sub)
        for t in plan.targets:
            reported = sub[t.variable].map(t.report_of) if t.is_age else sub[t.variable]
            got = reported.value_counts()
            target = {c: 0.0 for c in t.report_cats}
            for cat, pr in zip(t.cats, t.p[g]):
                target[t.report_of[cat]] += float(pr)
            for c in t.report_cats:
                tp = target[c]
                gp = float(got.get(c, 0)) / n_g if n_g else 0.0
                se = math.sqrt(tp * (1 - tp) / n_g) if n_g else 0.0
                rows.append({
                    "group": g, "target": t.variable, "category": c, "target_p": tp,
                    "generated_p": gp, "abs_diff": abs(gp - tp), "expected_se": se,
                    "z": _z(gp - tp, se),
                })
    ctx.extra_tables[VERIFY_FILE] = pd.DataFrame(rows)


def _z(diff: float, se: float) -> float:
    if se > 0:
        return float(diff / se)
    return 0.0 if abs(diff) < 1e-12 else float("inf")


def verification_summary(tables: Any) -> Dict[str, Any]:
    """Worst differences between targets and generated records, against the sampling noise.

    ``tables`` is ``Context.extra_tables`` (or the targets-vs-generated frame itself).
    ``expected_max_noise`` is the largest ``expected_se * sqrt(2 ln K)`` over the K cells:
    the size of the biggest difference chance alone produces among K cells.
    """
    frame = tables[VERIFY_FILE] if isinstance(tables, Mapping) else tables

    def block(f: pd.DataFrame) -> Dict[str, Any]:
        if f.empty:
            return {"cells": 0, "max_abs_diff": 0.0, "max_z": 0.0, "expected_max_noise": 0.0}
        k = len(f)
        factor = math.sqrt(2 * math.log(max(k, 2)))
        return {
            "cells": int(k),
            "max_abs_diff": float(f["abs_diff"].max()),
            "max_z": float(f["z"].abs().max()),
            "expected_max_noise": float(f["expected_se"].max() * factor),
        }

    out = block(frame)
    out["per_target"] = {str(t): block(sub) for t, sub in frame.groupby("target", sort=False)}
    if isinstance(tables, Mapping) and MIX_FILE in tables:
        mix = tables[MIX_FILE]
        out["group_mix"] = {
            "max_abs_diff": float(mix["abs_diff"].max()), "max_z": float(mix["z"].abs().max()),
        }
    return out
