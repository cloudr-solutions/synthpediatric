"""Abide-by-the-dictionary checks: coverage and vocabulary conformance.

- ``coverage_report`` summarizes, per variable, how its distribution is sourced —
  ``published`` (real NCCR record counts) vs. ``uniform`` (no published frequencies,
  sampled uniformly across permissible values). This tells the team exactly which
  variables still need Input-team statistics.
- ``conformance_report`` / ``assert_conformant`` verify that every value in a
  generated cohort is a permissible value for its variable (the hard guarantee).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .dictionary import DataDictionary


def coverage_report(dictionary: DataDictionary) -> pd.DataFrame:
    """Per-variable coverage: value count and whether frequencies are published."""
    rows = []
    for name, vm in dictionary.variables.items():
        rows.append(
            {
                "variable": name,
                "label": vm.label,
                "type": vm.vtype,
                "n_values": vm.n_categories,
                "frequency_source": getattr(vm, "frequency_source", "published"),
            }
        )
    report = pd.DataFrame(
        rows, columns=["variable", "label", "type", "n_values", "frequency_source"]
    )
    return report.sort_values(["frequency_source", "variable"], ignore_index=True)


def generation_report(
    loaded: DataDictionary, no_frequency: str = "uniform"
) -> Dict[str, Any]:
    """Which variables a run skipped and which it invented, from the dictionary as loaded.

    - ``dropped``: metadata variables that are not columns at all, each with a reason
      (``no_value_set``: the metadata lists no permissible values, so there is nothing to
      sample; ``too_few_values``; ``zero_counts``; ``no_counts_excluded``).
    - ``invented``: columns that have a value set but no published count anywhere. They
      are filled by a uniform draw (``no_frequency: uniform``), blanked (``nullify``) or
      removed (``suppress``); ``invented_handling`` says which.
    - ``published``: columns sampled from published counts.
    """
    invented = [
        n for n, v in loaded.variables.items()
        if getattr(v, "frequency_source", "published") == "uniform"
    ]
    return {
        "source": loaded.source_id,
        "published": len(loaded.variables) - len(invented),
        "dropped": dict(loaded.skipped),
        "invented": invented,
        "invented_handling": no_frequency,
    }


def report_lines(report: Dict[str, Any], limit: int = 8) -> List[str]:
    """Plain-text lines for the CLI summary (long name lists are cut at ``limit``)."""
    def names(items: List[str]) -> str:
        shown = ", ".join(items[:limit])
        return shown if len(items) <= limit else f"{shown}, ... ({len(items)} in total)"

    dropped = report["dropped"]
    handled = {
        "uniform": "filled with uniform random values",
        "nullify": "left blank",
        "suppress": "removed from the table",
    }[report["invented_handling"]]
    lines = [f"Columns sampled from published counts: {report['published']}"]
    lines.append(
        f"Dropped (not generated), {len(dropped)}: " + (names(list(dropped)) if dropped else "none")
    )
    if dropped:
        by_reason: Dict[str, int] = {}
        for reason in dropped.values():
            by_reason[reason] = by_reason.get(reason, 0) + 1
        lines.append("  reasons: " + ", ".join(f"{r} {n}" for r, n in sorted(by_reason.items())))
    invented = report["invented"]
    lines.append(
        f"Invented (no published counts), {len(invented)}, {handled}: "
        + (names(invented) if invented else "none")
    )
    return lines


def conformance_report(dictionary: DataDictionary, df: pd.DataFrame) -> pd.DataFrame:
    """Count out-of-vocabulary values per variable in a generated cohort.
    A NULL (blank) is never out of vocabulary. When any scored column contains nulls, an
    ``n_null`` column reports their count per variable; with no nulls the output is
    unchanged.
    """
    rows = []
    any_null = False
    for name, vm in dictionary.variables.items():
        if name not in df.columns:
            continue
        permissible = {str(c) for c in vm.categories}
        is_null = df[name].isna()
        n_null = int(is_null.sum())
        any_null = any_null or n_null > 0
        col = df[name].astype(str)
        bad = ~col.isin(permissible) & ~is_null
        n_bad = int(bad.sum())
        examples = sorted(col[bad].unique())[:5] if n_bad else []
        rows.append(
            {"variable": name, "n_out_of_vocabulary": n_bad, "examples": examples,
             "n_null": n_null}
        )
    cols = ["variable", "n_out_of_vocabulary", "examples"] + (["n_null"] if any_null else [])
    all_cols = ["variable", "n_out_of_vocabulary", "examples", "n_null"]
    return pd.DataFrame(rows, columns=all_cols)[cols]


def assert_conformant(dictionary: DataDictionary, df: pd.DataFrame) -> None:
    """Raise if any generated value is not a permissible value for its variable."""
    report = conformance_report(dictionary, df)
    offending = report[report["n_out_of_vocabulary"] > 0]
    if len(offending):
        raise ValueError(
            "non-conformant values found:\n" + offending.to_string(index=False)
        )
