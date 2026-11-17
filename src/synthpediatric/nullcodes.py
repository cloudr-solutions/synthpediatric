"""Null codes and the not-applicable fraction.

Two things live here.

1. A classifier that says, for every permissible value of every NCCR variable, whether the
   value is a real answer or a null-type code. The NCCR metadata has no null flag: a
   permissible value is a code and a description, and the description carries the meaning
   ("Not applicable: Information not collected for this case", "No prostatectomy done").
   The classifier reads the description (the code is only a tiebreaker) with an ordered,
   reviewable list of ``RULES`` and a file of per-code ``overrides`` a person can edit.
   ``build_map`` / ``synthpediatric nullcodes`` write the result as a data file.

2. The not-applicable fraction. A variable that covers only a sub-population (Gleason score
   exists only for prostate cancers) publishes counts that cover a small part of its
   source's records. Normalizing those counts to 1 gives every row a value. The fraction
   leaves the uncovered share of rows with the variable's own not-applicable code, or
   blank when it has none. ``plan_na_fraction`` decides, ``NaPlan.apply`` does it.

Kinds
-----
``not_applicable``  the question does not apply to this record (X8, "Not applicable ...").
``unknown``         the answer exists but is not known or not documented (X9, 9, 99).
``no_data``         the source has no data for the record (missing, not available, not coded).
``not_performed``   a procedure or test was not done (X7, "No prostatectomy done").
``real``            an actual answer. Everything the rules do not recognize is real.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

KIND_NOT_APPLICABLE = "not_applicable"
KIND_UNKNOWN = "unknown"
KIND_NO_DATA = "no_data"
KIND_NOT_PERFORMED = "not_performed"
KIND_REAL = "real"
KINDS = (
    KIND_NOT_APPLICABLE, KIND_UNKNOWN, KIND_NO_DATA, KIND_NOT_PERFORMED, KIND_REAL,
)
NULL_KINDS = KINDS[:-1]

KIND_HELP = {
    KIND_NOT_APPLICABLE: "the question does not apply to this record (X8, 'Not applicable ...')",
    KIND_UNKNOWN: "the answer exists but is not known or not documented (X9, 9, 99, 'Unknown')",
    KIND_NO_DATA: "the source holds no data for the record (missing, not available, not coded)",
    KIND_NOT_PERFORMED: "a procedure or test was not done (X7, 'No prostatectomy done')",
    KIND_REAL: "an actual answer; every value no rule recognizes",
}

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_OVERRIDES_PATH = DATA_DIR / "null_code_overrides.json"
DEFAULT_MAP_PATH = DATA_DIR / "null_code_map.json"
MAP_SCHEMA = 1

# Counts below this are omitted from the metadata, so each omitted cell hides at most 15.
SUPPRESSION_THRESHOLD = 16
MAX_SUPPRESSED_PER_CODE = SUPPRESSION_THRESHOLD - 1


# --------------------------------------------------------------------------- #
# Classifier
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Rule:
    """One classification rule. The first rule whose pattern matches the description wins."""

    id: str
    kind: str
    pattern: str
    borderline: bool = False
    note: str = ""
    raw: bool = False  # match the description as written (case kept) instead of lower-cased

    def compiled(self) -> "re.Pattern[str]":
        return re.compile(self.pattern)


# Matched against the description, lower-cased, whitespace collapsed. Order matters.
RULES: Tuple[Rule, ...] = (
    # --- false positives: look like a null code, are real answers -------------------
    Rule("real_iccc_group", KIND_REAL, r"^(?:[IVX]{2,}|[IVX][a-f]?)[a-f]?\d*(?:\.\d+)*\.?\s",
         raw=True,
         note="ICCC group label such as 'Ie Unspecified and other specified leukemias' or "
              "'XII OTHER AND UNSPECIFIED MALIGNANT NEOPLASMS': a diagnostic group, not a null"),
    Rule("real_not_classified", KIND_REAL, r"^not classified by (seer|iccc)",
         note="'Not classified by SEER or in situ' is a group of the ICCC recode"),
    Rule("real_partial_gleason", KIND_REAL, r"^primary pattern \d, secondary pattern unknown",
         note="one Gleason pattern is known: a partial answer"),
    # --- mixed descriptions (borderline) ---------------------------------------------
    Rule("unknown_gleason_both", KIND_UNKNOWN,
         r"^primary pattern unknown, secondary pattern unknown", True,
         note="both Gleason patterns unknown"),
    Rule("unknown_or_na", KIND_UNKNOWN, r"unknown.*not applicable|not applicable.*unknown", True,
         note="description names both; unknown wins so it is never used as the "
              "not-applicable fill"),
    Rule("na_or_in_text", KIND_NOT_APPLICABLE, r"\bor not applicable\b", True,
         note="'... or Not Applicable for this Site' at the end of a longer description"),
    # --- not applicable --------------------------------------------------------------
    Rule("na_lead", KIND_NOT_APPLICABLE, r"^not applicable",
         note="description starts with 'Not applicable' (X8, 8, 88, Blank, ...)"),
    Rule("na_level", KIND_NOT_APPLICABLE, r"does not include this level",
         note="8888888: the classification has no such level"),
    Rule("na_period", KIND_NOT_APPLICABLE, r"^diagnosed (after|before|prior)", True,
         note="'Diagnosed prior to 2023': the item did not exist for the diagnosis year"),
    Rule("na_not_paired", KIND_NOT_APPLICABLE, r"^not a paired site", True,
         note="laterality does not apply to an unpaired site"),
    # --- no data ---------------------------------------------------------------------
    Rule("no_data_not_provided", KIND_NO_DATA, r"\bnot provided$|^patient not found", True,
         note="'Enrollment Status not Provided', 'Patient not Found at Time of Linkage'"),
    Rule("no_data_lead", KIND_NO_DATA,
         r"^(no data|not available|recode not available|not coded|not reported|missing\b|"
         r"unable to|not calculated|not known due to missing)",
         note="missing, not available, not coded, not calculated"),
    # --- unknown ---------------------------------------------------------------------
    Rule("unknown_lead", KIND_UNKNOWN,
         r"^(it is )?unknown\b|^unspecified or unknown|^not documented|^not stated|"
         r"^not assessed|^no information|^not tested for [^;]*; unknown",
         note="description starts with unknown / not documented / not stated"),
    Rule("unknown_not_classified", KIND_UNKNOWN,
         r"^not yet classified|results not in chart", True,
         note="'Not Yet Classified by NAACCR ...', 'Test ordered, results not in chart'"),
    Rule("unknown_race", KIND_UNKNOWN, r"^non-hispanic unknown race$", True,
         note="a race category that means unknown race"),
    Rule("unknown_trail", KIND_UNKNOWN, r"[/;, ]unknown$|^[^;]*\bremoved unknown$", True,
         note="description ends with unknown ('None/Unknown', 'Borderline/Unknown')"),
    Rule("unknown_if", KIND_UNKNOWN,
         r"\bit is unknown (if|whether)\b|recommended,? (but )?(it is )?unknown if",
         note="'recommended, but it is unknown if it was administered'"),
    Rule("unknown_not_documented", KIND_UNKNOWN, r"\bnot documented in medical record\b", True,
         note="'not documented' inside a longer description"),
    Rule("unknown_no_information", KIND_UNKNOWN, r"\bno information\b", True,
         note="'no information concerning laterality'"),
    # --- not performed ---------------------------------------------------------------
    Rule("not_performed_no", KIND_NOT_PERFORMED, r"^no\b[^;,.]*\b(performed|done)\b",
         note="X7: 'No prostatectomy done', 'No needle core biopsy/TURP performed'"),
    Rule("not_performed_was", KIND_NOT_PERFORMED, r"\bwas not (performed|administered)\b", True,
         note="treatment not given (often a clinical answer; borderline)"),
    Rule("not_performed_lead", KIND_NOT_PERFORMED, r"^not (tested|performed|done)\b", True,
         note="description starts with not tested / not performed"),
)
_COMPILED = [(r, r.compiled()) for r in RULES]

# A deliberately loose scan, used only to list the values the rules decided are real
# although a keyword suggested otherwise (the false positives report).
LOOSE_KEYWORDS = re.compile(
    r"not applicable|unknown|not documented|not performed|no data|missing|not available|"
    r"not coded|unspecified|blank|not collected|not stated|not recorded|not classified|refused|"
    r"not done|no information|\bn/a\b|not reported|not tested|not assessed|not administered",
    re.IGNORECASE,
)


def normalize_description(text: Optional[str]) -> str:
    """Lower-cased description with runs of whitespace (and line breaks) collapsed."""
    return " ".join((text or "").split())


@dataclass(frozen=True)
class Classification:
    kind: str
    rule: str  # rule id, 'override', or 'default'
    borderline: bool = False
    reason: str = ""


def _override_keys(source: Optional[str], variable: Optional[str], code: str) -> List[str]:
    s, v = source or "*", variable or "*"
    return [f"{s}.{v}.{code}", f"{s}.*.{code}", f"*.{v}.{code}", f"*.*.{code}"]


def load_overrides(path: Union[str, Path, None] = None) -> Dict[str, Dict[str, Any]]:
    """Read an overrides file: ``{"overrides": {"CTC.psaLabValueRecode.X9": {kind, reason}}}``.

    A key is ``SOURCE.variable.code``; ``*`` may stand for the source or the variable.
    The most specific key wins. The kind must be one of ``KINDS``.
    """
    p = Path(path) if path else DEFAULT_OVERRIDES_PATH
    if not p.is_file():
        raise ValueError(f"null-code overrides file not found: {p}")
    spec = json.loads(p.read_text(encoding="utf-8"))
    table = spec.get("overrides", spec) if isinstance(spec, Mapping) else None
    if not isinstance(table, Mapping):
        raise ValueError(f"{p}: expected a mapping with an 'overrides' table")
    out: Dict[str, Dict[str, Any]] = {}
    for key, entry in table.items():
        if key.startswith("_"):
            continue
        kind = entry if isinstance(entry, str) else (entry or {}).get("kind")
        if kind not in KINDS:
            raise ValueError(f"{p}: override '{key}' has kind {kind!r}; valid kinds: {KINDS}")
        if key.count(".") < 2:
            raise ValueError(f"{p}: override key '{key}' must look like SOURCE.variable.code")
        reason = "" if isinstance(entry, str) else str(entry.get("reason", ""))
        out[key] = {"kind": kind, "reason": reason}
    return out


def merge_overrides(*tables: Optional[Mapping[str, Mapping[str, Any]]]) -> Dict[str, Any]:
    """Later tables win over earlier ones."""
    merged: Dict[str, Any] = {}
    for table in tables:
        if table:
            merged.update(table)
    return merged


def classify(
    code: Optional[str],
    description: Optional[str],
    *,
    source: Optional[str] = None,
    variable: Optional[str] = None,
    overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Classification:
    """Classify one permissible value from its description (``code`` for overrides)."""
    code = "" if code is None else str(code)
    if overrides:
        for key in _override_keys(source, variable, code):
            if key in overrides:
                o = overrides[key]
                return Classification(o["kind"], "override", True, o.get("reason", ""))
    original = normalize_description(description)
    text = original.lower()
    if not text:
        return Classification(KIND_REAL, "default")
    for rule, rx in _COMPILED:
        if rx.search(original if rule.raw else text):
            return Classification(rule.kind, rule.id, rule.borderline, rule.note)
    return Classification(KIND_REAL, "default")


def is_false_positive(description: Optional[str], result: Classification) -> bool:
    """A value a keyword scan flags but the rules keep real."""
    return result.kind == KIND_REAL and bool(LOOSE_KEYWORDS.search(description or ""))


# --------------------------------------------------------------------------- #
# The map
# --------------------------------------------------------------------------- #

_CODES_QUERY = """
PREFIX nccr: <https://nccrdataplatform.ccdi.cancer.gov/vocab#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?sid ?col ?notation ?plabel ?desc ?rc WHERE {
    ?var a nccr:Variable ;
         nccr:sourceColumn ?col ;
         nccr:belongsToSource ?ds ;
         nccr:hasValueSet ?vs .
    ?ds nccr:sourceId ?sid .
    ?cv skos:inScheme ?vs .
    OPTIONAL { ?cv nccr:recordCount ?rc }
    OPTIONAL { ?cv skos:prefLabel ?plabel }
    OPTIONAL { ?cv skos:notation ?notation }
    OPTIONAL { ?cv nccr:codeDescription ?desc }
}
"""


def collect_codes(graph: Any, source: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every permissible value of the metadata: source, variable, code, description, count."""
    want = source.upper() if source else None
    out: List[Dict[str, Any]] = []
    for row in graph.query(_CODES_QUERY):
        sid = str(row.sid)
        if want and sid.upper() != want:
            continue
        label = str(row.plabel) if row.plabel is not None else None
        notation = str(row.notation) if row.notation is not None else None
        desc = str(row.desc) if row.desc is not None else (label or notation or "")
        out.append({
            "source": sid, "variable": str(row.col),
            "code": notation if notation is not None else (label or ""),
            "label": label, "description": normalize_description(desc),
            "count": int(row.rc) if row.rc is not None else None,
        })
    out.sort(key=lambda r: (r["source"], r["variable"], r["code"]))
    return out


