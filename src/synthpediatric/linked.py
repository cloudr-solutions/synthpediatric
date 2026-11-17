"""Linked generation: all nine NCCR sources of one cohort, joined on ``nccrId``.

CTC is the parent: one row per tumor, grouped into patients. ``nccrId`` is a seeded random
64-character hex string, one per patient. ``tumorRecordNumber`` is the 2-character zero-padded
rank of the tumor within its patient. ABM has one row per tumor, so it carries the same
``(nccrId, tumorRecordNumber)`` pairs. COG, MCE, CCDI, RO, PHARM, MCD and MCP are children:
each has a ``coverage`` (share of patients with rows) and ``rows_per_patient`` (mean over the
patients that have rows), both configurable, with defaults from the record and patient counts
of ``nccr-metadata/erd.dbml``.

Every table has the full column set of its RAW-JSON data dictionary (plus the columns only the
RDF metadata knows), ``nccrId`` first. A column without a value set is written blank: the
tool does not invent codes, drug names or free text. See ``docs/sources.md``.

A config without ``linked:`` never reaches this module's run code; see ``recipe.run_recipe``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .config import (
    ConfigError,
    as_number,
    as_str,
    check_keys,
    config_hash,
    load_config,
    normalize_config,
    unknown_message,
)
from .raw_dictionary import (
    KEY,
    TUMOR_KEY,
    RawDictionary,
    key_definition,
    load_raw_dictionary,
    reconcile,
)

PARENT = "CTC"
CHILD_ORDER = ("ABM", "COG", "MCE", "CCDI", "RO", "PHARM", "MCD", "MCP")
SEQUENCE_VARIABLES = (
    "tumorOrder", "sequenceNumberCentral", "numberOfPrimaries", "recordNumberRecode"
)
SEQUENCE_PROTECTED_REASON = "linked sequence variable"
MAX_TUMORS_PER_PATIENT = 99
DEFAULT_TOLERANCE = 0.05
_CHILD_OPTIONS = ("coverage", "rows_per_patient")
_TOP_KEYS = ("dictionaries", "tumors_per_patient", "children", "tolerance")


class LinkageError(ValueError):
    """The generated tables do not link the way the plan says."""


# --------------------------------------------------------------------------- #
# Config block
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _defaults_file() -> Dict[str, Any]:
    path = Path(__file__).parent / "data" / "nccr_linkage_defaults.json"
    return json.loads(path.read_text(encoding="utf-8"))


def default_tumors_per_patient() -> float:
    ctc = _defaults_file()["ctc"]
    return round(ctc["records"] / ctc["patients"], 4)


def default_cardinality(source: str) -> Dict[str, float]:
    """``coverage`` and ``rows_per_patient`` of a child source from the erd.dbml counts."""
    d = _defaults_file()
    counts = d["sources"][source]
    return {
        "coverage": round(counts["patients"] / d["ctc"]["patients"], 6),
        "rows_per_patient": round(counts["records"] / counts["patients"], 4),
    }


def normalize_linked(where: str, value: Any, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the ``linked:`` block and fill every default (idempotent)."""
    check_keys(where, value, _TOP_KEYS, required=("dictionaries",))
    if str(cfg.get("source", "")).upper() != PARENT:
        raise ConfigError(f"{where}: needs source: {PARENT} (the parent table of the link)")
    metadata = str(cfg.get("metadata", "")).lower()
    if metadata != "remote" and not metadata.endswith(".ttl"):
        raise ConfigError(f"{where}: needs NCCR RDF metadata (a .ttl file or 'remote')")
    out: Dict[str, Any] = {"dictionaries": as_str(f"{where}.dictionaries", value["dictionaries"])}
    tpp = value.get("tumors_per_patient")
    tpp = default_tumors_per_patient() if tpp is None else as_number(
        f"{where}.tumors_per_patient", tpp
    )
    if not 1 <= tpp <= 50:
        raise ConfigError(f"{where}.tumors_per_patient: must be between 1 and 50, got {tpp}")
    out["tumors_per_patient"] = float(tpp)

    given = value.get("children")
    if given is None:
        given = {name: None for name in CHILD_ORDER}
    check_children = f"{where}.children"
    if not isinstance(given, Mapping):
        raise ConfigError(f"{check_children}: expected a mapping of source -> options")
    for name in given:
        if name not in CHILD_ORDER:
            raise ConfigError(unknown_message(check_children, "source", name, CHILD_ORDER))
    children: Dict[str, Any] = {}
    for name in CHILD_ORDER:
        if name not in given:
            continue
        opts = given[name]
        here = f"{check_children}.{name}"
        if name == "ABM":
            if opts:
                raise ConfigError(f"{here}: ABM has one row per tumor and accepts no options")
            children[name] = {}
            continue
        opts = {} if opts is None else opts
        check_keys(here, opts, _CHILD_OPTIONS)
        entry = default_cardinality(name)
        if opts.get("coverage") is not None:
            entry["coverage"] = as_number(f"{here}.coverage", opts["coverage"], positive=True)
            if entry["coverage"] > 1:
                raise ConfigError(f"{here}.coverage: must be in (0, 1], got {opts['coverage']}")
        if opts.get("rows_per_patient") is not None:
            entry["rows_per_patient"] = as_number(
                f"{here}.rows_per_patient", opts["rows_per_patient"]
            )
            if entry["rows_per_patient"] < 1:
                raise ConfigError(
                    f"{here}.rows_per_patient: must be >= 1, got {opts['rows_per_patient']}"
                )
        children[name] = entry
    out["children"] = children
    tol = value.get("tolerance")
    out["tolerance"] = DEFAULT_TOLERANCE if tol is None else as_number(
        f"{where}.tolerance", tol, positive=True
    )
    return out


