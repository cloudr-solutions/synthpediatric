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
    """Return a per-variable fidelity report comparing synthetic to target marginals."""
    rows = []
    for name, var in dictionary.variables.items():
        if name not in df.columns:
            continue
        target = pd.Series(var.probabilities, index=[str(c) for c in var.categories])
        target = target.groupby(level=0).sum()  # guard against duplicate labels
        empirical = df[name].astype(str).value_counts(normalize=True)

        index = target.index.union(empirical.index)
        t = target.reindex(index, fill_value=0.0).to_numpy()
        e = empirical.reindex(index, fill_value=0.0).to_numpy()

        diff = np.abs(t - e)
        rows.append(
            {
                "variable": name,
                "n_categories": int(len(index)),
                "tv_distance": 0.5 * float(diff.sum()),
                "max_abs_diff": float(diff.max()) if diff.size else 0.0,
            }
        )
    report = pd.DataFrame(rows, columns=["variable", "n_categories", "tv_distance", "max_abs_diff"])
    return report.sort_values("tv_distance", ascending=False, ignore_index=True)


def overall_score(report: pd.DataFrame) -> float:
    """Mean total variation distance across variables (lower is better)."""
    if report.empty:
        return float("nan")
    return float(report["tv_distance"].mean())