def build_map(
    codes: Sequence[Mapping[str, Any]],
    overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
    generated_from: str = "",
) -> Dict[str, Any]:
    """Classify ``codes`` (from ``collect_codes``) into the map data structure.

    ``sources[S][variable]`` holds ``n_values``, ``n_real`` and ``null_codes`` (code ->
    kind, description, rule, borderline, count). ``counts[S]`` has the number of values per
    kind. ``false_positives`` lists the values a keyword scan flags that stay real.
    """
    overrides = overrides or {}
    sources: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, Dict[str, int]] = {}
    false_pos: List[Dict[str, Any]] = []
    for c in codes:
        res = classify(
            c["code"], c["description"], source=c["source"], variable=c["variable"],
            overrides=overrides,
        )
        var = sources.setdefault(c["source"], {}).setdefault(
            c["variable"], {"n_values": 0, "n_real": 0, "null_codes": {}}
        )
        var["n_values"] += 1
        tally = counts.setdefault(c["source"], {k: 0 for k in KINDS})
        tally[res.kind] += 1
        if res.kind == KIND_REAL:
            var["n_real"] += 1
            if is_false_positive(c["description"], res):
                false_pos.append({
                    "source": c["source"], "variable": c["variable"], "code": c["code"],
                    "description": c["description"],
                })
        else:
            entry = {
                "kind": res.kind, "description": c["description"], "rule": res.rule,
                "borderline": res.borderline, "count": c["count"],
            }
            var["null_codes"][c["code"]] = entry
    total = {k: sum(t[k] for t in counts.values()) for k in KINDS}
    n_null = sum(total[k] for k in NULL_KINDS)
    return {
        "schema": MAP_SCHEMA,
        "generated_from": generated_from,
        "kinds": KIND_HELP,
        "rules": [
            {"id": r.id, "kind": r.kind, "pattern": r.pattern, "borderline": r.borderline,
             "case_sensitive": r.raw, "note": r.note}
            for r in RULES
        ],
        "n_overrides": len(overrides),
        "totals": {"values": sum(total.values()), "null_type": n_null, **total},
        "counts": {s: counts[s] for s in sorted(counts)},
        "sources": {
            s: {v: sources[s][v] for v in sorted(sources[s])} for s in sorted(sources)
        },
        "false_positives": false_pos,
    }


