"""Generate synthetic time-to-event (survival) from a survival specification.

The counterpart to :mod:`synthpediatric.analyze`: analysis *recovers* survival
curves; this module *generates* synthetic follow-up time + vital status whose
Kaplan-Meier curves match a provided survival specification. That specification is
exactly the kind of output the "Input team" produces from SEER*Stat (e.g., 5-year
survival, or survival probabilities at several time points, by disease group).

This closes the loop: Input team survival stats -> generate survival -> analysis
toolkit (KM) reproduces the input curve -> validation.

A per-group survival spec may be:
  * a float                      -> interpreted as 5-year (60-month) overall survival
  * {"s5": 0.90}                 -> 5-year survival
  * {"median_months": 40}        -> median survival (exponential)
  * {"points": {12: 0.95, 60: 0.80, 120: 0.70}}  -> survival at given months
  * [(12, 0.95), (60, 0.80)]     -> same, as (month, survival) pairs

The first three assume a constant-hazard (exponential) form; "points" uses
piecewise-linear inverse-CDF sampling and is the most faithful to real curves.
"""

from __future__ import annotations

from typing import Mapping, Sequence, Tuple, Union

import numpy as np

SurvivalSpec = Union[float, Mapping[str, object], Sequence[Tuple[float, float]]]


def _exponential_sampler(rate: float, rng: np.random.Generator):
    if rate <= 0:
        return lambda n: np.full(n, np.inf)
    return lambda n: rng.exponential(1.0 / rate, size=n)


def _table_sampler(points, rng: np.random.Generator):
    """Piecewise-linear inverse-CDF sampler from (month, survival) points."""
    if isinstance(points, Mapping):
        items = sorted(points.items())
    else:
        items = sorted(points)
    t = [0.0]
    s = [1.0]
    for ti, si in items:
        t.append(float(ti))
        s.append(float(si))
    t_arr = np.asarray(t)
    s_arr = np.asarray(s)
    if np.any(np.diff(s_arr) > 0):
        raise ValueError("survival points must be non-increasing in time")
    s_last = s_arr[-1]
    # np.interp needs ascending x; survival is descending, so reverse.
    s_asc = s_arr[::-1]
    t_asc = t_arr[::-1]

    def sampler(n: int) -> np.ndarray:
        u = rng.uniform(size=n)
        event_t = np.interp(u, s_asc, t_asc)
        # u below the last observed survival -> event is beyond the observed range.
        return np.where(u < s_last, np.inf, event_t)

    return sampler


def _make_sampler(spec: SurvivalSpec, rng: np.random.Generator):
    if isinstance(spec, (int, float)):
        spec = {"s5": float(spec)}
    if isinstance(spec, Mapping):
        if "median_months" in spec:
            return _exponential_sampler(np.log(2.0) / float(spec["median_months"]), rng)
        if "s5" in spec:
            s5 = min(max(float(spec["s5"]), 1e-9), 1 - 1e-9)
            return _exponential_sampler(-np.log(s5) / 60.0, rng)
        if "points" in spec:
            return _table_sampler(spec["points"], rng)
        raise ValueError(f"unrecognized survival spec keys: {list(spec)}")
    # sequence of (t, S) pairs
    return _table_sampler(spec, rng)


def sample_survival(
    groups: Sequence,
    specs: Mapping[object, SurvivalSpec],
    rng: Union[np.random.Generator, int, None] = None,
    horizon_months: float = 120.0,
    dropout_min_months: float = 12.0,
    default_spec: SurvivalSpec = 0.80,
) -> Tuple[np.ndarray, np.ndarray]:
    """Sample (observed months, event indicator) for each record in ``groups``.

    Each group's event times come from its survival spec; administrative censoring
    is applied at ``horizon_months`` with random dropout uniformly from
    ``dropout_min_months`` to the horizon. ``specs`` is keyed by group value
    (matched by value or its string form); ``default_spec`` covers unlisted groups.
    """
    generator = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
    groups = np.asarray(groups, dtype=object)
    months = np.empty(groups.size, dtype=float)
    event = np.zeros(groups.size, dtype=int)

    for g in np.unique(groups):
        mask = groups == g
        k = int(mask.sum())
        spec = specs.get(g, specs.get(str(g), default_spec))
        t_event = _make_sampler(spec, generator)(k)
        t_cens = generator.uniform(dropout_min_months, horizon_months, size=k)
        obs = np.minimum(t_event, t_cens)
        ev = (t_event <= t_cens).astype(int)
        over = obs > horizon_months
        obs[over] = horizon_months
        ev[over] = 0
        months[mask] = obs
        event[mask] = ev

    return months, event
