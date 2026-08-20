"""Canonical representation of a marginals data dictionary.

A marginals dictionary describes, for each variable in a dataset, the frequency
(count or proportion) of every permissible value. This is exactly the information
published in registry data dictionaries with value frequencies.

The loader is intentionally tolerant so it can adapt to real NCCR dictionary
exports: value counts may be provided under any of several keys (``count``,
``frequency``, ``proportion``, ...), and proportions are accepted in place of
raw counts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

# Keys we will accept for the per-value weight, in priority order.
_WEIGHT_KEYS = ("count", "counts", "n", "frequency", "freq", "proportion", "prop", "pct", "percent")


@dataclass
class VariableMarginal:
    """The marginal (univariate) distribution of a single variable."""

    name: str
    label: str
    vtype: str
    categories: List[Any]
    weights: np.ndarray = field(repr=False)

    def __post_init__(self) -> None:
        self.weights = np.asarray(self.weights, dtype=float)
        if self.weights.ndim != 1 or self.weights.size != len(self.categories):
            raise ValueError(
                f"variable '{self.name}': weights ({self.weights.size}) and "
                f"categories ({len(self.categories)}) length mismatch"
            )
        if self.weights.size == 0:
            raise ValueError(f"variable '{self.name}': no permissible values provided")
        if np.any(self.weights < 0):
            raise ValueError(f"variable '{self.name}': negative frequencies are not allowed")
        if self.weights.sum() <= 0:
            raise ValueError(f"variable '{self.name}': frequencies sum to zero")

    @property
    def probabilities(self) -> np.ndarray:
        """Weights normalized to a probability distribution."""
        return self.weights / self.weights.sum()

    @property
    def n_categories(self) -> int:
        return len(self.categories)

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Draw ``n`` independent values from this marginal."""
        cats = np.asarray(self.categories, dtype=object)
        idx = rng.choice(len(cats), size=n, p=self.probabilities)
        return cats[idx]

    @classmethod
    def from_dict(cls, spec: Dict[str, Any]) -> "VariableMarginal":
        name = spec.get("name")
        if not name:
            raise ValueError("each variable requires a 'name'")
        raw_values = spec.get("values")
        if not raw_values:
            raise ValueError(f"variable '{name}' requires a non-empty 'values' list")

        categories: List[Any] = []
        weights: List[float] = []
        for entry in raw_values:
            if not isinstance(entry, dict) or "value" not in entry:
                raise ValueError(
                    f"variable '{name}': each value entry must be an object with a 'value' key"
                )
            categories.append(entry["value"])
            weights.append(_extract_weight(entry, name))

        return cls(
            name=name,
            label=spec.get("label", name),
            vtype=spec.get("type", "categorical"),
            categories=categories,
            weights=np.asarray(weights, dtype=float),
        )


def _extract_weight(entry: Dict[str, Any], var_name: str) -> float:
    for key in _WEIGHT_KEYS:
        if key in entry and entry[key] is not None:
            return float(entry[key])
    raise ValueError(
        f"variable '{var_name}': value entry {entry!r} has no recognized weight key "
        f"(expected one of {_WEIGHT_KEYS})"
    )


@dataclass
class DataDictionary:
    """A dataset's variables and their marginal distributions."""

    name: str
    source: str
    version: str
    n_records: Optional[int]
    variables: Dict[str, VariableMarginal]
    notes: str = ""

    @property
    def variable_names(self) -> List[str]:
        return list(self.variables)

    def __getitem__(self, key: str) -> VariableMarginal:
        return self.variables[key]

    @classmethod
    def from_dict(cls, spec: Dict[str, Any]) -> "DataDictionary":
        raw_vars = spec.get("variables")
        if not raw_vars:
            raise ValueError("dictionary requires a non-empty 'variables' list")
        variables: Dict[str, VariableMarginal] = {}
        for var_spec in raw_vars:
            var = VariableMarginal.from_dict(var_spec)
            if var.name in variables:
                raise ValueError(f"duplicate variable name: '{var.name}'")
            variables[var.name] = var
        return cls(
            name=spec.get("name", "unnamed"),
            source=spec.get("source", ""),
            version=spec.get("version", ""),
            n_records=spec.get("n_records"),
            variables=variables,
            notes=spec.get("notes", ""),
        )

    @classmethod
    def load(cls, path: Union[str, Path]) -> "DataDictionary":
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
        return cls.from_dict(spec)