# --------------------------------------------------------------------------- #
# Planning and keys
# --------------------------------------------------------------------------- #

@dataclass
class ChildPlan:
    source: str
    coverage: float
    rows_per_patient: float
    patients: np.ndarray       # indexes of the patients that have rows
    rows_per: np.ndarray       # rows of each of those patients (same order, sum = n_rows)

    @property
    def n_rows(self) -> int:
        return int(self.rows_per.sum())


@dataclass
class Plan:
    n: int
    n_patients: int
    tumors_per_patient: float
    tumor_counts: np.ndarray   # tumors of each patient
    children: Dict[str, ChildPlan] = field(default_factory=dict)


def plan_cardinality(
    n: int, tumors_per_patient: float, children: Mapping[str, Mapping[str, float]], seed: int
) -> Plan:
    """How many patients, tumors per patient, and rows per child. Totals are exact.

    Every patient gets one tumor and the other ``n - P`` tumors are assigned uniformly. A child
    covers ``round(P * coverage)`` patients chosen without replacement; each gets one row and
    the other rows of ``round(C * rows_per_patient)`` are assigned uniformly among them.
    """
    patients = max(1, min(n, int(round(n / tumors_per_patient))))
    rng = np.random.default_rng(np.random.SeedSequence([seed, 7002]))
    counts = 1 + rng.multinomial(n - patients, np.full(patients, 1.0 / patients))
    if int(counts.max()) > MAX_TUMORS_PER_PATIENT:
        raise LinkageError(
            f"a patient would get {int(counts.max())} tumors; tumorRecordNumber allows "
            f"{MAX_TUMORS_PER_PATIENT}. Lower linked.tumors_per_patient"
        )
    plan = Plan(n=n, n_patients=patients, tumors_per_patient=tumors_per_patient,
                tumor_counts=counts.astype(np.int64))
    for index, name in enumerate(CHILD_ORDER):
        if name not in children:
            continue
        if name == "ABM":
            plan.children[name] = ChildPlan(
                name, 1.0, 1.0, np.arange(0), np.ones(n, dtype=np.int64)
            )
            continue
        opts = children[name]
        crng = np.random.default_rng(np.random.SeedSequence([seed, 7003, index]))
        covered = max(1, min(patients, int(round(patients * opts["coverage"]))))
        rows = max(covered, int(round(covered * opts["rows_per_patient"])))
        chosen = np.sort(crng.choice(patients, size=covered, replace=False))
        extra = crng.multinomial(rows - covered, np.full(covered, 1.0 / covered))
        plan.children[name] = ChildPlan(
            name, float(opts["coverage"]), float(opts["rows_per_patient"]), chosen,
            (1 + extra).astype(np.int64),
        )
    return plan


@dataclass
class Keys:
    ids: np.ndarray            # nccrId of each patient
    row_patient: np.ndarray    # patient of each parent row
    row_rank: np.ndarray       # 1-based rank of the tumor within its patient
    row_count: np.ndarray      # tumors of the patient of each parent row
    record_width: int

    def parent_ids(self) -> np.ndarray:
        return self.ids[self.row_patient]

    def record_numbers(self) -> np.ndarray:
        return np.array([f"{r:0{self.record_width}d}" for r in self.row_rank], dtype=object)


