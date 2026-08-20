"""Survival analysis for pediatric/AYA cancer cohorts (registry-native).

A dependency-light analysis layer — the kind of cohort-level epidemiology the NCCR
Data Platform does not provide today. The Kaplan-Meier estimator and log-rank test
are implemented in NumPy (no heavy dependencies); the log-rank p-value uses SciPy if
it is available, and otherwise returns the chi-square statistic and degrees of freedom.

Everything here operates on an ordinary time-to-event table (a time column and a 0/1
event column), so it runs identically on a real approved NCCR download, on SEER
public-use data, or on a synthetic cohort produced by this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class KMResult:
    """A Kaplan-Meier survival curve (right-continuous step function)."""

    time: np.ndarray       # event/censoring times, with 0.0 prepended
    survival: np.ndarray   # S(t) after each time
    at_risk: np.ndarray    # number at risk entering each time
    events: np.ndarray     # events observed at each time
    n: int
    n_events: int

    def survival_at(self, t: float) -> float:
        """Survival probability at time ``t`` (step function, right-continuous)."""
        idx = int(np.searchsorted(self.time, t, side="right") - 1)
        idx = max(idx, 0)
        return float(self.survival[idx])

    def median_survival(self) -> float:
        """Smallest time at which survival drops to <= 0.5 (NaN if never reached)."""
        below = np.where(self.survival <= 0.5)[0]
        if below.size == 0:
            return float("nan")
        return float(self.time[below[0]])


def kaplan_meier(time: Sequence[float], event: Sequence[int]) -> KMResult:
    """Kaplan-Meier product-limit estimator.

    Parameters
    ----------
    time:  observed time to event or censoring (non-negative).
    event: 1 if the event was observed, 0 if censored.
    """
    time = np.asarray(time, dtype=float)
    event = np.asarray(event, dtype=int)
    if time.shape != event.shape or time.ndim != 1:
        raise ValueError("time and event must be 1-D arrays of equal length")
    if time.size == 0:
        raise ValueError("empty cohort")
    if np.any(time < 0):
        raise ValueError("times must be non-negative")
    if not np.all(np.isin(event, (0, 1))):
        raise ValueError("event must contain only 0 or 1")

    times: List[float] = [0.0]
    surv: List[float] = [1.0]
    at_risk: List[int] = [int(time.size)]
    events: List[int] = [0]

    s = 1.0
    for t in np.unique(time):
        nar = int(np.sum(time >= t))
        d = int(np.sum((time == t) & (event == 1)))
        if d > 0 and nar > 0:
            s *= 1.0 - d / nar
        times.append(float(t))
        surv.append(s)
        at_risk.append(nar)
        events.append(d)

    return KMResult(
        time=np.asarray(times),
        survival=np.asarray(surv),
        at_risk=np.asarray(at_risk),
        events=np.asarray(events),
        n=int(time.size),
        n_events=int(event.sum()),
    )


def kaplan_meier_by_group(
    df: pd.DataFrame, time_col: str, event_col: str, group_col: str
) -> Dict[object, KMResult]:
    """Fit a Kaplan-Meier curve within each level of ``group_col``."""
    for col in (time_col, event_col, group_col):
        if col not in df.columns:
            raise KeyError(f"column '{col}' not in data")
    out: Dict[object, KMResult] = {}
    for group, sub in df.groupby(group_col, sort=False):
        out[group] = kaplan_meier(sub[time_col].to_numpy(), sub[event_col].to_numpy())
    return out


def logrank_test(
    df: pd.DataFrame, time_col: str, event_col: str, group_col: str
) -> Dict[str, object]:
    """K-sample log-rank test for equality of survival across groups.

    Returns the chi-square statistic and degrees of freedom, plus a p-value when
    SciPy is available.
    """
    groups = sorted(df[group_col].dropna().unique(), key=str)
    k = len(groups)
    if k < 2:
        raise ValueError("log-rank test needs at least two groups")

    time = df[time_col].to_numpy(dtype=float)
    event = df[event_col].to_numpy(dtype=int)
    grp = df[group_col].to_numpy()

    observed = np.zeros(k)
    expected = np.zeros(k)
    var = np.zeros((k, k))

    for t in np.unique(time[event == 1]):
        at_risk = time >= t
        n = int(at_risk.sum())
        d = int(((time == t) & (event == 1)).sum())
        if n <= 1:
            continue
        is_t_event = (time == t) & (event == 1)
        n_g = np.array([int((at_risk & (grp == g)).sum()) for g in groups], dtype=float)
        d_g = np.array([int((is_t_event & (grp == g)).sum()) for g in groups], dtype=float)
        observed += d_g
        expected += d * n_g / n
        factor = d * (n - d) / (n - 1) / (n * n)
        for i in range(k):
            var[i, i] += factor * n_g[i] * (n - n_g[i])
            for j in range(i + 1, k):
                cov = -factor * n_g[i] * n_g[j]
                var[i, j] += cov
                var[j, i] += cov

    oe = (observed - expected)[:-1]
    v_reduced = var[:-1, :-1]
    chi2 = float(oe @ np.linalg.pinv(v_reduced) @ oe)
    dof = k - 1

    p_value: Optional[float] = None
    try:  # optional: nicer output if SciPy is present
        from scipy.stats import chi2 as _chi2

        p_value = float(_chi2.sf(chi2, dof))
    except Exception:  # pragma: no cover - SciPy not installed
        p_value = None

    return {
        "chi2": chi2,
        "df": dof,
        "p_value": p_value,
        "groups": [str(g) for g in groups],
        "observed": {str(g): float(o) for g, o in zip(groups, observed)},
        "expected": {str(g): float(e) for g, e in zip(groups, expected)},
    }
