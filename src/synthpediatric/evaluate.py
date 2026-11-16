"""Fidelity scorecard: how well do synthetic marginals match the dictionary?

The primary Phase 0 metric is total variation distance (TVD) between the
synthetic empirical distribution and the published target distribution, computed
per variable. TVD ranges from 0 (identical) to 1 (disjoint). For pure
independent sampling TVD reflects only sampling noise; where consistency rules
repaired records, the affected variable's TVD rises slightly - that is the
honest, visible cost of enforcing coherence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dictionary import DataDictionary

PROVENANCE_STATEMENT = (
    "Privacy by design: these synthetic records were generated only from published "
    "aggregate value frequencies (marginals). No individual-level records were used, "
    "so there is no training population to re-identify and membership inference is not "
    "applicable by construction."
)


def marginal_fidelity(dictionary: DataDictionary, df: pd.DataFrame) -> pd.DataFrame:
    """Return a per-variable fidelity report comparing synthetic to target marginals.
    NULL (blank) cells are left out: the distance is computed among the non-null values,
    so a column blanked on purpose (for example by a ``repair_to_null`` rule) does not look
    like a distribution error. A column that is entirely null gets a NaN distance.
    """
    rows = []
    for name, var in dictionary.variables.items():
        if name not in df.columns:
            continue
        target = pd.Series(var.probabilities, index=[str(c) for c in var.categories])
        target = target.groupby(level=0).sum()  # guard against duplicate labels
        present = df[name].dropna()
        empirical = present.astype(str).value_counts(normalize=True)

        index = target.index.union(empirical.index)
        t = target.reindex(index, fill_value=0.0).to_numpy()
        e = empirical.reindex(index, fill_value=0.0).to_numpy()

        diff = np.abs(t - e)
        all_null = len(present) == 0 and len(df) > 0
        rows.append(
            {
                "variable": name,
                "n_categories": int(len(index)),
                "tv_distance": float("nan") if all_null else 0.5 * float(diff.sum()),
                "max_abs_diff": (
                    float("nan") if all_null else (float(diff.max()) if diff.size else 0.0)
                ),
                "frequency_source": getattr(var, "frequency_source", "published"),
            }
        )
    report = pd.DataFrame(
        rows,
        columns=["variable", "n_categories", "tv_distance", "max_abs_diff", "frequency_source"],
    )
    return report.sort_values("tv_distance", ascending=False, ignore_index=True)


def _published(report: pd.DataFrame) -> pd.DataFrame:
    """Rows scored against published frequencies (all rows if there is no source column)."""
    if "frequency_source" not in report.columns:
        return report
    return report[report["frequency_source"] != "uniform"]


def overall_score(report: pd.DataFrame, include_invented: bool = False) -> float:
    """Mean total variation distance (lower is better) over the published columns.

    A column with no published frequencies is invented (uniform fallback) and is scored
    against its own uniform target, which says nothing about fidelity, so it is left out.
    ``include_invented=True`` gives the older mean over every column. NaN if no column
    is left to average.
    """
    rows = report if include_invented else _published(report)
    if rows.empty:
        return float("nan")
    return float(rows["tv_distance"].mean())


def fidelity_summary(report: pd.DataFrame) -> dict:
    """Headline numbers for a manifest: published score, invented count, combined score."""

    def num(x: float):
        return None if x != x else x  # NaN -> None, so the manifest stays valid JSON

    published = _published(report)
    return {
        "published_columns": int(len(published)),
        "invented_columns": int(len(report) - len(published)),
        "overall_tv_distance_published": num(overall_score(report)),
        "overall_tv_distance_all_columns": num(overall_score(report, include_invented=True)),
    }