def make_keys(plan: Plan, seed: int, key_defs: Mapping[str, Mapping[str, Any]]) -> Keys:
    """``nccrId`` per patient (random hex) and the rank of each parent row within its patient."""
    id_len = int(key_defs[KEY].get("length") or 64)
    width = int(key_defs[TUMOR_KEY].get("length") or 2)
    if 10 ** width <= int(plan.tumor_counts.max()):
        raise LinkageError(f"tumorRecordNumber has {width} characters, too few for the tumors")
    rng = np.random.default_rng(np.random.SeedSequence([seed, 7001]))
    nbytes = (id_len + 1) // 2
    ids = np.array(
        [rng.bytes(nbytes).hex()[:id_len] for _ in range(plan.n_patients)], dtype=object
    )
    if len(set(ids)) != len(ids):  # 256 random bits: only a broken generator gets here
        raise LinkageError("nccrId collision")
    counts = plan.tumor_counts
    row_patient = np.repeat(np.arange(plan.n_patients), counts)
    starts = np.cumsum(counts) - counts
    row_rank = np.arange(plan.n) - np.repeat(starts, counts) + 1
    return Keys(ids, row_patient, row_rank, counts[row_patient], width)


def child_patients(child: ChildPlan) -> np.ndarray:
    """The patient of each row of a child (rows of one patient are adjacent)."""
    return np.repeat(child.patients, child.rows_per)


# --------------------------------------------------------------------------- #
# Sequence columns and assembly
# --------------------------------------------------------------------------- #

def _largest_numeric_at_most(notations: Sequence[str], k: int) -> Optional[str]:
    numeric = sorted((int(x), x) for x in notations if x.isdigit() and int(x) >= 1)
    fit = [x for v, x in numeric if v <= k]
    return fit[-1] if fit else None


def sequence_columns(
    df: pd.DataFrame, keys: Keys, value_maps: Mapping[str, Mapping[str, Any]]
) -> List[str]:
    """Overwrite tumorOrder, sequenceNumberCentral, numberOfPrimaries, recordNumberRecode.

    ``value_maps`` is variable -> {notation: the value as it appears in ``df``}. A variable
    whose needed notation is missing from its value set is left as sampled; a warning says so.
    """
    warnings: List[str] = []
    j, k = keys.row_rank, keys.row_count
    df["tumorOrder"] = [str(int(x)) for x in j]

    wanted: Dict[str, np.ndarray] = {
        "recordNumberRecode": np.where(j == 1, "01", "02").astype(object),
        "sequenceNumberCentral": np.where(k == 1, "00", np.where(j == 1, "01", "02")).astype(
            object
        ),
    }
    mapping = value_maps.get("numberOfPrimaries", {})
    by_k = {int(x): _largest_numeric_at_most(list(mapping), int(x)) for x in np.unique(k)}
    if mapping and all(v is not None for v in by_k.values()):
        wanted["numberOfPrimaries"] = np.array([by_k[int(x)] for x in k], dtype=object)
    else:
        warnings.append(
            "linked: numberOfPrimaries: no numeric notation in the value set; "
            "column left as sampled"
        )
    for name, notations in wanted.items():
        vmap = value_maps.get(name, {})
        missing = sorted({x for x in set(notations) if x not in vmap})
        if missing:
            warnings.append(
                f"linked: {name}: notation(s) {', '.join(missing)} not in the value set; "
                "column left as sampled"
            )
            continue
        df[name] = [vmap[x] for x in notations]
    return warnings


def assemble(
    df: pd.DataFrame, columns: Sequence[str], key_values: Mapping[str, Any],
    generated: Optional[Mapping[str, Any]] = None,
) -> pd.DataFrame:
    """The table in dictionary order: keys first, sampled columns, blanks for the rest."""
    df = df.reset_index(drop=True)
    generated = generated or {}
    data: Dict[str, Any] = {}
    for name in columns:
        if name in key_values:
            data[name] = key_values[name]
        elif name in generated:
            data[name] = generated[name]
        elif name in df.columns:
            data[name] = df[name].to_numpy()
        else:
            data[name] = pd.Series([None] * len(df), dtype=object)
    return pd.DataFrame(data, columns=list(columns))


