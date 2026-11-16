"""Measure real participant-level data and export disclosure-controlled aggregates.

The mirror image of the ingestion layer. The Input team runs ``synthpediatric measure``
inside the CGC workspace on the real extract. It writes only aggregates, in the formats
the generator already reads:

* ``freqs/<variable>.json``     one frequency table, a ``targets.overrides.tables`` file
* ``crosstabs/<name>.csv``      clique columns plus ``count``, a ``targets.joints.crosstabs`` file
* ``survival/<name>.json``      group -> spec, a ``targets.survival.specs`` file
* ``survival/<name>_summary.csv``  n, 5-year survival, median and chosen time points per group
* ``measure_manifest.json``     what was measured, the threshold, suppression counts, hashes

Disclosure control (threshold default 16):

* A frequency or cross-tab cell below the threshold is not written. The category has no
  count, which is how the published NCCR metadata represents a suppressed value.
* Complementary suppression runs along every line of every table, reusing
  :func:`synthpediatric.validate._suppress`, so a lone suppressed cell cannot be recovered
  from a row, column or 1-way margin.
* A survival group with fewer than ``threshold`` participants is not exported. A survival
  value (point, 5-year survival, median) is exported only when at least ``threshold``
  participants are still at risk at that time and the number of events up to that time is 0
  or at least ``threshold``.
* Every output is audited before it is moved into place (:func:`audit_outputs`, which reuses
  :func:`synthpediatric.validate.audit_report`). Unsafe output is deleted and the run fails.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from . import __version__
from .analyze import kaplan_meier
from .config import (
    ConfigError,
    check_keys,
    file_sha256,
    read_structured,
    unknown_message,
)
from .validate import ValidationError, _suppress, audit_report, read_frame

DEFAULT_THRESHOLD = 16
DEFAULT_MAX_LEVELS = 200
DEFAULT_HORIZON_MONTHS = 120.0
MANIFEST_NAME = "measure_manifest.json"
SURVIVAL_FORMS = ("points", "s5", "median_months")

TOP_KEYS = (
    "name", "data", "rename", "labels", "bins", "dictionary", "strict", "cohort", "threshold",
    "max_levels", "frequencies", "crosstabs", "survival", "outputs",
)
SURVIVAL_KEYS = (
    "name", "group", "time", "event", "event_values", "horizon_months", "time_points", "s5",
    "median", "form", "time_resolution_months",
)


class MeasureError(ConfigError):
    """The measure config or the data does not fit. The message names the key and fix."""


class MeasureAuditError(ValueError):
    """An output file is not safe to leave CGC."""


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def _as_int(where: str, value: Any, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MeasureError(f"{where}: expected an integer >= {minimum}, got {value!r}")
    return value


def _as_name(where: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise MeasureError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _safe(name: str) -> str:
    out = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name).strip("._")
    return out or "table"


def _str_list(where: str, value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise MeasureError(f"{where}: expected a non-empty list of variable names")
    return [_as_name(f"{where}[{i}]", v) for i, v in enumerate(value)]


def _unique_names(where: str, names: Sequence[str]) -> None:
    seen = set()
    for n in names:
        if n in seen:
            raise MeasureError(f"{where}: '{n}' is used twice; names must be unique")
        seen.add(n)


def _norm_survival(where: str, value: Any) -> Dict[str, Any]:
    check_keys(where, value, SURVIVAL_KEYS, required=("group", "time", "event"))
    horizon = value.get("horizon_months", DEFAULT_HORIZON_MONTHS)
    if isinstance(horizon, bool) or not isinstance(horizon, (int, float)) or horizon <= 0:
        raise MeasureError(f"{where}.horizon_months: expected a positive number, got {horizon!r}")
    points = value.get("time_points", [])
    if not isinstance(points, list) or any(
        isinstance(p, bool) or not isinstance(p, (int, float)) or p <= 0 for p in points
    ):
        raise MeasureError(f"{where}.time_points: expected a list of positive months")
    if any(p > horizon for p in points):
        raise MeasureError(f"{where}.time_points: a time point is beyond horizon_months {horizon}")
    points = sorted({float(p) for p in points})
    s5 = value.get("s5", True)
    median = value.get("median", False)
    if not isinstance(s5, bool) or not isinstance(median, bool):
        raise MeasureError(f"{where}: s5 and median must be true or false")
    if s5 and horizon < 60:
        raise MeasureError(f"{where}.s5: horizon_months {horizon} is below 60; set s5: false")
    form = value.get("form")
    if form is None:
        form = "points" if points else ("s5" if s5 else "median_months")
    if form not in SURVIVAL_FORMS:
        raise MeasureError(
            unknown_message(f"{where}.form", "choice", form, SURVIVAL_FORMS)
        )
    if (form == "points" and not points) or (form == "s5" and not s5) or (
        form == "median_months" and not median
    ):
        raise MeasureError(
            f"{where}.form: '{form}' needs its statistic: time_points, s5: true or median: true"
        )
    resolution = value.get("time_resolution_months", 1)
    if isinstance(resolution, bool) or not isinstance(resolution, (int, float)) or resolution <= 0:
        raise MeasureError(f"{where}.time_resolution_months: expected a positive number")
    event_values = value.get("event_values")
    if event_values is not None:
        event_values = [str(v) for v in _str_list(f"{where}.event_values", event_values)]
    group = _as_name(f"{where}.group", value["group"])
    return {
        "name": _safe(str(value.get("name") or f"survival_by_{group}")),
        "group": group,
        "time": _as_name(f"{where}.time", value["time"]),
        "event": _as_name(f"{where}.event", value["event"]),
        "event_values": event_values,
        "horizon_months": float(horizon),
        "time_points": points,
        "s5": s5,
        "median": median,
        "form": form,
        "time_resolution_months": float(resolution),
    }


def _norm_cohort(where: str, value: Any) -> Optional[Dict[str, Any]]:
    if value in (None, {}, []):
        return None
    check_keys(where, value, ("name", "filters"), required=("filters",))
    filters = value["filters"]
    if not isinstance(filters, list) or not filters:
        raise MeasureError(f"{where}.filters: expected a non-empty list of filters")
    out = []
    for i, flt in enumerate(filters):
        w = f"{where}.filters[{i}]"
        check_keys(w, flt, ("variable", "op", "values", "threshold"), required=("variable", "op"))
        op = str(flt["op"]).lower()
        if op not in ("equals", "min", "max"):
            raise MeasureError(f"{w}.op: unknown value {op!r}. Valid choices: equals, min, max")
        item: Dict[str, Any] = {"variable": _as_name(f"{w}.variable", flt["variable"]), "op": op}
        if op == "equals":
            if not isinstance(flt.get("values"), list) or not flt["values"]:
                raise MeasureError(f"{w}.values: 'equals' requires a non-empty list")
            item["values"] = [str(v) for v in flt["values"]]
        else:
            th = flt.get("threshold")
            if isinstance(th, bool) or not isinstance(th, (int, float)):
                raise MeasureError(f"{w}.threshold: '{op}' requires a number")
            item["threshold"] = float(th)
        out.append(item)
    return {"name": str(value.get("name", "cohort")), "filters": out}


def _norm_bins(where: str, value: Any) -> Dict[str, Dict[str, Any]]:
    if value in (None, {}):
        return {}
    if not isinstance(value, Mapping):
        raise MeasureError(f"{where}: expected a mapping of variable -> {{edges, labels}}")
    out = {}
    for var, spec in value.items():
        w = f"{where}.{var}"
        check_keys(w, spec, ("edges", "labels"), required=("edges", "labels"))
        edges, labels = spec["edges"], spec["labels"]
        if (
            not isinstance(edges, list) or len(edges) < 2
            or any(isinstance(e, bool) or not isinstance(e, (int, float)) for e in edges)
            or any(b <= a for a, b in zip(edges, edges[1:]))
        ):
            raise MeasureError(f"{w}.edges: expected an increasing list of at least two numbers")
        if not isinstance(labels, list) or len(labels) != len(edges) - 1:
            raise MeasureError(f"{w}.labels: expected {len(edges) - 1} labels (one per interval)")
        _unique_names(f"{w}.labels", [str(x) for x in labels])
        out[str(var)] = {"edges": [float(e) for e in edges], "labels": [str(x) for x in labels]}
    return out


def normalize_measure_config(source: Union[Mapping[str, Any], str, Path]) -> Dict[str, Any]:
    """Validate a measure config (a mapping, or a path to a YAML or JSON file)."""
    raw = dict(source) if isinstance(source, Mapping) else read_structured(source)
    if not isinstance(raw, Mapping):
        raise MeasureError("measure config: expected a mapping at the top level")
    check_keys("measure config", raw, TOP_KEYS, required=("data",))
    data = raw["data"]
    data = [data] if isinstance(data, str) else data
    if not isinstance(data, list) or not data:
        raise MeasureError("data: expected a file path or a non-empty list of file paths")
    data = [_as_name(f"data[{i}]", d) for i, d in enumerate(data)]
    threshold = _as_int("threshold", raw.get("threshold", DEFAULT_THRESHOLD), 1)
    max_levels = _as_int("max_levels", raw.get("max_levels", DEFAULT_MAX_LEVELS), 2)
    strict = raw.get("strict", True)
    if not isinstance(strict, bool):
        raise MeasureError("strict: expected true or false")
    rename = raw.get("rename") or {}
    if not isinstance(rename, Mapping) or any(not isinstance(v, str) for v in rename.values()):
        raise MeasureError("rename: expected a mapping of extract column -> NCCR variable name")
    labels = raw.get("labels") or {}
    if not isinstance(labels, Mapping) or any(not isinstance(v, Mapping) for v in labels.values()):
        raise MeasureError("labels: expected a mapping of variable -> {extract value: NCCR label}")
    labels = {
        str(var): {str(k): str(v) for k, v in m.items()} for var, m in labels.items()
    }
    freqs = _str_list("frequencies", raw["frequencies"]) if raw.get("frequencies") else []
    _unique_names("frequencies", freqs)
    crosstabs = []
    for i, item in enumerate(raw.get("crosstabs") or []):
        w = f"crosstabs[{i}]"
        if isinstance(item, Mapping):
            check_keys(w, item, ("name", "variables"), required=("variables",))
            variables = _str_list(f"{w}.variables", item["variables"])
            name = item.get("name")
        else:
            variables, name = _str_list(w, item), None
        if len(variables) < 2:
            raise MeasureError(f"{w}: a cross-tab needs at least two variables")
        _unique_names(f"{w}.variables", variables)
        crosstabs.append({"name": _safe(str(name or "_".join(variables))), "variables": variables})
    survival = [
        _norm_survival(f"survival[{i}]", s) for i, s in enumerate(raw.get("survival") or [])
    ]
    for kind, items in (("crosstabs", crosstabs), ("survival", survival)):
        _unique_names(kind, [x["name"] for x in items])
    if not (freqs or crosstabs or survival):
        raise MeasureError(
            "nothing to measure: list at least one of frequencies, crosstabs or survival"
        )
    outputs = raw.get("outputs") or {}
    check_keys("outputs", outputs, ("dir",))
    dictionary = raw.get("dictionary")
    if dictionary is not None:
        dictionary = _as_name("dictionary", dictionary)
    return {
        "name": str(raw.get("name", "measure")),
        "data": data,
        "rename": {str(k): v for k, v in rename.items()},
        "labels": labels,
        "bins": _norm_bins("bins", raw.get("bins")),
        "dictionary": dictionary,
        "strict": strict,
        "cohort": _norm_cohort("cohort", raw.get("cohort")),
        "threshold": threshold,
        "max_levels": max_levels,
        "frequencies": freqs,
        "crosstabs": crosstabs,
        "survival": survival,
        "outputs": {"dir": outputs.get("dir")},
    }


def measure_config_hash(config: Mapping[str, Any]) -> str:
    """SHA-256 of the normalized measure config (without the output directory)."""
    payload = {k: v for k, v in config.items() if k != "outputs"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Data preparation
# --------------------------------------------------------------------------- #

def _read_data(paths: Sequence[str]) -> Tuple[pd.DataFrame, Dict[str, str]]:
    frames, hashes = [], {}
    for p in paths:
        if not Path(p).is_file():
            raise MeasureError(f"data: file not found: {p}")
        try:
            frames.append(read_frame(p))
        except ValidationError as exc:
            raise MeasureError(f"data: {exc}") from exc
        hashes[p] = file_sha256(p)
    first = list(frames[0].columns)
    for p, f in zip(paths[1:], frames[1:]):
        if set(f.columns) != set(first):
            raise MeasureError(f"data: {p} has different columns from {paths[0]}")
    return pd.concat(frames, ignore_index=True), hashes


def _apply_rename(frame: pd.DataFrame, rename: Mapping[str, str]) -> pd.DataFrame:
    for col in rename:
        if col not in frame.columns:
            raise MeasureError(unknown_message("rename", "column", col, frame.columns))
    clash = [n for n in rename.values() if n in frame.columns and n not in rename]
    if clash:
        raise MeasureError(f"rename: target name '{clash[0]}' already exists in the extract")
    frame = frame.rename(columns=dict(rename))
    if frame.columns.duplicated().any():
        raise MeasureError("rename: two columns end up with the same name")
    return frame


def _text(s: pd.Series) -> pd.Series:
    """Labels as text. Integral floats lose the '.0'; missing stays missing."""
    if pd.api.types.is_float_dtype(s):
        nonnull = s.dropna()
        if len(nonnull) and bool(np.all(np.mod(nonnull.to_numpy(float), 1) == 0)):
            s = s.astype("Int64")
    out = s.astype("string").str.strip()
    out = out.mask(out == "")
    return out.astype(object).where(out.notna(), None)


def _require_column(frame: pd.DataFrame, where: str, name: str) -> None:
    if name not in frame.columns:
        raise MeasureError(unknown_message(where, "variable", name, frame.columns))


def _apply_cohort(frame: pd.DataFrame, cohort: Optional[Mapping[str, Any]]) -> pd.DataFrame:
    if not cohort:
        return frame
    keep = np.ones(len(frame), dtype=bool)
    for i, flt in enumerate(cohort["filters"]):
        where = f"cohort.filters[{i}].variable"
        _require_column(frame, where, flt["variable"])
        col = frame[flt["variable"]]
        if flt["op"] == "equals":
            keep &= _text(col).isin(flt["values"]).to_numpy()
        else:
            num = pd.to_numeric(col, errors="coerce")
            if num.notna().sum() == 0:
                raise MeasureError(
                    f"{where}: '{flt['variable']}' has no numeric values; use an 'equals' filter"
                )
            ok = num >= flt["threshold"] if flt["op"] == "min" else num <= flt["threshold"]
            keep &= ok.fillna(False).to_numpy()
    out = frame.loc[keep]
    if len(out) == 0:
        raise MeasureError("cohort: the filters leave no participants")
    return out


class _Prepared:
    """Categorical views of the extract's columns, with the warnings collected so far."""

    def __init__(self, frame: pd.DataFrame, config: Mapping[str, Any], dictionary: Any) -> None:
        self.frame = frame
        self.config = config
        self.dictionary = dictionary
        self.warnings = 0
        self._cache: Dict[str, pd.Series] = {}

    def _flag(self, message: str) -> None:
        if self.config["strict"]:
            raise MeasureError(message)
        self.warnings += 1

    def categorical(self, where: str, var: str) -> pd.Series:
        if var in self._cache:
            return self._cache[var]
        _require_column(self.frame, where, var)
        col = self.frame[var]
        bins = self.config["bins"].get(var)
        if bins is not None:
            num = pd.to_numeric(col, errors="coerce")
            out = pd.cut(num, bins["edges"], labels=bins["labels"], right=False)
            out = out.astype(object).where(out.notna(), None)
        else:
            if pd.api.types.is_float_dtype(col):
                nonnull = col.dropna().to_numpy(float)
                if len(nonnull) and bool(np.any(np.mod(nonnull, 1) != 0)):
                    raise MeasureError(
                        f"{where}: '{var}' is continuous (non-integer numbers). Add it under "
                        "'bins' with edges and labels, or measure it as a survival time"
                    )
            out = _text(col)
            mapping = self.config["labels"].get(var)
            if mapping:
                out = out.map(lambda v: mapping.get(v, v) if v is not None else None)
        levels = out.dropna().nunique()
        if levels > self.config["max_levels"]:
            raise MeasureError(
                f"{where}: '{var}' has {levels} distinct values (max_levels is "
                f"{self.config['max_levels']}). It looks like an identifier or a continuous "
                "variable; add 'bins' or raise max_levels"
            )
        self._check_labels(where, var, out)
        self._cache[var] = out
        return out

    def _check_labels(self, where: str, var: str, values: pd.Series) -> None:
        d = self.dictionary
        if d is None:
            return
        if var not in d.variables:
            self._flag(unknown_message(where, "variable", var, d.variables, " (in dictionary)"))
            return
        known = [str(c) for c in d.variables[var].categories]
        unknown = sorted({str(v) for v in values.dropna().unique()} - set(known))
        for label in unknown[:3]:
            self._flag(
                unknown_message(f"{where}.{var}", "category", label, known, " (in the extract)")
            )
        if len(unknown) > 3:
            self.warnings += 1


