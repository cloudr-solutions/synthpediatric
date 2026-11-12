"""Rule registry and fidelity profiles.

Every pipeline step is a *named rule* with a parameter schema (``normalize``) and an
``apply`` function. A config composes rules; a *profile* decides which rules are on
by default; ``rules:`` toggles override the profile one rule at a time.

Execution order (fixed, ascending ``order``; a rule runs at most once)::

    10 marginals    dictionary   inline 1-way target marginals
    20 overrides    dictionary   authoritative marginals loaded from files
    30 cohort       dictionary   restrict categories to a sub-population
    40 oversample   dictionary   reweight categories (rare-cancer boost)
    50 joints       generate     calibrate a cross-tab to the marginals (IPF) and sample it
    60 constraints  generate     hard consistency repairs on the sampled records
    -- sampling happens here (joint backbone if `joints` ran, else independent marginals) --
    80 survival     post         time/event columns by group

Precedence follows from the order: a later rule sees the output of earlier ones. So
``overrides`` beat ``marginals`` for the same variable, ``cohort`` restricts the final
marginals, ``oversample`` reweights within the cohort, ``joints`` calibrates to the
final marginals, and ``constraints`` (hard) repair whatever the sampling produced.
Multi-item rules (``cohort.filters``, ``oversample`` as a list) apply their items in
the listed order. Order is not configurable; the toggles and profiles are.

Validation against the data: the parameter schemas above only check shape. Names and
labels are checked when a rule runs, against the dictionary as it is at that point, and
always before any record is sampled (``survival``, which runs after sampling, has a
``preflight`` check for this). Marginals, overrides and cross-tab labels are checked
against the dictionary as loaded, because a table replaces a variable's whole
distribution. ``Context.strict`` (config ``strict:``) decides whether a bad reference is a
``ConfigError`` or a warning in the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

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
    read_structured,
    unknown_message,
)
from .dictionary import DataDictionary

# --------------------------------------------------------------------------- #
# Profiles: the "how many rules" dial. Edit this table to change a bundle.
# --------------------------------------------------------------------------- #

PROFILES: Dict[str, Tuple[str, ...]] = {
    "marginals_only": ("marginals", "overrides", "cohort"),
    "standard": ("marginals", "overrides", "cohort", "joints", "constraints"),
    "full": ("marginals", "overrides", "cohort", "joints", "constraints", "oversample", "survival"),
}
# No `profile:` given -> every configured rule runs (what recipes meant before profiles).
DEFAULT_PROFILE = "full"

STAGES = ("dictionary", "generate", "post")


@dataclass
class Context:
    """Mutable state handed from rule to rule during a run."""

    config: Dict[str, Any]
    dictionary: DataDictionary
    joint: Any = None
    ruleset: Any = None
    df: Optional[pd.DataFrame] = None
    warnings: List[str] = field(default_factory=list)
    input_files: Dict[str, str] = field(default_factory=dict)
    oversampling: List[Dict[str, Any]] = field(default_factory=list)
    # strict: a reference to a variable / category / group / column that does not exist is
    # an error. Not strict: it is a warning (recorded in the manifest) and the run goes on.
    strict: bool = True
    # The dictionary as loaded, before any rule ran. Marginals, overrides and cross-tab
    # labels are checked against it: a table replaces a variable's whole distribution, so
    # it may legitimately name categories an earlier rule dropped.
    base_dictionary: Optional[DataDictionary] = None

    def __post_init__(self) -> None:
        if self.base_dictionary is None:
            self.base_dictionary = self.dictionary


@dataclass(frozen=True)
class Rule:
    name: str
    order: int
    stage: str
    config_key: str  # where the params live in the config, for messages
    summary: str
    normalize: Callable[[str, Any], Any]
    apply: Callable[[Context, Any], Dict[str, Any]]
    # Optional check that needs the final dictionary but must run before sampling.
    preflight: Optional[Callable[[Context, Any], None]] = None


# --------------------------------------------------------------------------- #
# Parameter schemas
# --------------------------------------------------------------------------- #

def _norm_tables(where: str, value: Any) -> Dict[str, Dict[str, float]]:
    if not isinstance(value, Mapping) or not value:
        raise ConfigError(
            f"{where}: expected a non-empty mapping of variable -> {{value: frequency}}"
        )
    out: Dict[str, Dict[str, float]] = {}
    for var, table in value.items():
        w = f"{where}.{var}"
        if not isinstance(table, Mapping) or not table:
            raise ConfigError(f"{w}: expected a non-empty mapping of value -> frequency")
        clean = {
            str(as_label(f"{w} key", k)): as_number(f"{w}[{k!r}]", v, nonneg=True)
            for k, v in table.items()
        }
        if sum(clean.values()) <= 0:
            raise ConfigError(f"{w}: frequencies sum to zero")
        out[str(var)] = clean
    return out


def _norm_marginals(where: str, value: Any) -> Dict[str, Dict[str, float]]:
    return _norm_tables(where, value)


def _norm_overrides(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, ("tables",), required=("tables",))
    return {"tables": as_str(f"{where}.tables", value["tables"])}


def _norm_cohort(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, ("name", "filters"), required=("filters",))
    filters = value["filters"]
    if not isinstance(filters, list) or not filters:
        raise ConfigError(f"{where}.filters: expected a non-empty list of filters")
    out_filters = []
    for i, flt in enumerate(filters):
        w = f"{where}.filters[{i}]"
        check_keys(w, flt, ("variable", "op", "values", "threshold"), required=("variable", "op"))
        op = check_choice(f"{w}.op", str(flt["op"]).lower(), ("equals", "min", "max"))
        item: Dict[str, Any] = {"variable": as_str(f"{w}.variable", flt["variable"]), "op": op}
        if op == "equals":
            vals = flt.get("values")
            if not isinstance(vals, list) or not vals:
                raise ConfigError(f"{w}.values: 'equals' requires a non-empty list of values")
            item["values"] = [as_label(f"{w}.values", v) for v in vals]
        else:
            if "threshold" not in flt:
                raise ConfigError(f"{w}: '{op}' requires a 'threshold'")
            item["threshold"] = as_number(f"{w}.threshold", flt["threshold"])
        out_filters.append(item)
    out: Dict[str, Any] = {"filters": out_filters}
    if value.get("name") is not None:
        out["name"] = as_str(f"{where}.name", value["name"])
    return out


def _norm_oversample(where: str, value: Any) -> List[Dict[str, Any]]:
    items = value if isinstance(value, list) else [value]
    if not items:
        raise ConfigError(f"{where}: expected a mapping or a non-empty list of mappings")
    out = []
    for i, item in enumerate(items):
        w = f"{where}[{i}]" if isinstance(value, list) else where
        check_keys(w, item, ("variable", "values", "factor"), required=("variable", "values"))
        vals = item["values"]
        if not isinstance(vals, list) or not vals:
            raise ConfigError(f"{w}.values: expected a non-empty list of category values")
        out.append({
            "variable": as_str(f"{w}.variable", item["variable"]),
            "values": [as_label(f"{w}.values", v) for v in vals],
            "factor": as_number(f"{w}.factor", item.get("factor", 10.0), positive=True),
        })
    return out


def _norm_joints(where: str, value: Any) -> Dict[str, Any]:
    check_keys(
        where, value, ("cliques", "crosstabs", "smoothing", "max_iter", "tol"),
        required=("cliques", "crosstabs"),
    )
    cliques = value["cliques"]
    if not isinstance(cliques, list) or not cliques:
        raise ConfigError(f"{where}.cliques: expected a list of variable lists, e.g. [[sex, age]]")
    if len(cliques) != 1:
        raise ConfigError(
            f"{where}.cliques: this version calibrates exactly one clique (a single joint "
            f"backbone); got {len(cliques)}. Merge them into one list of variables"
        )
    clique = cliques[0]
    if not isinstance(clique, list) or len(clique) < 2:
        raise ConfigError(f"{where}.cliques[0]: expected a list of at least 2 variable names")
    return {
        "cliques": [[as_str(f"{where}.cliques[0]", v) for v in clique]],
        "crosstabs": as_str(f"{where}.crosstabs", value["crosstabs"]),
        "smoothing": as_number(f"{where}.smoothing", value.get("smoothing", 0.0), nonneg=True),
        "max_iter": as_int(f"{where}.max_iter", value.get("max_iter", 100), 1),
        "tol": as_number(f"{where}.tol", value.get("tol", 1e-8), positive=True),
    }


def _norm_constraints(where: str, value: Any) -> Dict[str, Any]:
    from .constraints import _CONSTRAINT_TYPES

    check_keys(where, value, ("file", "rules", "max_iterations"))
    if ("file" in value) == ("rules" in value):
        raise ConfigError(
            f"{where}: give exactly one of 'file' (a rules JSON/YAML) or 'rules' (inline list)"
        )
    if "file" in value:
        if "max_iterations" in value:
            raise ConfigError(
                f"{where}.max_iterations: only valid with inline 'rules' (a file sets its own)"
            )
        return {"file": as_str(f"{where}.file", value["file"])}
    inline = value["rules"]
    if not isinstance(inline, list) or not inline:
        raise ConfigError(f"{where}.rules: expected a non-empty list of constraints")
    for i, entry in enumerate(inline):
        if not isinstance(entry, Mapping):
            raise ConfigError(f"{where}.rules[{i}]: expected a mapping")
        ctype = entry.get("type", "allowed_values")
        if ctype not in _CONSTRAINT_TYPES:
            raise ConfigError(
                f"{where}.rules[{i}].type: unknown constraint type {ctype!r}. "
                f"Valid types: {fmt_choices(_CONSTRAINT_TYPES)}"
            )
    return {
        "rules": [dict(e) for e in inline],
        "max_iterations": as_int(f"{where}.max_iterations", value.get("max_iterations", 10), 1),
    }


def _norm_survival(where: str, value: Any) -> Dict[str, Any]:
    check_keys(
        where, value, ("group_col", "specs", "horizon_months", "time_col", "event_col"),
        required=("group_col", "specs"),
    )
    specs = value["specs"]
    if isinstance(specs, Mapping):
        specs = {str(as_label(f"{where}.specs key", k)): v for k, v in specs.items()}
    elif isinstance(specs, str) and specs:
        pass  # path to a JSON/YAML file, read when the rule runs
    else:
        raise ConfigError(f"{where}.specs: expected a mapping of group -> spec, or a file path")
    return {
        "group_col": as_str(f"{where}.group_col", value["group_col"]),
        "specs": specs,
        "horizon_months": as_number(
            f"{where}.horizon_months", value.get("horizon_months", 120), positive=True
        ),
        "time_col": as_str(f"{where}.time_col", value.get("time_col", "months")),
        "event_col": as_str(f"{where}.event_col", value.get("event_col", "event")),
    }


# --------------------------------------------------------------------------- #
# Rule implementations
# --------------------------------------------------------------------------- #

def _read_file(ctx: Context, where: str, path: str) -> Any:
    ctx.input_files[path] = file_sha256(path) if Path(path).is_file() else ""
    try:
        return read_structured(path)
    except ConfigError as exc:
        raise ConfigError(f"{where}: {exc}") from exc


def _flag(ctx: Context, message: str, action: str) -> None:
    """Strict: raise a config error. Otherwise record a warning and let the run go on."""
    if ctx.strict:
        raise ConfigError(message)
    ctx.warnings.append(f"{message} (strict: false, {action})")


def _cats(vm: Any) -> List[str]:
    return [str(c) for c in vm.categories]


def _category_message(
    where: str, value: object, now: List[str], base: List[str], note: str = ""
) -> str:
    """Unknown category; says so when it exists in the loaded dictionary but an earlier rule
    (marginals, overrides, cohort) removed it."""
    if str(value) in base and str(value) not in now:
        return (
            f"{where}: category '{value}'{note} exists in the dictionary but an earlier rule "
            f"(marginals, overrides or cohort) removed it. Valid categories at this point: "
            f"{fmt_valid(now)}"
        )
    return unknown_message(where, "category", value, now, note)


def _check_tables(
    ctx: Context, root: str, tables: Mapping[str, Mapping[str, float]], note: str = ""
) -> None:
    """Variables and category labels of target tables must exist in the loaded dictionary."""
    base = ctx.base_dictionary.variables
    for var, table in tables.items():
        if var not in base:
            _flag(
                ctx, unknown_message(root, "variable", var, base, note),
                "variable added as a new column",
            )
            continue
        cats = _cats(base[var])
        for label in table:
            if label not in cats:
                _flag(
                    ctx, unknown_message(f"{root}.{var}", "category", label, cats, note),
                    "category kept as written",
                )


def _apply_marginals(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    from .inputs import override_marginals

    _check_tables(ctx, "targets.marginals", p)
    ctx.dictionary = override_marginals(ctx.dictionary, p)
    return {"variables": list(p)}


def _apply_overrides(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    from .inputs import override_marginals

    where = "targets.overrides.tables"
    root = Path(p["tables"])
    if root.is_dir():
        files = sorted(f for f in root.iterdir() if f.suffix.lower() in (".json", ".yaml", ".yml"))
        if not files:
            raise ConfigError(f"{where}: directory {root} has no .json/.yaml/.yml files")
    elif root.is_file():
        files = [root]
    else:
        raise ConfigError(f"{where}: path not found: {root}")
    tables: Dict[str, Dict[str, float]] = {}
    for f in files:
        one = _norm_tables(f"{where} ({f.name})", _read_file(ctx, where, str(f)))
        _check_tables(ctx, "targets.overrides", one, note=f" (in {f.name})")
        tables.update(one)
    ctx.dictionary = override_marginals(ctx.dictionary, tables)
    return {"variables": list(tables), "files": [str(f) for f in files]}


def _apply_cohort(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    from .inputs import CohortFilter, _filter_variable, apply_cohort, cohort_from_dict

    # Filters apply in order, so each one is checked against the categories its
    # predecessors left (a value an earlier filter removed is reported as such).
    state = dict(ctx.dictionary.variables)
    kept: List[Dict[str, Any]] = []
    for i, flt in enumerate(p["filters"]):
        where = f"cohort.filters[{i}]"
        var = flt["variable"]
        if var not in state:
            _flag(
                ctx, unknown_message(f"{where}.variable", "variable", var, state),
                "filter skipped",
            )
            continue
        flt = dict(flt)
        now = _cats(state[var])
        if flt["op"] == "equals":
            base_vm = ctx.base_dictionary.variables.get(var)
            base = _cats(base_vm) if base_vm is not None else []
            matched = []
            for value in flt["values"]:
                if str(value) in now:
                    matched.append(value)
                else:
                    _flag(
                        ctx, _category_message(f"{where}.values", value, now, base),
                        "value ignored",
                    )
            if not matched:
                raise ConfigError(
                    f"{where}.values: no value matches a category of '{var}', so the filter "
                    f"would remove every record. Valid categories: {fmt_valid(now)}"
                )
            flt["values"] = matched
        try:
            state[var] = _filter_variable(state[var], CohortFilter(
                variable=var, op=flt["op"], values=flt.get("values"),
                threshold=flt.get("threshold"),
            ))
        except ValueError as exc:
            raise ConfigError(
                f"{where}: {exc}. Categories at this point: {fmt_valid(now)}"
            ) from exc
        kept.append(flt)
    if kept:
        spec = {"filters": kept, "name": p.get("name", "cohort")}
        ctx.dictionary = apply_cohort(ctx.dictionary, cohort_from_dict(spec))
    return {"filters": len(kept)}


def _apply_oversample(ctx: Context, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    from .resample import oversample_with_report

    for i, item in enumerate(items):
        where = "oversample" if len(items) == 1 else f"oversample[{i}]"
        if item["variable"] not in ctx.dictionary.variables:
            raise ConfigError(
                unknown_message(
                    f"{where}.variable", "variable", item["variable"], ctx.dictionary.variables
                )
            )
        if ctx.strict:  # not strict: the report below keeps today's `unmatched_values` warning
            now = _cats(ctx.dictionary.variables[item["variable"]])
            base_vm = ctx.base_dictionary.variables.get(item["variable"])
            base = _cats(base_vm) if base_vm is not None else []
            for value in item["values"]:
                if str(value) not in now:
                    raise ConfigError(_category_message(f"{where}.values", value, now, base))
        ctx.dictionary, report = oversample_with_report(
            ctx.dictionary, item["variable"], item["values"], item["factor"]
        )
        ctx.oversampling.append(report)
        if report["unmatched_values"]:
            ctx.warnings.append(
                f"oversample: values not found in '{item['variable']}' (no factor applied): "
                f"{report['unmatched_values']}"
            )
    return {"variables": [i["variable"] for i in items]}


def _apply_joints(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    from .calibrate import JointDistribution, raking_ipf, targets_from_dictionary

    where = "targets.joints"
    clique = p["cliques"][0]
    for var in clique:
        if var not in ctx.dictionary.variables:
            raise ConfigError(
                unknown_message(f"{where}.cliques[0]", "variable", var, ctx.dictionary.variables)
            )
    path = p["crosstabs"]
    if not Path(path).is_file():
        raise ConfigError(f"{where}.crosstabs: file not found: {path}")
    ctx.input_files[path] = file_sha256(path)
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    needed = clique + ["count"]
    lacking = [c for c in needed if c not in table.columns]
    if lacking:
        raise ConfigError(
            f"{where}.crosstabs: {path} lacks column(s) {lacking}; "
            f"expected columns: {fmt_choices(needed)}"
        )
    # Labels are checked against the loaded dictionary: a category an earlier rule (cohort)
    # removed may stay in the cross-tab, the calibration drops its cells. A label that no
    # category matches would also be dropped, silently, together with its mass.
    for var in clique:
        cats = _cats(ctx.base_dictionary.variables.get(var, ctx.dictionary.variables[var]))
        for label in sorted(set(table[var]) - set(cats)):
            _flag(
                ctx,
                unknown_message(
                    f"{where}.crosstabs.{var}", "category", label, cats, f" (in {path})"
                ),
                "cells with this label get no mass",
            )
    counts: Dict[tuple, float] = {}
    for row in table[needed].itertuples(index=False):
        try:
            value = float(row[-1])
        except ValueError as exc:
            raise ConfigError(
                f"{where}.crosstabs: non-numeric count {row[-1]!r} in {path}"
            ) from exc
        key = tuple(row[:-1])
        counts[key] = counts.get(key, 0.0) + value
    joint = JointDistribution.from_counts(counts, clique)
    cal = raking_ipf(
        joint, targets_from_dictionary(ctx.dictionary, clique),
        max_iter=p["max_iter"], tol=p["tol"], smoothing=p["smoothing"],
    )
    ctx.joint = cal.joint
    if not cal.converged:
        ctx.warnings.append(f"joints: IPF did not converge (max deviation {cal.max_deviation:.2e})")
    return {
        "clique": clique, "crosstabs": path, "iterations": cal.iterations,
        "max_deviation": float(cal.max_deviation), "converged": bool(cal.converged),
        "calibration_warnings": list(cal.warnings),
    }


def _apply_constraints(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    from .constraints import RuleSet

    if "file" in p:
        where = "constraints.file"
        spec = _read_file(ctx, where, p["file"])
        if not isinstance(spec, Mapping):
            raise ConfigError(
                f"constraints.file: {p['file']} must hold a mapping with a 'constraints' list"
            )
        source = p["file"]
    else:
        where = "constraints.rules"
        spec = {"constraints": p["rules"], "max_iterations": p["max_iterations"]}
        source = "inline"
    try:
        ruleset = RuleSet.from_dict(spec)
    except (KeyError, TypeError, ValueError) as exc:  # missing field, unknown type, ...
        raise ConfigError(f"{where}: invalid constraint ({type(exc).__name__}: {exc})") from exc

    # Constraints run on the sampled records, whose columns are the dictionary's variables.
    columns = ctx.dictionary.variables
    usable = []
    for i, constraint in enumerate(ruleset.constraints):
        for field_name, column in constraint.column_refs().items():
            if column not in columns:
                note = f" in constraint '{constraint.name}'"
                if source != "inline":
                    note += f" of {source}"
                _flag(
                    ctx,
                    unknown_message(f"{where}[{i}].{field_name}", "column", column, columns, note),
                    "constraint skipped",
                )
                break
        else:
            usable.append(constraint)
    ruleset.constraints = usable
    ctx.ruleset = ruleset
    return {"source": source, "n_constraints": len(ruleset.constraints)}


DEFAULT_GROUP = "__default__"  # survival specs key: the spec for groups that are not listed


def _survival_specs(ctx: Context, p: Dict[str, Any]) -> Dict[Any, Any]:
    specs = p["specs"]
    if isinstance(specs, str):
        specs = _read_file(ctx, "targets.survival.specs", specs)
        if not isinstance(specs, Mapping):
            raise ConfigError(
                "targets.survival.specs: the file must hold a mapping of group -> spec"
            )
    return dict(specs)


def _preflight_survival(ctx: Context, p: Dict[str, Any]) -> None:
    """Check the survival section against the dictionary before any record is sampled."""
    from .survival_gen import _make_sampler

    where = "targets.survival"
    variables = ctx.dictionary.variables
    if p["group_col"] not in variables:
        raise ConfigError(
            unknown_message(f"{where}.group_col", "column", p["group_col"], variables)
        )
    # A spec may name a group the cohort removed (the same specs serve several cohorts), so
    # a group is known if the loaded dictionary or the final one has it.
    groups = _cats(variables[p["group_col"]])
    base_vm = ctx.base_dictionary.variables.get(p["group_col"])
    if base_vm is not None:
        groups += [g for g in _cats(base_vm) if g not in groups]
    for group, spec in _survival_specs(ctx, p).items():
        try:
            _make_sampler(spec, np.random.default_rng(0))
        except (TypeError, ValueError, KeyError) as exc:
            raise ConfigError(
                f"{where}.specs.{group}: invalid survival spec {spec!r} ({exc}). "
                "Use a number (5-year survival), {s5: ...}, {median_months: ...} or {points: ...}"
            ) from exc
        if group != DEFAULT_GROUP and str(group) not in groups:
            _flag(
                ctx, unknown_message(f"{where}.specs", "group", group, groups),
                "group ignored",
            )


def _apply_survival(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    from .survival_gen import sample_survival

    df = ctx.df
    specs = _survival_specs(ctx, p)
    kwargs = {}
    if DEFAULT_GROUP in specs:  # fallback for unlisted groups (else the built-in 0.80)
        kwargs["default_spec"] = specs.pop(DEFAULT_GROUP)
    months, event = sample_survival(
        df[p["group_col"]].to_numpy(), specs, rng=ctx.config["seed"],
        horizon_months=p["horizon_months"], **kwargs,
    )
    df[p["time_col"]] = months
    df[p["event_col"]] = event
    return {"group_col": p["group_col"], "columns": [p["time_col"], p["event_col"]]}


RULES: Dict[str, Rule] = {
    r.name: r
    for r in (
        Rule("marginals", 10, "dictionary", "targets.marginals",
             "inline 1-way target marginals", _norm_marginals, _apply_marginals),
        Rule("overrides", 20, "dictionary", "targets.overrides",
             "authoritative marginals loaded from files", _norm_overrides, _apply_overrides),
        Rule("cohort", 30, "dictionary", "cohort",
             "restrict categories to a sub-population", _norm_cohort, _apply_cohort),
        Rule("oversample", 40, "dictionary", "oversample",
             "reweight categories (e.g. rare cancers)", _norm_oversample, _apply_oversample),
        Rule("joints", 50, "generate", "targets.joints",
             "calibrate a cross-tab to the marginals (IPF) and sample it",
             _norm_joints, _apply_joints),
        Rule("constraints", 60, "generate", "constraints",
             "hard consistency repairs", _norm_constraints, _apply_constraints),
        Rule("survival", 80, "post", "targets.survival",
             "time/event columns by group", _norm_survival, _apply_survival,
             _preflight_survival),
    )
}


# --------------------------------------------------------------------------- #
# Config <-> rules
# --------------------------------------------------------------------------- #

def normalize_rules(
    profile: Optional[str], toggles: Any, sections: Mapping[str, Any]
) -> Tuple[str, Dict[str, bool], Dict[str, Any]]:
    """Validate profile, toggles and per-rule params. Returns the canonical triple."""
    profile = check_choice(
        "profile", DEFAULT_PROFILE if profile is None else profile, tuple(PROFILES)
    )
    if not isinstance(toggles, Mapping):
        raise ConfigError(f"rules: expected a mapping of rule name -> true/false, got {toggles!r}")
    clean_toggles: Dict[str, bool] = {}
    for name, flag in toggles.items():
        if name not in RULES:
            raise ConfigError(f"rules: unknown rule '{name}'. Valid rules: {fmt_choices(RULES)}")
        if not isinstance(flag, bool):
            raise ConfigError(f"rules.{name}: expected true or false, got {flag!r}")
        clean_toggles[name] = flag
    params = {
        name: RULES[name].normalize(RULES[name].config_key, value)
        for name, value in sections.items()
    }
    return profile, clean_toggles, params


def section_params(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """Pull each rule's params out of a canonical config."""
    found: Dict[str, Any] = dict(cfg.get("targets", {}))
    for key in ("cohort", "oversample", "constraints"):
        if key in cfg:
            found[key] = cfg[key]
    return found