def unique_ids(seed: int, n: int, length: int) -> np.ndarray:
    """``n`` distinct numeric strings of ``length`` digits (no leading zero), seeded."""
    low, high = 10 ** (length - 1), 10 ** length
    if n > high - low:
        raise LinkageError(f"cannot make {n} distinct {length}-digit ids")
    rng = np.random.default_rng(np.random.SeedSequence([seed, 7004]))
    return np.array([str(int(x) + low) for x in rng.choice(high - low, size=n, replace=False)],
                    dtype=object)


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

def _result(name: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "detail": detail}


def check_linked(
    tables: Mapping[str, pd.DataFrame], plan: Plan, expected: Mapping[str, Sequence[str]],
    tolerance: float = DEFAULT_TOLERANCE,
) -> List[Dict[str, Any]]:
    """Cross-table integrity and dictionary conformance, one result per check and source."""
    out: List[Dict[str, Any]] = []
    parent = tables[PARENT]
    for src, df in tables.items():
        cols = list(df.columns)
        want = list(expected[src])
        out.append(_result(
            f"{src}: dictionary columns present, in order", cols == want,
            f"{len(cols)} columns" if cols == want else
            f"missing {sorted(set(want) - set(cols))}, extra {sorted(set(cols) - set(want))}, "
            f"first columns {cols[:2]}",
        ))
        firsts = [KEY, TUMOR_KEY] if src in (PARENT, "ABM") else [KEY]
        out.append(_result(f"{src}: key columns first", cols[: len(firsts)] == firsts,
                           f"first columns {cols[: len(firsts)]}"))
    pairs = list(zip(parent[KEY], parent[TUMOR_KEY]))
    out.append(_result(f"{PARENT}: (nccrId, tumorRecordNumber) unique",
                       len(set(pairs)) == len(pairs), f"{len(pairs)} rows"))
    ids = set(parent[KEY])
    for src, df in tables.items():
        if src == PARENT:
            continue
        orphans = int((~df[KEY].isin(ids)).sum())
        out.append(_result(f"{src}: every nccrId exists in {PARENT}", orphans == 0,
                           f"{len(df)} rows, {orphans} orphan(s)"))
    if "ABM" in tables:
        abm = list(zip(tables["ABM"][KEY], tables["ABM"][TUMOR_KEY]))
        out.append(_result("ABM: (nccrId, tumorRecordNumber) pairs equal CTC's",
                           abm == pairs, f"{len(abm)} rows, row for row"))
    patients = plan.n_patients
    for src, child in plan.children.items():
        if src == "ABM" or src not in tables:
            continue
        df = tables[src]
        covered = int(df[KEY].nunique())
        cov = covered / patients
        cov_ok = abs(cov - child.coverage) <= tolerance * child.coverage + 1.0 / patients
        out.append(_result(f"{src}: coverage within tolerance", cov_ok,
                           f"configured {child.coverage:.6g}, achieved {cov:.6g} "
                           f"({covered} of {patients} patients)"))
        rpp = len(df) / covered if covered else 0.0
        rpp_ok = covered > 0 and (
            abs(rpp - child.rows_per_patient) <= tolerance * child.rows_per_patient + 1.0 / covered
        )
        out.append(_result(f"{src}: rows per patient within tolerance", rpp_ok,
                           f"configured {child.rows_per_patient:.6g}, achieved {rpp:.6g}"))
    return out


def verify_linked(
    tables: Mapping[str, pd.DataFrame], plan: Plan, expected: Mapping[str, Sequence[str]],
    tolerance: float = DEFAULT_TOLERANCE,
) -> List[Dict[str, Any]]:
    """``check_linked``, raising ``LinkageError`` when any check fails."""
    results = check_linked(tables, plan, expected, tolerance)
    failed = [r for r in results if not r["passed"]]
    if failed:
        raise LinkageError(
            "linked tables failed " + str(len(failed)) + " check(s): "
            + "; ".join(f"{r['check']} ({r['detail']})" for r in failed)
        )
    return results


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def _blank_reason(
    name: str, skipped: Mapping[str, str], raw_only: Sequence[str], nullified: Sequence[str],
    in_dictionary: bool,
) -> str:
    if name in skipped:
        return skipped[name]
    if name in raw_only:
        return "not_in_rdf_metadata"
    if name in nullified:
        return "no_frequency_nullified"
    return "no_value_set" if not in_dictionary else "suppressed"