def write_map(data: Mapping[str, Any], path: Union[str, Path]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, sort_keys=False, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def load_map(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """The shipped null-code map (or the map at ``path``)."""
    p = Path(path) if path else DEFAULT_MAP_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def summary_markdown(data: Mapping[str, Any]) -> str:
    """A human-readable summary of a map: counts per source and kind, borderline, excluded."""
    lines: List[str] = ["# Null-code map: summary", ""]
    if data.get("generated_from"):
        lines += [f"Built from: {data['generated_from']}", ""]
    t = data["totals"]
    lines += [
        f"{t['values']:,} permissible values, {t['null_type']:,} classified as null-type "
        f"(not_applicable {t[KIND_NOT_APPLICABLE]:,}, unknown {t[KIND_UNKNOWN]:,}, "
        f"no_data {t[KIND_NO_DATA]:,}, not_performed {t[KIND_NOT_PERFORMED]:,}), "
        f"{t[KIND_REAL]:,} real. {data.get('n_overrides', 0)} per-code overrides applied.",
        "",
        "## Values per source and kind", "",
        "| source | values | not_applicable | unknown | no_data | not_performed | real |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s, c in data["counts"].items():
        lines.append(
            f"| {s} | {sum(c.values()):,} | {c[KIND_NOT_APPLICABLE]:,} | {c[KIND_UNKNOWN]:,} | "
            f"{c[KIND_NO_DATA]:,} | {c[KIND_NOT_PERFORMED]:,} | {c[KIND_REAL]:,} |"
        )
    lines += [
        f"| **all** | {t['values']:,} | {t[KIND_NOT_APPLICABLE]:,} | {t[KIND_UNKNOWN]:,} | "
        f"{t[KIND_NO_DATA]:,} | {t[KIND_NOT_PERFORMED]:,} | {t[KIND_REAL]:,} |",
        "",
    ]
    # Distinct (kind, description) groups, so 360 monthly flags are one line.
    border: Dict[Tuple[str, str, str], List[str]] = {}
    for s, variables in data["sources"].items():
        for v, spec in variables.items():
            for code, e in spec["null_codes"].items():
                if e["borderline"]:
                    border.setdefault((e["kind"], e["rule"], e["description"][:140]), []).append(
                        f"{s}.{v}.{code}"
                    )
    lines += [
        f"## Borderline classifications for review ({len(border)} distinct descriptions)", "",
        "| kind | rule | description | values | examples |", "|---|---|---|---:|---|",
    ]
    for (kind, rule, desc), where in sorted(border.items()):
        shown = ", ".join(where[:2]) + (", ..." if len(where) > 2 else "")
        lines.append(f"| {kind} | {rule} | {desc.replace('|', '/')} | {len(where)} | {shown} |")
    fps = data.get("false_positives", [])
    groups: Dict[str, List[str]] = {}
    for f in fps:
        groups.setdefault(f["description"][:140], []).append(
            f"{f['source']}.{f['variable']}.{f['code']}"
        )
    lines += [
        "", f"## False positives excluded ({len(fps)} values, {len(groups)} distinct "
        "descriptions)", "",
        "A keyword scan (unknown, unspecified, missing, not classified, refused, ...) flags "
        "these, the rules keep them real.", "",
        "| description | values | example |", "|---|---:|---|",
    ]
    for desc, where in sorted(groups.items()):
        lines.append(f"| {desc.replace('|', '/')} | {len(where)} | {where[0]} |")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Per-variable information the loader attaches to a VariableMarginal
# --------------------------------------------------------------------------- #

def variable_na_info(
    values: Mapping[Any, Optional[float]],
    meta: Mapping[Any, Sequence[Tuple[str, str]]],
    *,
    source: str,
    variable: str,
    total: Optional[int],
    overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """What the not-applicable fraction needs to know about one variable.

    ``values`` maps each value (label or code, as generated) to its count or None; ``meta``
    maps the value to its ``(code, description)`` pairs. Several codes can share a label;
    the value keeps a null kind only when every code behind it agrees.
    """
    kinds: Dict[Any, str] = {}
    descs: Dict[Any, str] = {}
    for value in values:
        found = [
            classify(code, desc, source=source, variable=variable, overrides=overrides)
            for code, desc in meta.get(value, [])
        ] or [Classification(KIND_REAL, "default")]
        agree = {f.kind for f in found}
        kinds[value] = found[0].kind if len(agree) == 1 else KIND_REAL
        descs[value] = (meta.get(value) or [("", "")])[0][1]
    counted = {v: c for v, c in values.items() if c is not None}
    return {
        "source": source,
        "total": total,
        "covered": float(sum(counted.values())),
        "n_counted": len(counted),
        "n_uncounted": len(values) - len(counted),
        "kinds": kinds,
        "descriptions": descs,
        "counted": {v: float(c) for v, c in counted.items()},
    }


# --------------------------------------------------------------------------- #
# The not-applicable fraction
# --------------------------------------------------------------------------- #

NA_MODES = ("on", "off")
NA_VARIABLE_CHOICES = ("on", "off", "auto")
DEFAULT_MIN_SHARE = 0.005
GENERIC_NA_MODE = "on"  # NCCR metadata sources; a JSON dictionary has no policy and stays off
NA_RULE_ORDER = 7  # mixed into the seed so the mask has its own random stream

NA_REASONS = {
    "applied": "the uncovered share was generated as not applicable",
    "suppression_only": "the gap is no larger than what suppressed cells (counts below 16) "
                        "can hide",
    "below_min_share": "the uncovered share is below min_share",
    "set_by_rule": "a marginals, overrides, cohort or oversample rule changed the variable's "
                   "distribution, so the published counts no longer describe it",
    "rule_target": "the variable is a target of the conditional or joints rule",
    "off_by_config": "switched off for this variable in the config",
    "no_total": "the dictionary has no record total",
}


def _pick_na_code(info: Mapping[str, Any]) -> Optional[Any]:
    """The not-applicable code with no published count, best first; None when there is none."""
    na = [v for v, k in info["kinds"].items() if k == KIND_NOT_APPLICABLE]
    cands = [v for v in na if v not in info["counted"]]
    if not cands:
        # Every not-applicable code carries a count. Use the biggest one: its published
        # share is part of the covered share, so the uncovered share is added to it once.
        return max(na, key=lambda v: (info["counted"][v], str(v))) if na else None

    def rank(v: Any) -> Tuple[int, int, str]:
        d = normalize_description(info["descriptions"].get(v, "")).lower()
        return (0 if d.startswith("not applicable") else 1, len(d), str(v))

    return sorted(cands, key=rank)[0]


def _same_distribution(a: Any, b: Any) -> bool:
    if list(a.categories) != list(b.categories):
        return False
    return bool(np.allclose(a.probabilities, b.probabilities, rtol=1e-9, atol=1e-12))


@dataclass
class NaPlan:
    """The decision for every variable with a gap, and (after ``apply``) what was done."""

    settings: Dict[str, Any]
    variables: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    seed: Optional[int] = None
    n_rows: int = 0
    masks: Dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    @property
    def applied(self) -> List[str]:
        return [v for v, e in self.variables.items() if e["status"] == "applied"]

    @property
    def blank_variables(self) -> List[str]:
        return [v for v in self.applied if self.variables[v]["blank"]]

    def apply(self, df: Any) -> Any:
        """Set the share of rows of each applied variable to its code (or blank), in place.

        The rows come from the plan's own random stream, so the sampling of the counted
        values and the stream the consistency rules draw from are not disturbed.
        """
        n = len(df)
        self.n_rows = n
        if not self.applied or n == 0:
            return df
        if self.seed is not None:
            ss = np.random.SeedSequence([int(self.seed) % (2 ** 63), NA_RULE_ORDER])
        else:
            ss = np.random.SeedSequence()
        rng = np.random.default_rng(ss)
        for name in self.applied:
            e = self.variables[name]
            rows = int(round(e["target_share"] * n))
            rows = max(0, min(rows, n))
            chosen = rng.choice(n, size=rows, replace=False) if rows else np.empty(0, dtype=int)
            mask = np.zeros(n, dtype=bool)
            mask[chosen] = True
            col = df[name].to_numpy(dtype=object, copy=True)
            col[mask] = None if e["blank"] else e["code"]
            df[name] = col
            self.masks[name] = mask
            e["generated_rows"] = rows
            e["generated_share"] = rows / n
            if not e["blank"]:
                # rows that already held the code before the fraction was set count too
                e["code_share_generated"] = float(np.mean(col == e["code"]))
        return df

    def report(self) -> Dict[str, Any]:
        """The manifest entry: settings, one record per variable with a gap, totals."""
        applied = self.applied
        return {
            "settings": self.settings,
            "n_rows": self.n_rows,
            "n_applied": len(applied),
            "n_blank": len(self.blank_variables),
            "variables": self.variables,
        }


class NaThenRules:
    """Wraps a RuleSet: the fraction is applied to the sampled table, then rules repair it."""

    def __init__(self, plan: NaPlan, inner: Any = None) -> None:
        self.plan = plan
        self.inner = inner

    @property
    def constraints(self) -> List[Any]:
        return list(getattr(self.inner, "constraints", []))

    def apply(self, df: Any, rng: Any) -> Tuple[Any, Dict[str, int]]:
        self.plan.apply(df)
        if self.inner is None:
            return df, {}
        return self.inner.apply(df, rng)


def plan_na_fraction(
    base: Any,
    final: Any,
    *,
    mode: str,
    mode_supplied_by: str,
    min_share: float = DEFAULT_MIN_SHARE,
    variables: Optional[Mapping[str, str]] = None,
    protected: Optional[Mapping[str, str]] = None,
    seed: Optional[int] = None,
) -> NaPlan:
    """Decide, for every variable whose counts do not cover its source, what to do.

    ``base`` is the dictionary as loaded (it carries each variable's ``na_info``), ``final``
    the dictionary after the dictionary rules ran. ``variables`` holds the per-variable
    settings (``on`` / ``off`` / ``auto``); ``protected`` maps variables owned by a rule
    (conditional, joints) to the reason.

    The rule for ``auto``: the gap is the source's records minus the variable's summed
    counts. Suppression of cells below 16 can hide at most 15 records per uncounted code,
    so a gap no larger than that is suppression and not sub-population. A larger gap is
    material when its share of the records is at least ``min_share``. ``on`` skips both
    tests, ``off`` skips the variable.
    """
    variables = dict(variables or {})
    protected = dict(protected or {})
    settings = {
        "mode": mode, "mode_supplied_by": mode_supplied_by, "min_share": min_share,
        "variables": variables,
        "rule": "material when gap > 15 x uncounted codes and uncovered share >= min_share",
    }
    plan = NaPlan(settings=settings, seed=seed)
    total = getattr(base, "n_records", None)
    for name, vm in base.variables.items():
        info = getattr(vm, "na_info", None)
        if not info or not info["counted"]:
            continue  # no published counts: the no_frequency setting owns this variable
        setting = variables.get(name, "auto")
        supplied = "config" if name in variables else mode_supplied_by
        if setting == "auto" and mode == "off":
            setting = "off"
        if not total:
            if setting == "on" or mode == "on":
                plan.variables[name] = _entry(info, None, setting, supplied, "skipped", "no_total")
            continue
        covered = info["covered"] / total
        gap = total - info["covered"]
        if gap <= 0:
            continue
        max_supp = MAX_SUPPRESSED_PER_CODE * info["n_uncounted"]
        uncovered = gap / total
        e = _entry(info, total, setting, supplied, "skipped", "")
        e.update({
            "covered_share": covered, "uncovered_share": uncovered, "gap_records": gap,
            "max_suppressed_records": max_supp,
        })
        plan.variables[name] = e
        if setting == "off":
            e["reason"] = "off_by_config"
            continue
        fin = final.variables.get(name)
        if name in protected:
            e["reason"] = "rule_target"
            e["detail"] = protected[name]
            continue
        if fin is None or not _same_distribution(vm, fin):
            e["reason"] = "set_by_rule"
            continue
        if setting == "auto":
            if gap <= max_supp:
                e["reason"] = "suppression_only"
                continue
            if uncovered < min_share:
                e["reason"] = "below_min_share"
                continue
        code = _pick_na_code(info)
        e["code_counted"] = code is not None and code in info["counted"]
        e["status"] = "applied"
        e["reason"] = "applied"
        e["code"] = code
        e["blank"] = code is None
        e["target_share"] = uncovered
        if code is not None:
            # The share of the code in the whole table: the uncovered share, plus the part
            # of the covered share that already carries the code (when it has a count).
            e["code_share_target"] = uncovered + (
                info["counted"][code] / total if e["code_counted"] else 0.0
            )
    return plan


def _entry(
    info: Mapping[str, Any], total: Optional[int], setting: str, supplied: str, status: str,
    reason: str,
) -> Dict[str, Any]:
    return {
        "status": status, "reason": reason, "setting": setting, "supplied_by": supplied,
        "covered_share": None, "uncovered_share": None, "target_share": 0.0,
        "generated_rows": 0, "generated_share": 0.0, "code": None, "blank": False,
        "code_counted": False, "code_share_target": None, "code_share_generated": None,
        "n_uncounted_codes": info["n_uncounted"],
        "null_codes": sorted(
            str(v) for v, k in info["kinds"].items() if k != KIND_REAL
        ),
    }


# --------------------------------------------------------------------------- #
# Reporting helpers (conformance and fidelity that know about the fraction)
# --------------------------------------------------------------------------- #

def fidelity_among_counted(d: Any, df: Any, plan: Optional[NaPlan]) -> Any:
    """Marginal fidelity where each fraction variable is scored on the rows that kept a
    counted value (the generated not-applicable rows are reported separately).

    Blank cells need no special care: ``conformance_report`` and ``marginal_fidelity`` leave
    NULLs out. Rows given a not-applicable code are left out here, because the code has no
    published count and would otherwise count against the counted values."""
    import pandas as pd

    from .dictionary import DataDictionary
    from .evaluate import marginal_fidelity

    if plan is None or not plan.applied:
        return marginal_fidelity(d, df)
    on_masked = {v for v in plan.applied if v in d.variables and v in plan.masks}

    def sub(names: Iterable[str]) -> Any:
        return DataDictionary(
            name=d.name, source=d.source, version=d.version, n_records=d.n_records,
            variables={k: d.variables[k] for k in names}, notes=d.notes,
        )

    rest = [k for k in d.variables if k not in on_masked]
    parts = [marginal_fidelity(sub(rest), df)] if rest else []
    for name in sorted(on_masked):
        kept = df.loc[~plan.masks[name], [name]]
        if len(kept):
            parts.append(marginal_fidelity(sub([name]), kept))
    report = pd.concat(parts, ignore_index=True)
    return report.sort_values("tv_distance", ascending=False, ignore_index=True)


def protected_variables(ctx: Any) -> Dict[str, str]:
    """Variables the conditional and joints rules own: the fraction leaves them alone."""
    out: Dict[str, str] = {}
    plan = getattr(ctx, "conditional", None)
    if plan is not None:
        out[plan.group_var] = "conditional group"
        for t in plan.targets:
            out[t.variable] = "conditional target"
        for var in plan.age_derivations:
            out[var] = "conditional derived age"
        for var in plan.hierarchy:
            out[var] = "conditional derived"
    joint = getattr(ctx, "joint", None)
    if joint is not None:
        for dim in joint.dimensions:
            out[dim] = "joints dimension"
    return out


def na_summary_lines(report: Mapping[str, Any], limit: int = 6) -> List[str]:
    """Plain-text lines for the CLI."""
    if not report:
        return []
    s = report["settings"]
    lines = [
        f"Not-applicable fraction: mode={s['mode']} ({s['mode_supplied_by']}), "
        f"{report['n_applied']} variable(s) with a not-applicable share "
        f"({report['n_blank']} as blank)"
    ]
    shown = sorted(
        (v for v, e in report["variables"].items() if e["status"] == "applied"),
        key=lambda v: -report["variables"][v]["target_share"],
    )[:limit]
    for v in shown:
        e = report["variables"][v]
        code = "blank" if e["blank"] else repr(e["code"])
        lines.append(f"  {v}: {e['target_share']:.1%} -> {code}")
    return lines