# --------------------------------------------------------------------------- #
# Disclosure control
# --------------------------------------------------------------------------- #

Cell = Tuple[str, ...]


def suppress_table(
    counts: Mapping[Cell, int], threshold: int
) -> Tuple[Dict[Cell, int], Dict[str, int]]:
    """Suppress a (cross-)tabulation. Returns the cells that may leave and the suppression stats.

    Cells with a count below ``threshold`` are suppressed. Then, along every line of the table
    (a 1-way table is one line; a cross-tab has a line for every axis and every setting of the
    other axes), a line with exactly one suppressed cell also loses its smallest other cell
    (:func:`synthpediatric.validate._suppress`). Lines are revisited until nothing changes.
    """
    cells = list(counts)
    if not cells:
        return {}, {"cells": 0, "suppressed_primary": 0, "suppressed_complementary": 0}
    ndim = len(cells[0])
    primary = {c for c in cells if counts[c] < threshold}
    suppressed = set(primary)
    lines: List[List[Cell]] = []
    for axis in range(ndim):
        groups: Dict[Cell, List[Cell]] = {}
        for c in cells:
            groups.setdefault(c[:axis] + c[axis + 1:], []).append(c)
        lines.extend(g for g in groups.values() if len(g) > 1)
    if ndim == 1:
        lines = [cells] if len(cells) > 1 else []
    changed = True
    while changed:
        changed = False
        for line in lines:
            # suppressed cells go in as 0, so _suppress sees them as below the threshold
            flags = _suppress([0 if c in suppressed else counts[c] for c in line], threshold)
            for cell, flag in zip(line, flags):
                if flag and cell not in suppressed:
                    suppressed.add(cell)
                    changed = True
    kept = {c: int(counts[c]) for c in cells if c not in suppressed}
    return kept, {
        "cells": len(cells),
        "suppressed_primary": len(primary),
        "suppressed_complementary": len(suppressed) - len(primary),
    }