def _value_maps(graph: Any, dictionary: Any) -> Dict[str, Dict[str, Any]]:
    """Notation -> the value as it appears in the CTC table (label or code mode)."""
    from .nccr_rdf import value_notations

    maps: Dict[str, Dict[str, Any]] = {}
    for var in SEQUENCE_VARIABLES:
        notations = value_notations(graph, PARENT, var)
        if not notations:
            continue
        labels = set(notations.values())
        var_marginal = dictionary.variables.get(var)
        cats = set(var_marginal.categories) if var_marginal is not None else set()
        code_mode = bool(cats) and not (cats & labels)
        maps[var] = {nt: (nt if code_mode else lab) for nt, lab in notations.items()}
    return maps


def _table_info(
    src: str, bundle: Mapping[str, Any], rec: Any, df: pd.DataFrame, key_cols: Sequence[str],
    generated: Sequence[str], raw: RawDictionary, plan: Plan, rows: int, warnings: List[str],
) -> Dict[str, Any]:
    d = bundle["dictionary"]
    skipped = getattr(d, "skipped", {}) or {}
    nullified = list(bundle.get("nullified", []))
    special = set(key_cols) | set(generated)
    blank: Dict[str, Any] = {}
    for name in df.columns:
        if name in special or len(df) == 0 or not df[name].isna().all():
            continue
        col = raw.get(name)
        blank[name] = {
            "reason": _blank_reason(name, skipped, rec.raw_only, nullified,
                                    name in d.variables),
            "semantic_type": col.semantic_type if col else None,
            "field_length": col.field_length if col else None,
        }
    info: Dict[str, Any] = {
        "role": "parent" if src == PARENT else "child",
        "parent": None if src == PARENT else PARENT,
        "key_columns": list(key_cols),
        "dictionary_columns": len(df.columns),
        "dictionary_file": raw.path,
        "reconciliation": {"raw_only": rec.raw_only, "rdf_only": rec.ttl_only},
        "generated_columns": list(generated),
        "blank_columns": blank,
        "rows": int(len(df)),
        "warnings": list(warnings),
    }
    if src == PARENT:
        info["planned"] = {"tumors": plan.n, "patients": plan.n_patients,
                           "tumors_per_patient": plan.tumors_per_patient}
        info["achieved"] = {"tumors": int(len(df)), "patients": int(df[KEY].nunique())}
    else:
        child = plan.children[src]
        covered = int(df[KEY].nunique())
        info["planned"] = {"coverage": child.coverage, "rows_per_patient": child.rows_per_patient,
                           "rows": rows}
        info["achieved"] = {
            "rows": int(len(df)), "patients_with_rows": covered,
            "coverage": covered / plan.n_patients,
            "rows_per_patient": (len(df) / covered) if covered else 0.0,
        }
    return info


