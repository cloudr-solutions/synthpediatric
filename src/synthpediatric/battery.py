"""DRAFT clinical consistency battery: load the rules file and run the output checks.

The battery file (see ``examples/battery/ctc_battery_draft.json``) is the single source for
both halves of each item. Its ``constraints`` list is an ordinary rule file for
:class:`~synthpediatric.constraints.RuleSet` (generation repairs the violations). The checks
here are computed from the very same constraint objects, so a rule and its check cannot
drift apart. Its ``checks`` list holds probabilistic statements, which are compared as
distributions and never pass or fail. Its ``roadmap`` list names items the single CTC table
cannot express.

Every item is DRAFT until the Input team verifies it against SEER*Stat and NCCR treatment
data and clinicians accept it. The ``status`` key carries that state, and each row of the
report repeats it.

Counts in the report may leave CGC, so any count between 1 and ``min_cell - 1`` is
suppressed (default 16) and every value derived from a suppressed count is blanked too.
A count of 0 is shown.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .constraints import AllowedValuesConstraint, Constraint, RuleSet

DEFAULT_MIN_CELL = 16
STATUSES = ("draft", "verified", "rejected")
FAMILIES = (
    "sex_restricted_sites",
    "age_implausible_diagnoses",
    "diagnosis_treatment_coherence",
    "stage_risk_outcome_monotonicity",
    "temporal_ordering",
    "era_effects",
    "utilization_shape",
    "late_effects",
)
CHECK_KINDS = ("distribution", "survival_5y", "stage_monotone", "age_outlier")
REPORT_COLUMNS = [
    "id", "name", "family", "status", "kind", "metric", "n_eligible", "n_flagged",
    "n_reference", "cohort_value", "reference_value", "reference_source", "difference",
    "tvd", "result", "note",
]

_COMMON_KEYS = ("id", "family", "status", "source_statement", "description")


class BatteryError(ValueError):
    """The battery file is malformed."""


@dataclass
class Battery:
    """A loaded battery file: hard rules, probabilistic checks and roadmap items."""

    path: Optional[str]
    meta: Dict[str, Any]
    constraints: List[Constraint]
    constraint_meta: Dict[str, Dict[str, Any]]
    checks: List[Dict[str, Any]]
    roadmap: List[Dict[str, Any]]
    max_iterations: int = 10

    def ruleset(self, statuses: Optional[Sequence[str]] = None) -> RuleSet:
        """The generation rules, optionally only those whose status is in ``statuses``."""
        keep = [
            c for c in self.constraints
            if statuses is None or self.constraint_meta[c.name]["status"] in statuses
        ]
        return RuleSet(constraints=keep, max_iterations=self.max_iterations)

    def ids(self) -> List[str]:
        """Every statement id in the file, in file order."""
        return (
            [self.constraint_meta[c.name]["id"] for c in self.constraints]
            + [c["id"] for c in self.checks]
            + [r["id"] for r in self.roadmap]
        )


def _require(entry: Mapping[str, Any], keys: Sequence[str], where: str) -> None:
    missing = [k for k in keys if not entry.get(k)]
    if missing:
        raise BatteryError(f"{where}: missing {', '.join(missing)}")
    if "family" in keys and entry["family"] not in FAMILIES:
        raise BatteryError(f"{where}: unknown family {entry['family']!r}")
    if "status" in keys and entry["status"] not in STATUSES:
        raise BatteryError(f"{where}: status must be one of {', '.join(STATUSES)}")


def load_battery(path: Union[str, Path]) -> Battery:
    """Load and validate a battery file."""
    with Path(path).open("r", encoding="utf-8") as fh:
        spec = json.load(fh)
    return battery_from_dict(spec, path=str(path))


def battery_from_dict(spec: Mapping[str, Any], path: Optional[str] = None) -> Battery:
    ruleset = RuleSet.from_dict(spec)
    meta: Dict[str, Dict[str, Any]] = {}
    for i, entry in enumerate(spec.get("constraints", [])):
        where = f"constraints[{i}]"
        _require(entry, _COMMON_KEYS + ("name",), where)
        meta[entry["name"]] = {k: entry[k] for k in _COMMON_KEYS + ("name",)}
    checks = [dict(c) for c in spec.get("checks", [])]
    for i, c in enumerate(checks):
        where = f"checks[{i}]"
        _require(c, _COMMON_KEYS + ("name", "kind", "generation"), where)
        if c["kind"] not in CHECK_KINDS:
            raise BatteryError(f"{where}: unknown kind {c['kind']!r}")
    roadmap = [dict(r) for r in spec.get("roadmap", [])]
    for i, r in enumerate(roadmap):
        _require(r, ("id", "family", "statement", "reason", "needs"), f"roadmap[{i}]")
        if r["family"] not in FAMILIES:
            raise BatteryError(f"roadmap[{i}]: unknown family {r['family']!r}")
    battery = Battery(
        path=path,
        meta={k: v for k, v in spec.items() if k not in ("constraints", "checks", "roadmap")},
        constraints=ruleset.constraints,
        constraint_meta=meta,
        checks=checks,
        roadmap=roadmap,
        max_iterations=ruleset.max_iterations,
    )
    ids = battery.ids()
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise BatteryError(f"duplicate ids: {', '.join(dupes)}")
    return battery


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _suppress(n: float, min_cell: int) -> float:
    """Blank a count between 1 and ``min_cell - 1``."""
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return np.nan
    return np.nan if 0 < n < min_cell else float(n)


def _hidden(n: float, min_cell: int) -> bool:
    return bool(np.isnan(_suppress(n, min_cell)))


def _tvd(p: Mapping[Any, float], q: Mapping[Any, float]) -> float:
    keys = set(p) | set(q)
    return 0.5 * float(sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys))


def _shares(counts: Mapping[Any, float]) -> Dict[Any, float]:
    total = float(sum(counts.values()))
    return {k: v / total for k, v in counts.items()} if total > 0 else {}


def kaplan_meier(time: np.ndarray, event: np.ndarray, horizon: float) -> float:
    """Kaplan-Meier survival at ``horizon`` (same units as ``time``)."""
    time = np.asarray(time, dtype=float)
    event = np.asarray(event).astype(int)
    surv = 1.0
    for t in np.unique(time[(event == 1) & (time <= horizon)]):
        at_risk = int((time >= t).sum())
        deaths = int(((time == t) & (event == 1)).sum())
        surv *= 1.0 - deaths / at_risk
    return surv


_AGE_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)")
_AGE_SINGLE = re.compile(r"^\s*(\d+)\s*years?\s*$")


def age_midpoint(label: Any) -> float:
    """Midpoint in years of a CTC age-group label, NaN for open-ended or unknown ones."""
    text = str(label)
    m = _AGE_RANGE.match(text)
    if m:
        return (int(m.group(1)) + int(m.group(2))) / 2.0
    m = _AGE_SINGLE.match(text)
    return float(m.group(1)) if m else np.nan


def _missing(df: pd.DataFrame, cols: Sequence[str]) -> List[str]:
    return [c for c in cols if c not in df.columns]


def _row(item: Mapping[str, Any], kind: str, **values: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {col: np.nan for col in REPORT_COLUMNS}
    row.update(
        id=item["id"], name=item["name"], family=item["family"], status=item["status"],
        kind=kind, note="",
    )
    row.update(values)
    return row


def _not_evaluable(item: Mapping[str, Any], kind: str, reason: str) -> Dict[str, Any]:
    return _row(item, kind, result="not_evaluable", note=reason)


# ---------------------------------------------------------------------------
# hard rules
# ---------------------------------------------------------------------------

def _trigger_mask(constraint: Constraint, df: pd.DataFrame) -> pd.Series:
    if isinstance(constraint, AllowedValuesConstraint):
        return df[constraint.trigger_col].isin(constraint.trigger_values)
    return pd.Series(True, index=df.index)


def _hard_row(
    constraint: Constraint,
    meta: Mapping[str, Any],
    cohort: pd.DataFrame,
    reference: Optional[pd.DataFrame],
    min_cell: int,
) -> Dict[str, Any]:
    refs = list(constraint.column_refs().values())
    gone = _missing(cohort, refs)
    if gone:
        return _not_evaluable(meta, "hard_rule", f"column not in cohort: {', '.join(gone)}")
    eligible = int(_trigger_mask(constraint, cohort).sum())
    flagged = int(constraint.find_violations(cohort).sum())
    hide = _hidden(eligible, min_cell) or _hidden(flagged, min_cell)
    row = _row(
        meta, "hard_rule", metric="violation_rate",
        n_eligible=_suppress(eligible, min_cell), n_flagged=_suppress(flagged, min_cell),
    )
    if hide:
        row["result"] = "suppressed"
        row["note"] = f"count under {min_cell}"
    elif eligible == 0:
        row["result"] = "no_eligible_records"
    else:
        row["cohort_value"] = flagged / eligible
        row["result"] = "ok" if flagged == 0 else "VIOLATIONS"
    if reference is not None and not _missing(reference, refs):
        r_elig = int(_trigger_mask(constraint, reference).sum())
        r_flag = int(constraint.find_violations(reference).sum())
        row["n_reference"] = _suppress(r_elig, min_cell)
        row["reference_source"] = "reference_data"
        if not (_hidden(r_elig, min_cell) or _hidden(r_flag, min_cell)) and r_elig:
            row["reference_value"] = r_flag / r_elig
            if r_flag:
                row["note"] = (
                    "the reference data also violates this rule: the statement may be wrong"
                )
    return row


# ---------------------------------------------------------------------------
# probabilistic checks
# ---------------------------------------------------------------------------

def _group_counts(df: pd.DataFrame, check: Mapping[str, Any]) -> Dict[Any, float]:
    sub = df.loc[df[check["group_col"]].isin(check["group_values"]), check["target_col"]]
    return {k: float(v) for k, v in sub.value_counts().items()}


def _distribution_row(check, cohort, reference, published, min_cell):
    cols = [check["group_col"], check["target_col"]]
    gone = _missing(cohort, cols)
    if gone:
        return _not_evaluable(check, "distribution", f"column not in cohort: {', '.join(gone)}")
    counts = _group_counts(cohort, check)
    n = int(sum(counts.values()))
    focus = check.get("focus_values")
    row = _row(check, "distribution", metric="share_in_focus" if focus else "tvd",
               n_eligible=_suppress(n, min_cell))
    if n == 0:
        row["result"] = "no_eligible_records"
        return row
    if _hidden(n, min_cell):
        row["result"] = "suppressed"
        row["note"] = f"count under {min_cell}"
        return row
    shares = _shares(counts)
    ref_shares: Optional[Dict[Any, float]] = None
    if published is not None and check["id"] in published:
        ref_shares = _shares(dict(published[check["id"]]))
        row["reference_source"] = "published"
    elif reference is not None and not _missing(reference, cols):
        ref_counts = _group_counts(reference, check)
        n_ref = int(sum(ref_counts.values()))
        row["n_reference"] = _suppress(n_ref, min_cell)
        row["reference_source"] = "reference_data"
        if n_ref and not _hidden(n_ref, min_cell):
            ref_shares = _shares(ref_counts)
    if focus:
        row["cohort_value"] = float(sum(shares.get(v, 0.0) for v in focus))
    if ref_shares is None:
        row["result"] = "needs_reference"
        return row
    row["tvd"] = _tvd(shares, ref_shares)
    if focus:
        row["reference_value"] = float(sum(ref_shares.get(v, 0.0) for v in focus))
        row["difference"] = row["cohort_value"] - row["reference_value"]
    row["result"] = "compared"
    return row


def distribution_detail(
    cohort: pd.DataFrame,
    check: Mapping[str, Any],
    reference: Optional[pd.DataFrame] = None,
    min_cell: int = DEFAULT_MIN_CELL,
) -> pd.DataFrame:
    """Per-value counts and shares behind one ``distribution`` check, with suppression."""
    counts = _group_counts(cohort, check)
    ref_counts = _group_counts(reference, check) if reference is not None else {}
    n, n_ref = sum(counts.values()), sum(ref_counts.values())
    rows = []
    for value in sorted(set(counts) | set(ref_counts), key=str):
        c, r = counts.get(value, 0.0), ref_counts.get(value, 0.0)
        c_hid, r_hid = _hidden(c, min_cell), _hidden(r, min_cell)
        rows.append({
            "value": value,
            "n_cohort": _suppress(c, min_cell),
            "share_cohort": np.nan if c_hid or not n else c / n,
            "n_reference": _suppress(r, min_cell),
            "share_reference": np.nan if r_hid or not n_ref else r / n_ref,
        })
    return pd.DataFrame(rows, columns=[
        "value", "n_cohort", "share_cohort", "n_reference", "share_reference"])


def _survival_in_group(df: pd.DataFrame, check: Mapping[str, Any]):
    sub = df.loc[df[check["group_col"]].isin(check["group_values"])]
    return sub, kaplan_meier(sub[check["time_col"]], sub[check["event_col"]],
                             float(check["horizon_months"])) if len(sub) else np.nan


def _survival_row(check, cohort, reference, published, min_cell):
    cols = [check["group_col"], check["time_col"], check["event_col"]]
    gone = _missing(cohort, cols)
    if gone:
        return _not_evaluable(
            check, "survival_5y",
            f"column not in cohort: {', '.join(gone)} (time and event exist only when the "
            "survival rule ran)")
    sub, km = _survival_in_group(cohort, check)
    n = len(sub)
    row = _row(check, "survival_5y", metric="survival_at_horizon",
               n_eligible=_suppress(n, min_cell))
    if n == 0:
        row["result"] = "no_eligible_records"
        return row
    if _hidden(n, min_cell):
        row["result"] = "suppressed"
        row["note"] = f"count under {min_cell}"
        return row
    row["cohort_value"] = km
    target = check.get("target", {}).get("value")
    if published is not None and check["id"] in published:
        row["reference_value"], row["reference_source"] = float(published[check["id"]]), "published"
    elif reference is not None and not _missing(reference, cols):
        ref_sub, ref_km = _survival_in_group(reference, check)
        row["n_reference"] = _suppress(len(ref_sub), min_cell)
        if len(ref_sub) and not _hidden(len(ref_sub), min_cell):
            row["reference_value"], row["reference_source"] = ref_km, "reference_data"
    elif target is not None:
        row["reference_value"], row["reference_source"] = float(target), "draft_target"
        row["note"] = "reference is the unverified read-ahead figure"
    if not np.isnan(row["reference_value"]):
        row["difference"] = km - row["reference_value"]
        row["result"] = "compared"
    else:
        row["result"] = "needs_reference"
    return row


def _stage_violations(df: pd.DataFrame, check: Mapping[str, Any], min_cell: int):
    """Return (groups evaluated, names of groups whose survival rises with stage)."""
    horizon = float(check["horizon_months"])
    evaluated, broken = 0, []
    for group, sub in df.groupby(check["group_col"], observed=True):
        curve = []
        for level in check["stage_order"]:
            lv = sub[sub[check["stage_col"]].isin(level)]
            if len(lv) >= max(min_cell, 1):
                curve.append(kaplan_meier(lv[check["time_col"]], lv[check["event_col"]], horizon))
        if len(curve) < 2:
            continue
        evaluated += 1
        if any(b > a for a, b in zip(curve, curve[1:])):
            broken.append(str(group))
    return evaluated, broken


def _stage_row(check, cohort, reference, published, min_cell):
    cols = [check["group_col"], check["stage_col"], check["time_col"], check["event_col"]]
    gone = _missing(cohort, cols)
    if gone:
        return _not_evaluable(
            check, "stage_monotone",
            f"column not in cohort: {', '.join(gone)} (time and event exist only when the "
            "survival rule ran)")
    evaluated, broken = _stage_violations(cohort, check, min_cell)
    row = _row(check, "stage_monotone", metric="share_of_groups_out_of_order",
               n_eligible=float(evaluated), n_flagged=float(len(broken)))
    if not evaluated:
        row["result"] = "no_eligible_records"
        row["note"] = f"no group has two stage levels with at least {min_cell} records"
        return row
    row["cohort_value"] = len(broken) / evaluated
    row["result"] = "reported"
    row["note"] = "groups out of order: " + ("; ".join(broken[:5]) if broken else "none")
    if reference is not None and not _missing(reference, cols):
        r_eval, r_broken = _stage_violations(reference, check, min_cell)
        row["reference_source"] = "reference_data"
        if r_eval:
            row["reference_value"] = len(r_broken) / r_eval
            row["difference"] = row["cohort_value"] - row["reference_value"]
            row["result"] = "compared"
    return row


def _age_stats(df: pd.DataFrame, check: Mapping[str, Any], min_cell: int) -> Dict[Any, tuple]:
    ages = df[check["age_col"]].map(age_midpoint)
    stats = {}
    for group, vals in ages.groupby(df[check["group_col"]], observed=True):
        vals = vals.dropna()
        if len(vals) >= max(min_cell, 2) and vals.std(ddof=0) > 0:
            stats[group] = (float(vals.mean()), float(vals.std(ddof=0)))
    return stats


def _flag_count(df: pd.DataFrame, check: Mapping[str, Any], stats: Mapping[Any, tuple]):
    ages = df[check["age_col"]].map(age_midpoint)
    mean = df[check["group_col"]].map(lambda g: stats.get(g, (np.nan, np.nan))[0])
    sd = df[check["group_col"]].map(lambda g: stats.get(g, (np.nan, np.nan))[1])
    usable = ages.notna() & mean.notna()
    flagged = usable & ((ages - mean).abs() > float(check["sd_threshold"]) * sd)
    return int(usable.sum()), int(flagged.sum())


def _outlier_row(check, cohort, reference, published, min_cell):
    cols = [check["group_col"], check["age_col"]]
    gone = _missing(cohort, cols)
    if gone:
        return _not_evaluable(check, "age_outlier", f"column not in cohort: {', '.join(gone)}")
    if reference is None or _missing(reference, cols):
        return _row(check, "age_outlier", metric="flagged_rate", result="needs_reference",
                    note="the real age distribution per diagnosis group is required")
    stats = _age_stats(reference, check, min_cell)
    n, flagged = _flag_count(cohort, check, stats)
    r_n, r_flagged = _flag_count(reference, check, stats)
    row = _row(check, "age_outlier", metric="flagged_rate",
               n_eligible=_suppress(n, min_cell), n_flagged=_suppress(flagged, min_cell),
               n_reference=_suppress(r_n, min_cell), reference_source="reference_data")
    if n == 0 or _hidden(n, min_cell) or _hidden(flagged, min_cell):
        row["result"] = "suppressed" if n else "no_eligible_records"
        return row
    row["cohort_value"] = flagged / n
    if r_n and not (_hidden(r_n, min_cell) or _hidden(r_flagged, min_cell)):
        row["reference_value"] = r_flagged / r_n
        row["difference"] = row["cohort_value"] - row["reference_value"]
    row["result"] = "compared"
    return row


_CHECK_RUNNERS = {
    "distribution": _distribution_row,
    "survival_5y": _survival_row,
    "stage_monotone": _stage_row,
    "age_outlier": _outlier_row,
}


def run_battery(
    cohort: pd.DataFrame,
    battery: Battery,
    reference: Optional[pd.DataFrame] = None,
    published: Optional[Mapping[str, Any]] = None,
    min_cell: int = DEFAULT_MIN_CELL,
) -> pd.DataFrame:
    """Run every implemented item and return one row per rule or check.

    ``reference`` is a real (or trusted) DataFrame with the same column names. ``published``
    maps a check id to a published value: a mapping of value to proportion or count for a
    ``distribution`` check, or a number for a ``survival_5y`` check. Roadmap items are listed
    with result ``not_implementable``. Counts under ``min_cell`` are suppressed.
    """
    rows: List[Dict[str, Any]] = []
    for constraint in battery.constraints:
        meta = battery.constraint_meta[constraint.name]
        rows.append(_hard_row(constraint, meta, cohort, reference, min_cell))
    for check in battery.checks:
        rows.append(_CHECK_RUNNERS[check["kind"]](check, cohort, reference, published, min_cell))
    for item in battery.roadmap:
        rows.append(_row(
            {"id": item["id"], "name": item["statement"], "family": item["family"],
             "status": "draft"},
            "roadmap", result="not_implementable", note=item["reason"]))
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def write_report(table: pd.DataFrame, path: Union[str, Path]) -> Path:
    """Write the report table as CSV."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)
    return out