# --------------------------------------------------------------------------- #
# Measures
# --------------------------------------------------------------------------- #

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _num(x: float) -> Any:
    return int(x) if float(x).is_integer() else x


def _write_specs(path: Path, specs: Mapping[str, Any]) -> None:
    """One group per line. Points are [month, survival] pairs: JSON keys are text and the
    generator sorts a mapping's keys as text ("120" before "60"), so a list of pairs is safer."""
    lines = []
    for g, spec in specs.items():
        ((form, val),) = spec.items()
        if form == "points":
            val = [[_num(t), v] for t, v in val]
        lines.append(f"  {json.dumps(str(g), ensure_ascii=False)}: {json.dumps({form: val})}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def _measure_frequency(prep: _Prepared, var: str, out: Path, threshold: int) -> Dict[str, Any]:
    s = prep.categorical("frequencies", var).dropna()
    counts = {(str(k),): int(v) for k, v in s.value_counts().items()}
    kept, stats = suppress_table(counts, threshold)
    entry: Dict[str, Any] = {"kind": "frequency", "variables": [var], **stats}
    entry["cells_written"] = len(kept)
    if not kept:
        entry["file"] = None
        entry["note"] = "every cell was suppressed; no file written"
        return entry
    rel = f"freqs/{_safe(var)}.json"
    _write_json(out / rel, {var: {k[0]: v for k, v in sorted(kept.items())}})
    entry["file"] = rel
    return entry


def _measure_crosstab(
    prep: _Prepared, spec: Mapping[str, Any], out: Path, threshold: int
) -> Dict[str, Any]:
    variables = spec["variables"]
    cols = {v: prep.categorical("crosstabs", v) for v in variables}
    sub = pd.DataFrame(cols).dropna()
    counts: Dict[Cell, int] = {}
    if len(sub):
        for key, n in sub.groupby(variables, sort=True).size().items():
            counts[tuple(str(k) for k in key)] = int(n)
    kept, stats = suppress_table(counts, threshold)
    entry: Dict[str, Any] = {
        "kind": "crosstab", "name": spec["name"], "variables": variables, **stats,
        "cells_written": len(kept),
    }
    if not kept:
        entry["file"] = None
        entry["note"] = "every cell was suppressed; no file written"
        return entry
    rel = f"crosstabs/{spec['name']}.csv"
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(variables + ["count"])
        for cell, n in sorted(kept.items()):
            w.writerow(list(cell) + [n])
    entry["file"] = rel
    return entry


def _at_risk_ok(time: np.ndarray, event: np.ndarray, t: float, threshold: int) -> bool:
    """A survival value at ``t`` may leave when enough participants are still at risk and the
    number of events so far is not a small positive count."""
    at_risk = int(np.sum(time >= t))
    events = int(np.sum(event[time <= t]))
    return at_risk >= threshold and not (0 < events < threshold)


def _event_array(col: pd.Series, values: Optional[Sequence[str]], where: str) -> pd.Series:
    if values is not None:
        txt = _text(col)
        return txt.isin(list(values)).astype(float).where(txt.notna())
    as_int = col.map(lambda v: int(v) if isinstance(v, (bool, np.bool_)) else v)
    num = pd.to_numeric(as_int, errors="coerce")
    bad = num.dropna()
    if not bad.isin([0, 1]).all():
        raise MeasureError(
            f"{where}: the event column must hold 0/1 (or true/false). For text values such as "
            "'Dead' list them under event_values"
        )
    return num


def _measure_survival(
    prep: _Prepared, spec: Mapping[str, Any], out: Path, threshold: int
) -> Dict[str, Any]:
    where = "survival"
    group = prep.categorical(f"{where}.group", spec["group"])
    _require_column(prep.frame, f"{where}.time", spec["time"])
    _require_column(prep.frame, f"{where}.event", spec["event"])
    time = pd.to_numeric(prep.frame[spec["time"]], errors="coerce")
    event = _event_array(prep.frame[spec["event"]], spec["event_values"], f"{where}.event")
    df = pd.DataFrame({"g": group, "t": time, "e": event}).dropna()
    if (df["t"] < 0).any():
        raise MeasureError(f"{where}.time: '{spec['time']}' has negative times")
    horizon, res = spec["horizon_months"], spec["time_resolution_months"]
    t = np.minimum(df["t"].to_numpy(float), horizon)
    e = np.where(df["t"].to_numpy(float) > horizon, 0, df["e"].to_numpy(float)).astype(int)
    t = np.floor(t / res + 1e-9) * res
    df = df.assign(t=t, e=e)
    points = list(spec["time_points"])
    stats_wanted = (["s5"] if spec["s5"] else []) + [f"s{p:g}" for p in points]
    if spec["median"]:
        stats_wanted.append("median_months")
    specs: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    dropped_small = no_stats = withheld = 0
    for g, sub in sorted(df.groupby("g", sort=True), key=lambda kv: str(kv[0])):
        n = len(sub)
        if n < threshold:
            dropped_small += 1
            continue
        tt, ee = sub["t"].to_numpy(float), sub["e"].to_numpy(int)
        km = kaplan_meier(tt, ee)

        def surv(at: float) -> Optional[float]:
            if not _at_risk_ok(tt, ee, at, threshold):
                return None
            return round(km.survival_at(at), 4)

        row: Dict[str, Any] = {"group": str(g), "n": n}
        if spec["s5"]:
            row["s5"] = surv(60.0)
        for p in points:
            row[f"s{p:g}"] = surv(p)
        if spec["median"]:
            m = km.median_survival()
            ok = not math.isnan(m) and m > 0 and _at_risk_ok(tt, ee, m, threshold)
            row["median_months"] = round(m, 2) if ok else None
        withheld += sum(1 for k in stats_wanted if row.get(k) is None)
        rows.append(row)
        if spec["form"] == "points":
            pts = [[p, row[f"s{p:g}"]] for p in points if row[f"s{p:g}"] is not None]
            gen: Any = {"points": pts} if pts else None
        elif spec["form"] == "s5":
            gen = {"s5": row["s5"]} if row["s5"] is not None else None
        else:
            gen = {"median_months": row["median_months"]} if row["median_months"] else None
        if gen is None:
            no_stats += 1
        else:
            specs[str(g)] = gen
    entry: Dict[str, Any] = {
        "kind": "survival", "name": spec["name"],
        "variables": [spec["group"], spec["time"], spec["event"]],
        "form": spec["form"], "horizon_months": horizon, "time_resolution_months": res,
        "groups_exported": len(specs), "groups_dropped_small": dropped_small,
        "groups_without_exportable_value": no_stats, "values_withheld": withheld,
    }
    if not specs:
        entry["file"] = None
        entry["note"] = "no group could be exported; no file written"
        return entry
    cols = ["group", "n"] + stats_wanted
    summary = out / f"survival/{spec['name']}_summary.csv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=cols).to_csv(summary, index=False)
    _write_specs(out / f"survival/{spec['name']}.json", specs)
    entry["file"] = f"survival/{spec['name']}.json"
    entry["summary_file"] = f"survival/{spec['name']}_summary.csv"
    return entry


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #

def _int_count(value: Any, where: str, threshold: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise MeasureAuditError(f"{where}: count {value!r} is not a whole number")
    if value < threshold:
        raise MeasureAuditError(f"{where}: count {int(value)} is below the threshold {threshold}")
    return int(value)


def _audit_report(report: Mapping[str, Any], threshold: int, where: str) -> None:
    try:
        audit_report(report, threshold)
    except ValidationError as exc:
        raise MeasureAuditError(f"{where}: {exc}") from exc


def audit_outputs(out_dir: Union[str, Path], threshold: int = DEFAULT_THRESHOLD) -> List[str]:
    """Check every file under ``out_dir`` and raise :class:`MeasureAuditError` on any unsafe one.

    Allowed layout: ``freqs/*.json``, ``crosstabs/*.csv``, ``survival/*.json``,
    ``survival/*_summary.csv`` and ``measure_manifest.json``. Counts must be whole numbers of
    at least ``threshold``; survival groups must have a summary row with n >= threshold; a file
    anywhere else is refused. Works on any directory in that layout, also hand-made ones.
    Returns the audited relative paths.
    """
    root = Path(out_dir)
    if not root.is_dir():
        raise MeasureAuditError(f"{root}: not a directory")
    audited: List[str] = []
    summaries: Dict[str, Dict[str, int]] = {}
    spec_files: List[Path] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if rel == MANIFEST_NAME:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            _audit_report(manifest, threshold, rel)
            if "participants" in manifest or "records" in manifest:
                raise MeasureAuditError(f"{rel}: manifest holds participant-level data")
        elif len(parts) == 2 and parts[0] == "freqs" and rel.endswith(".json"):
            table = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(table, dict) or not table:
                raise MeasureAuditError(f"{rel}: expected {{variable: {{value: count}}}}")
            for var, freq in table.items():
                if not isinstance(freq, dict) or not freq:
                    raise MeasureAuditError(f"{rel}: '{var}' is not a table of counts")
                levels = [
                    {"real_n": _int_count(c, f"{rel} [{var}={k}]", threshold)}
                    for k, c in freq.items()
                ]
                _audit_report({"levels": levels}, threshold, rel)
        elif len(parts) == 2 and parts[0] == "crosstabs" and rel.endswith(".csv"):
            table = pd.read_csv(path, dtype=str, keep_default_na=False)
            if "count" not in table.columns or len(table.columns) < 3:
                raise MeasureAuditError(f"{rel}: expected clique columns plus 'count'")
            levels = []
            for i, c in enumerate(table["count"]):
                try:
                    num = float(c)
                except ValueError:
                    raise MeasureAuditError(f"{rel}: row {i + 2} has no numeric count") from None
                levels.append({"real_n": _int_count(num, f"{rel} row {i + 2}", threshold)})
            _audit_report({"cells": levels}, threshold, rel)
        elif len(parts) == 2 and parts[0] == "survival" and rel.endswith("_summary.csv"):
            table = pd.read_csv(path, dtype=str, keep_default_na=False)
            if "group" not in table.columns or "n" not in table.columns:
                raise MeasureAuditError(f"{rel}: expected columns group and n")
            ns = {}
            for g, n in zip(table["group"], table["n"]):
                try:
                    num = float(n)
                except ValueError:
                    raise MeasureAuditError(f"{rel}: group '{g}' has no numeric n") from None
                ns[g] = _int_count(num, f"{rel} group '{g}'", threshold)
            _audit_report({"groups": [{"real_n": v} for v in ns.values()]}, threshold, rel)
            summaries[rel[: -len("_summary.csv")]] = ns
        elif len(parts) == 2 and parts[0] == "survival" and rel.endswith(".json"):
            spec_files.append(path)
        else:
            raise MeasureAuditError(
                f"{rel}: unexpected file. Only freqs/*.json, crosstabs/*.csv, "
                "survival/*.json, survival/*_summary.csv and the manifest may be exported"
            )
        audited.append(rel)
    for path in spec_files:
        rel = path.relative_to(root).as_posix()
        specs = json.loads(path.read_text(encoding="utf-8"))
        ns = summaries.get(rel[: -len(".json")])
        if not isinstance(specs, dict) or ns is None:
            raise MeasureAuditError(f"{rel}: survival specs need a matching _summary.csv")
        for g, spec in specs.items():
            if g not in ns:
                raise MeasureAuditError(
                    f"{rel}: group '{g}' is not in the summary (n >= {threshold})"
                )
            one_form = isinstance(spec, dict) and len(spec) == 1
            if not one_form or next(iter(spec)) not in SURVIVAL_FORMS:
                raise MeasureAuditError(f"{rel}: group '{g}' has an unrecognised spec")
    return audited


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def _load_dictionary(spec: Optional[str]) -> Any:
    if not spec:
        return None
    from .validate import load_context_dictionary

    try:
        return load_context_dictionary(spec)
    except ConfigError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise MeasureError(f"dictionary: could not load '{spec}': {exc}") from exc


def run_measure(
    config: Union[Mapping[str, Any], str, Path],
    out_dir: Union[str, Path, None] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Measure the data named in ``config`` and write audited aggregates to ``out_dir``.

    ``out_dir`` defaults to ``outputs.dir`` in the config. The files are built in a staging
    directory next to it, audited, and only then moved into place; on an audit failure
    nothing is left behind. An existing non-empty ``out_dir`` is refused unless
    ``overwrite`` is true and it holds a measure manifest. Returns the manifest.
    """
    cfg = normalize_measure_config(config)
    target = out_dir or cfg["outputs"]["dir"]
    if not target:
        raise MeasureError(
            "outputs.dir: give an output directory in the config or on the command line"
        )
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        if not (overwrite and (target / MANIFEST_NAME).is_file()):
            raise MeasureError(
                f"output directory {target} is not empty. Choose a new one, or pass --overwrite "
                "to replace the results of an earlier measure run"
            )
    threshold = cfg["threshold"]
    frame, hashes = _read_data(cfg["data"])
    frame = _apply_rename(frame, cfg["rename"])
    frame = _apply_cohort(frame, cfg["cohort"])
    prep = _Prepared(frame, cfg, _load_dictionary(cfg["dictionary"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        entries = [_measure_frequency(prep, v, staging, threshold) for v in cfg["frequencies"]]
        entries += [_measure_crosstab(prep, c, staging, threshold) for c in cfg["crosstabs"]]
        entries += [_measure_survival(prep, s, staging, threshold) for s in cfg["survival"]]
        for e in entries:
            if e.get("file"):
                e["sha256"] = file_sha256(staging / e["file"])
        manifest = {
            "tool": f"synthpediatric {__version__}",
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": cfg["name"],
            "measure_config_sha256": measure_config_hash(cfg),
            "input_files_sha256": hashes,
            "threshold": threshold,
            "cohort_filter": cfg["cohort"],
            "strict": cfg["strict"],
            "label_warnings": prep.warnings,
            "outputs": entries,
            "suppressed_cells_total": sum(
                e.get("suppressed_primary", 0) + e.get("suppressed_complementary", 0)
                for e in entries
            ),
            "notes": [
                "Counts of suppressed cells only; no suppressed values, no totals, "
                "no participant-level data.",
                "A suppressed category has no count and is not listed in the file.",
            ],
        }
        _write_json(staging / MANIFEST_NAME, manifest)
        audited = audit_outputs(staging, threshold)
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    manifest["audited_files"] = audited
    manifest["output_dir"] = str(target)
    return manifest


def run_cli(args: Any) -> int:
    """``synthpediatric measure``: run, print a short report, return the exit code."""
    try:
        manifest = run_measure(
            args.config,
            out_dir=args.out_dir,
            overwrite=args.overwrite,
        )
    except MeasureAuditError as exc:
        raise SystemExit(f"audit failed, no output was kept: {exc}")
    except ConfigError as exc:
        raise SystemExit(f"config error: {exc}")
    print(
        f"Measured '{manifest['name']}' (threshold {manifest['threshold']}) "
        f"-> {manifest['output_dir']}/"
    )
    for e in manifest["outputs"]:
        where = e.get("file") or "(nothing written)"
        if e["kind"] == "survival":
            detail = (
                f"{e['groups_exported']} groups exported, {e['groups_dropped_small']} dropped "
                f"(small), {e['values_withheld']} values withheld"
            )
        else:
            detail = (
                f"{e['cells_written']} cells, {e['suppressed_primary']} suppressed, "
                f"{e['suppressed_complementary']} complementary"
            )
        print(f"  {e['kind']:<10} {','.join(e['variables'][:3]):<40} {where}  [{detail}]")
    if manifest["label_warnings"]:
        print(f"warning: {manifest['label_warnings']} label warning(s) (strict: false)")
    print(f"Audit passed on {len(manifest['audited_files'])} files. Manifest: {MANIFEST_NAME}")
    return 0
