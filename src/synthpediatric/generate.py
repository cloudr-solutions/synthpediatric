"""Phase 0 synthetic cohort generator: independent marginal sampling + repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd

from .constraints import RuleSet
from .dictionary import DataDictionary


@dataclass
class GenerationResult:
    """Output of :func:`generate`."""

    data: pd.DataFrame
    repairs: Dict[str, int] = field(default_factory=dict)
    n_requested: int = 0
    seed: Optional[int] = None

    @property
    def total_repairs(self) -> int:
        return int(sum(self.repairs.values()))


def _as_generator(rng: Union[np.random.Generator, int, None]) -> np.random.Generator:
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


def generate(
    dictionary: DataDictionary,
    n: int,
    rng: Union[np.random.Generator, int, None] = None,
    ruleset: Optional[RuleSet] = None,
) -> GenerationResult:
    """Generate ``n`` synthetic records from a marginals ``dictionary``.

    Each variable is sampled independently from its published marginal, then the
    optional ``ruleset`` repairs clinically incoherent records.
    """
    if n <= 0:
        raise ValueError("n must be a positive integer")

    seed = rng if isinstance(rng, int) else None
    generator = _as_generator(rng)

    columns = {
        name: var.sample(n, generator) for name, var in dictionary.variables.items()
    }
    df = pd.DataFrame(columns)

    repairs: Dict[str, int] = {}
    if ruleset is not None:
        df, repairs = ruleset.apply(df, generator)

    return GenerationResult(data=df, repairs=repairs, n_requested=n, seed=seed)