def resolve_rules(cfg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Expand profile + toggles + params into the ordered, explicit rule list.

    Each entry: name, order, stage, enabled (will run), status
    (applied | skipped | disabled), reason, params.
    """
    profile = cfg["profile"]
    toggles = cfg.get("rules", {})
    params = section_params(cfg)
    resolved = []
    for rule in sorted(RULES.values(), key=lambda r: r.order):
        in_profile = rule.name in PROFILES[profile]
        enabled = toggles.get(rule.name, in_profile)
        has_params = rule.name in params
        if rule.name in toggles:
            note = f"profile '{profile}' {'includes' if in_profile else 'excludes'} it"
            why_on = f"switched on in rules: ({note})"
            why_off = f"switched off in rules: ({note})"
        else:
            why_on = f"in profile '{profile}'"
            why_off = f"not in profile '{profile}'"
        if enabled and has_params:
            status, reason = "applied", why_on
        elif enabled:
            if rule.name in toggles:
                raise ConfigError(
                    f"rules.{rule.name}: switched on but no parameters given; "
                    f"add a '{rule.config_key}' section"
                )
            status, reason = "skipped", f"{why_on}, but no '{rule.config_key}' section configured"
        else:
            status, reason = "disabled", why_off
        resolved.append({
            "name": rule.name, "order": rule.order, "stage": rule.stage,
            "enabled": status == "applied", "status": status, "reason": reason,
            "params": params.get(rule.name),
        })
    return resolved


def run_stage(ctx: Context, resolved: List[Dict[str, Any]], stage: str) -> None:
    """Apply every enabled rule of ``stage`` in order, recording details on its entry."""
    for entry in resolved:
        if entry["stage"] == stage and entry["enabled"]:
            entry["details"] = RULES[entry["name"]].apply(ctx, entry["params"]) or {}


def run_preflight(ctx: Context, resolved: List[Dict[str, Any]]) -> None:
    """Check every enabled rule that runs after sampling (``post`` stage) while no record
    exists yet, so a mistake in it stops the run before generation, not after."""
    for entry in resolved:
        rule = RULES[entry["name"]]
        if entry["enabled"] and rule.preflight is not None:
            rule.preflight(ctx, entry["params"])


def rule_catalog() -> List[Dict[str, Any]]:
    """Rule names, order, stage, config key, profiles containing it (for docs/CLI)."""
    return [
        {
            "name": r.name, "order": r.order, "stage": r.stage, "config_key": r.config_key,
            "summary": r.summary, "profiles": [p for p, rs in PROFILES.items() if r.name in rs],
        }
        for r in sorted(RULES.values(), key=lambda r: r.order)
    ]


__all__ = [
    "PROFILES", "DEFAULT_PROFILE", "RULES", "Context", "Rule", "normalize_rules",
    "resolve_rules", "run_stage", "run_preflight", "rule_catalog",
]