def run_linked(recipe: Union[Mapping[str, Any], str, Path]) -> Dict[str, Any]:
    """Generate the parent and every configured child, link them, and check the links."""
    from .nccr_rdf import load_graph, source_columns
    from .recipe import run_recipe
    from .source_policy import LINKED_TABLE_LABEL, LINKED_TABLE_TYPE, linked_statement

    raw = load_config(recipe)
    cfg = normalize_config(raw)
    block = cfg.get("linked")
    if block is None:
        raise ConfigError("linked: this config has no linked block; use run_recipe")
    seed = cfg["seed"]
    if seed is None:  # the run is still reproducible from the manifest, which records the seed
        seed = int(np.random.SeedSequence().entropy % (2 ** 31))
    metadata = cfg["metadata"]
    sources = None if metadata.lower() == "remote" else [metadata]
    children = block["children"]
    wanted = (PARENT,) + tuple(c for c in CHILD_ORDER if c in children)
    raws = {s: load_raw_dictionary(block["dictionaries"], s) for s in wanted}
    graph = load_graph(sources)
    recs = {s: reconcile(raws[s], source_columns(graph, s)) for s in wanted}
    key_defs = {
        KEY: key_definition(raws[PARENT], KEY), TUMOR_KEY: key_definition(raws[PARENT], TUMOR_KEY)
    }

    parent_raw = {k: v for k, v in raw.items() if k != "linked"}
    parent_raw["seed"] = seed
    protected = {v: SEQUENCE_PROTECTED_REASON for v in SEQUENCE_VARIABLES}
    parent = run_recipe(parent_raw, extra_protected=protected)

    plan = plan_cardinality(cfg["n"], block["tumors_per_patient"], children, seed)
    keys = make_keys(plan, seed, key_defs)
    pdf = parent["data"].copy()
    warnings = sequence_columns(pdf, keys, _value_maps(graph, parent["dictionary"]))
    parent_keys = {KEY: keys.parent_ids(), TUMOR_KEY: keys.record_numbers()}
    tables: Dict[str, pd.DataFrame] = {
        PARENT: assemble(pdf, recs[PARENT].columns, parent_keys)
    }
    bundles: Dict[str, Dict[str, Any]] = {PARENT: dict(parent)}
    infos: Dict[str, Dict[str, Any]] = {}
    key_cols = {PARENT: [KEY, TUMOR_KEY]}
    gen_cols = {PARENT: [KEY, TUMOR_KEY] + [v for v in SEQUENCE_VARIABLES if v in tables[PARENT]]}
    row_warnings: Dict[str, List[str]] = {PARENT: list(warnings)}
    planned_rows = {PARENT: plan.n}

    for index, src in enumerate(CHILD_ORDER, start=1):
        if src not in children:
            continue
        child = plan.children[src]
        child_cfg: Dict[str, Any] = {
            "metadata": metadata, "source": src, "n": child.n_rows, "seed": seed + index,
            "profile": "marginals_only",
        }
        for opt in ("value_mode", "no_frequency"):
            if raw.get(opt) is not None:
                child_cfg[opt] = raw[opt]
        cb = run_recipe(child_cfg)
        if src == "ABM":
            ckeys = dict(parent_keys)
        else:
            patient = child_patients(child)
            ckeys = {KEY: keys.ids[patient]}
        generated: Dict[str, Any] = {}
        if src == "RO" and "recordId" in recs[src].columns:
            width = raws[src].get("recordId").field_length or 8
            generated["recordId"] = unique_ids(seed + index, len(cb["data"]), width)
        tables[src] = assemble(cb["data"], recs[src].columns, ckeys, generated)
        bundles[src] = dict(cb)
        key_cols[src] = list(ckeys)
        gen_cols[src] = list(ckeys) + list(generated)
        row_warnings[src] = []
        planned_rows[src] = child.n_rows

    expected = {s: recs[s].columns for s in tables}
    checks = verify_linked(tables, plan, expected, block["tolerance"])

    for src, df in tables.items():
        info = _table_info(src, bundles[src], recs[src], df, key_cols[src], gen_cols[src],
                           raws[src], plan, planned_rows[src], row_warnings[src])
        infos[src] = info
        b = bundles[src]
        b["data"] = df
        b["table_type"] = LINKED_TABLE_TYPE
        b["table_label"] = LINKED_TABLE_LABEL
        b["linkage"] = linked_statement(src, PARENT)
        b["linked"] = info
        b["warnings"] = list(b["warnings"]) + row_warnings[src]
    return {
        "tables": bundles, "order": list(tables), "plan": plan, "keys": keys,
        "config": cfg, "config_sha256": config_hash(cfg), "seed": seed, "checks": checks,
        "info": infos, "warnings": warnings,
    }


def write_linked(
    bundle: Mapping[str, Any], out_dir: Union[str, Path], fmt: str = "csv",
    archive: Optional[str] = None, keep_csv: Optional[bool] = None,
) -> Path:
    """One folder per source (``<SRC>/``) plus ``linked_manifest.json`` in ``out_dir``."""
    from . import __version__
    from .recipe import write_run

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for src in bundle["order"]:
        write_run(bundle["tables"][src], out / src, fmt=fmt, archive=archive, keep_csv=keep_csv)
    cfg = bundle["config"]
    manifest = {
        "tool": "synthpediatric",
        "version": __version__,
        "table_type": "linked_cohort",
        "config": cfg,
        "config_sha256": bundle["config_sha256"],
        "seed": bundle["seed"],
        "seeds": {"parent": bundle["seed"], **{
            s: bundle["seed"] + i for i, s in enumerate(CHILD_ORDER, start=1)
            if s in bundle["order"]
        }},
        "keys": {"primary": KEY, "tumor": TUMOR_KEY, "parent": PARENT},
        "tables": {
            s: {"folder": s, **{k: v for k, v in bundle["info"][s].items()
                                 if k in ("rows", "dictionary_columns", "planned", "achieved")}}
            for s in bundle["order"]
        },
        "checks": bundle["checks"],
        "checks_passed": all(c["passed"] for c in bundle["checks"]),
        "reproduction": "The same config and seed give the same tables. Without the linked "
                        "block the config produces the unlinked single-source CTC table.",
    }
    (out / "linked_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return out
