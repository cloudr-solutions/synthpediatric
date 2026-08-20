"""Joint calibration: give synthetic cohorts real cross-variable structure.

Marginals alone cannot encode relationships between variables (age x disease,
sex x site, stage x survival). This module adds them with a transparent,
governance-friendly approach rather than a black-box generative model:

  1. Learn a JOINT distribution over a small "backbone" of variables from an
     individual-level proxy that has real correlations (e.g. SEER public-use
     research data, which shares NCCR's NAACCR/ICD-O/ICCC coding).
  2. Calibrate that joint's margins to the published NCCR frequencies using
     iterative proportional fitting (IPF / raking). The result keeps the proxy's
     association structure while matching NCCR's marginal distributions -
     "SEER's correlations wearing NCCR's distribution."
  3. Sample the backbone from the calibrated joint, then fill remaining variables
     from their marginals and apply the consistency rules.

IPF preserves the odds-ratio / association structure of the seed table while
forcing each variable's marginal to match its target. It cannot invent structure
for category combinations absent from the proxy; those stay at (near) zero.

Category LABELS must be harmonized between the proxy data and the NCCR dictionary
before calibration - IPF aligns targets to the joint by label, and unmatched
labels are dropped with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .dictionary import DataDictionary
from .generate import GenerationResult


@dataclass
class JointDistribution:
    """A dense contingency table over an ordered set of backbone variables."""

    dimensions: List[str]
    categories: Dict[str, List]
    table: np.ndarray = field(repr=False)

    def __post_init__(self) -> None:
        expected = tuple(len(self.categories[d]) for d in self.dimensions)
        if self.table.shape != expected:
            raise ValueError(
                f"table shape {self.table.shape} does not match categories {expected}"
            )

    # ---- construction ---------------------------------------------------

    @classmethod
    def from_records(
        cls, df: pd.DataFrame, columns: Sequence[str]
    ) -> "JointDistribution":
        """Build a joint (count) table from individual-level proxy records."""
        columns = list(columns)
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise KeyError(f"columns not in proxy data: {missing}")

        sub = df[columns].dropna()
        if len(sub) == 0:
            raise ValueError(
                f"no complete proxy records for columns {columns}: every row has a "
                "missing value in at least one of them, so no joint can be built"
            )
        categories = {c: sorted(sub[c].astype(str).unique(), key=str) for c in columns}
        index_of = {c: {v: i for i, v in enumerate(categories[c])} for c in columns}
        shape = tuple(len(categories[c]) for c in columns)
        table = np.zeros(shape, dtype=float)

        grouped = sub.astype(str).groupby(columns, sort=False).size()
        for key, count in grouped.items():
            if len(columns) == 1:
                key = (key,)
            idx = tuple(index_of[c][k] for c, k in zip(columns, key))
            table[idx] = count

        return cls(dimensions=columns, categories=categories, table=table)

    # ---- queries --------------------------------------------------------

    @property
    def total(self) -> float:
        return float(self.table.sum())

    def probabilities(self) -> np.ndarray:
        if self.total <= 0:
            raise ValueError("joint distribution has no mass")
        return self.table / self.total

    def marginal(self, var: str) -> Dict[object, float]:
        """Normalized marginal distribution of one backbone variable."""
        if self.total <= 0:
            raise ValueError("joint distribution has no mass")
        axis = self.dimensions.index(var)
        other = tuple(a for a in range(self.table.ndim) if a != axis)
        counts = self.table.sum(axis=other)
        probs = counts / counts.sum()
        return dict(zip(self.categories[var], probs))

    def sample(
        self, n: int, rng: Union[np.random.Generator, int, None] = None
    ) -> pd.DataFrame:
        """Draw ``n`` backbone rows from the joint distribution."""
        if self.total <= 0:
            raise ValueError("joint distribution has no mass")
        generator = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
        flat = self.table.ravel()
        probs = flat / flat.sum()
        picks = generator.choice(flat.size, size=n, p=probs)
        multi = np.unravel_index(picks, self.table.shape)
        data = {
            dim: np.asarray(self.categories[dim], dtype=object)[multi[i]]
            for i, dim in enumerate(self.dimensions)
        }
        return pd.DataFrame(data)


@dataclass
class CalibrationResult:
    """A calibrated joint plus diagnostics from the IPF run."""

    joint: JointDistribution
    iterations: int
    max_deviation: float
    converged: bool
    warnings: List[str] = field(default_factory=list)


def targets_from_dictionary(
    dictionary: DataDictionary, variables: Sequence[str]
) -> Dict[str, Dict[object, float]]:
    """Extract target marginal proportions (by label) from an NCCR dictionary."""
    targets: Dict[str, Dict[object, float]] = {}
    for var in variables:
        if var not in dictionary.variables:
            raise KeyError(f"variable '{var}' not in dictionary")
        vm = dictionary.variables[var]
        # Sum probabilities for categories that render to the same label, so mass
        # is not silently dropped by later entries overwriting earlier ones.
        merged: Dict[object, float] = {}
        for c, p in zip(vm.categories, vm.probabilities):
            key = str(c)
            merged[key] = merged.get(key, 0.0) + float(p)
        targets[var] = merged
    return targets


def raking_ipf(
    joint: JointDistribution,
    targets: Mapping[str, Mapping[object, float]],
    max_iter: int = 100,
    tol: float = 1e-8,
    smoothing: float = 0.0,
) -> CalibrationResult:
    """Iteratively scale the joint so each variable's marginal matches its target.

    Parameters
    ----------
    smoothing:
        Small mass added to every cell before fitting. Use a positive value if the
        proxy is missing category combinations that the targets require (otherwise
        those cells cannot receive mass).
    """
    table = joint.table.astype(float).copy()
    if smoothing > 0:
        table = table + smoothing
    if table.sum() <= 0:
        raise ValueError("joint table has no mass")

    msgs: List[str] = []

    # Pre-align each target to this joint's category order (by string label).
    aligned: Dict[str, Tuple[int, np.ndarray]] = {}
    for var, tgt in targets.items():
        if var not in joint.dimensions:
            msgs.append(f"target variable '{var}' not in joint; ignored")
            continue
        cats = joint.categories[var]
        vec = np.array([float(tgt.get(str(c), 0.0)) for c in cats], dtype=float)
        unplaceable = [k for k in tgt if str(k) not in {str(c) for c in cats}]
        if unplaceable:
            msgs.append(
                f"'{var}': {len(unplaceable)} target label(s) absent from proxy, dropped"
            )
        if vec.sum() <= 0:
            msgs.append(f"'{var}': target has no overlapping labels; skipped")
            continue
        vec = vec / vec.sum()
        aligned[var] = (joint.dimensions.index(var), vec)

    if not aligned:
        raise ValueError(
            "no target survived label alignment with the joint; nothing to calibrate. "
            "Check that target variables are backbone dimensions and that category "
            "labels are harmonized between the proxy and the dictionary. "
            f"Diagnostics: {msgs}"
        )

    converged = False
    it = 0
    max_dev = np.inf
    for it in range(1, max_iter + 1):
        max_dev = 0.0
        total = table.sum()
        for axis, target_vec in aligned.values():
            other = tuple(a for a in range(table.ndim) if a != axis)
            current = table.sum(axis=other) / total
            max_dev = max(max_dev, float(np.abs(target_vec - current).max()))
            scale = np.divide(
                target_vec, current, out=np.zeros_like(target_vec), where=current > 0
            )
            shape = [1] * table.ndim
            shape[axis] = table.shape[axis]
            table = table * scale.reshape(shape)
            total = table.sum()
        if max_dev < tol:
            converged = True
            break

    table = table / table.sum()
    calibrated = JointDistribution(
        dimensions=list(joint.dimensions),
        categories={k: list(v) for k, v in joint.categories.items()},
        table=table,
    )
    return CalibrationResult(
        joint=calibrated, iterations=it, max_deviation=max_dev, converged=converged, warnings=msgs
    )


def calibrate_to_dictionary(
    proxy: pd.DataFrame,
    columns: Sequence[str],
    dictionary: DataDictionary,
    max_iter: int = 100,
    tol: float = 1e-8,
    smoothing: float = 0.0,
) -> CalibrationResult:
    """Learn a joint from proxy records and calibrate it to NCCR marginals."""
    joint = JointDistribution.from_records(proxy, columns)
    targets = targets_from_dictionary(dictionary, columns)
    return raking_ipf(joint, targets, max_iter=max_iter, tol=tol, smoothing=smoothing)


def generate_calibrated(
    dictionary: DataDictionary,
    joint: JointDistribution,
    n: int,
    rng: Union[np.random.Generator, int, None] = None,
    ruleset=None,
) -> GenerationResult:
    """Generate a cohort: calibrated joint backbone + marginal sampling for the rest.

    Backbone variables (``joint.dimensions``) are drawn jointly so their
    correlations are preserved; every other variable in ``dictionary`` is sampled
    independently from its marginal. Consistency rules are applied last.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    missing = [d for d in joint.dimensions if d not in dictionary.variables]
    if missing:
        raise ValueError(
            f"joint backbone dimensions not present in the dictionary: {missing}. "
            "Every backbone dimension must correspond to a dictionary variable."
        )
    seed = rng if isinstance(rng, int) else None
    generator = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)

    backbone = joint.sample(n, generator)

    columns = {}
    for name, var in dictionary.variables.items():
        if name in joint.dimensions:
            columns[name] = backbone[name].to_numpy()
        else:
            columns[name] = var.sample(n, generator)
    df = pd.DataFrame(columns)

    repairs: Dict[str, int] = {}
    if ruleset is not None:
        df, repairs = ruleset.apply(df, generator)

    return GenerationResult(data=df, repairs=repairs, n_requested=n, seed=seed)
