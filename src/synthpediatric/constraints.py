"""Consistency-rules engine.

Independent marginal sampling produces clinically incoherent records (e.g. a
retinoblastoma case in a 35-year-old). Constraints detect and repair these
violations. Repairs necessarily perturb the affected variable's marginal
slightly; that trade-off is surfaced in the fidelity report so it stays honest.

Constraints are declarative and data-driven so the engine is not tied to any
particular dictionary. A rule set can be loaded from JSON (see
``examples/nccr_ctc_rules.json``).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union

import numpy as np
import pandas as pd


class Constraint(ABC):
    """A single consistency rule over a DataFrame of synthetic records."""

    name: str
    description: str

    def column_refs(self) -> Dict[str, str]:
        """Data columns this constraint reads or writes, keyed by the field that names them."""
        return {}

    @abstractmethod
    def find_violations(self, df: pd.DataFrame) -> pd.Series:
        """Return a boolean Series marking rows that violate this constraint."""

    @abstractmethod
    def repair(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        """Return a DataFrame with violating rows repaired in place."""


@dataclass
class AllowedValuesConstraint(Constraint):
    """When ``trigger_col`` holds one of ``trigger_values``, ``target_col`` must
    be one of ``allowed_values``. Violations are repaired by resampling the
    target from the allowed set."""

    trigger_col: str
    trigger_values: Sequence[Any]
    target_col: str
    allowed_values: Sequence[Any]
    description: str = ""
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"{self.trigger_col}->{self.target_col}"
        if not self.allowed_values:
            raise ValueError(f"constraint '{self.name}': allowed_values must be non-empty")
        self._trigger = list(self.trigger_values)
        self._allowed = list(self.allowed_values)

    def column_refs(self) -> Dict[str, str]:
        return {"trigger_col": self.trigger_col, "target_col": self.target_col}

    def _check_columns(self, df: pd.DataFrame) -> None:
        for col in (self.trigger_col, self.target_col):
            if col not in df.columns:
                raise KeyError(f"constraint '{self.name}': column '{col}' not in data")

    def find_violations(self, df: pd.DataFrame) -> pd.Series:
        self._check_columns(df)
        triggered = df[self.trigger_col].isin(self._trigger)
        out_of_range = ~df[self.target_col].isin(self._allowed)
        return triggered & out_of_range

    def repair(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        mask = self.find_violations(df)
        k = int(mask.sum())
        if k:
            picks = rng.choice(len(self._allowed), size=k)
            df.loc[mask, self.target_col] = [self._allowed[i] for i in picks]
        return df

    @classmethod
    def from_dict(cls, spec: Dict[str, Any]) -> "AllowedValuesConstraint":
        return cls(
            trigger_col=spec["trigger_col"],
            trigger_values=spec["trigger_values"],
            target_col=spec["target_col"],
            allowed_values=spec["allowed_values"],
            description=spec.get("description", ""),
            name=spec.get("name", ""),
        )


_CONSTRAINT_TYPES = {
    "allowed_values": AllowedValuesConstraint,
}


@dataclass
class RuleSet:
    """An ordered collection of constraints applied iteratively until stable."""

    constraints: List[Constraint] = field(default_factory=list)
    max_iterations: int = 10

    def apply(
        self, df: pd.DataFrame, rng: np.random.Generator
    ) -> Tuple[pd.DataFrame, Dict[str, int]]:
        """Repair the DataFrame in place; return it plus a per-constraint repair count."""
        summary: Dict[str, int] = {c.name: 0 for c in self.constraints}
        if not self.constraints:
            return df, summary

        for _ in range(self.max_iterations):
            total = 0
            for constraint in self.constraints:
                n = int(constraint.find_violations(df).sum())
                if n:
                    df = constraint.repair(df, rng)
                    summary[constraint.name] += n
                    total += n
            if total == 0:
                break
        return df, summary

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "RuleSet":
        with Path(path).open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
        return cls.from_dict(spec)

    @classmethod
    def from_dict(cls, spec: Dict[str, Any]) -> "RuleSet":
        raw = spec.get("constraints", [])
        constraints: List[Constraint] = []
        for entry in raw:
            ctype = entry.get("type", "allowed_values")
            if ctype not in _CONSTRAINT_TYPES:
                raise ValueError(
                    f"unknown constraint type: '{ctype}'. "
                    f"Valid types: {', '.join(_CONSTRAINT_TYPES)}"
                )
            constraints.append(_CONSTRAINT_TYPES[ctype].from_dict(entry))
        return cls(constraints=constraints, max_iterations=spec.get("max_iterations", 10))
