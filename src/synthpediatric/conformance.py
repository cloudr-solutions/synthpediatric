"""Abide-by-the-dictionary checks: coverage and vocabulary conformance.

- ``coverage_report`` summarizes, per variable, how its distribution is sourced —
  ``published`` (real NCCR record counts) vs. ``uniform`` (no published frequencies,
  sampled uniformly across permissible values). This tells the team exactly which
  variables still need Input-team statistics.
- ``conformance_report`` / ``assert_conformant`` verify that every value in a
  generated cohort is a permissible value for its variable (the hard guarantee).
"""

from __future__ import annotations

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


def conformance_report(dictionary: DataDictionary, df: pd.DataFrame) -> pd.DataFrame:
    """Count out-of-vocabulary values per variable in a generated cohort."""
    rows = []
    for name, vm in dictionary.variables.items():
        if name not in df.columns:
            continue
        permissible = {str(c) for c in vm.categories}
        col = df[name].astype(str)
        bad = ~col.isin(permissible)
        n_bad = int(bad.sum())
        examples = sorted(col[bad].unique())[:5] if n_bad else []
        rows.append(
            {"variable": name, "n_out_of_vocabulary": n_bad, "examples": examples}
        )
    return pd.DataFrame(rows, columns=["variable", "n_out_of_vocabulary", "examples"])


def assert_conformant(dictionary: DataDictionary, df: pd.DataFrame) -> None:
    """Raise if any generated value is not a permissible value for its variable."""
    report = conformance_report(dictionary, df)
    offending = report[report["n_out_of_vocabulary"] > 0]
    if len(offending):
        raise ValueError(
            "non-conformant values found:\n" + offending.to_string(index=False)
        )
