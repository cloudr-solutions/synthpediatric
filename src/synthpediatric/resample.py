"""Reweight a dictionary variable to over/under-sample categories.

Supports the Jamboree "two synthetic resources" idea: ship one cohort at natural
disease proportions and one that oversamples rare/ultra-rare cancers so there are
enough cases to study. Reweighting produces a modified DataDictionary; generation is
otherwise unchanged. A reweighted cohort is NOT epidemiologically representative by
design - record the applied factors so downstream users can re-weight back if needed.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple

from .dictionary import DataDictionary, VariableMarginal


def reweight_variable(
    dictionary: DataDictionary,
    variable: str,
    factors: Mapping[object, float],
) -> DataDictionary:
    """Return a copy of ``dictionary`` with ``variable``'s category weights scaled.

    ``factors`` maps category value (matched by value or string form) to a multiplier;
    unlisted categories keep a factor of 1.0.
    """
    if variable not in dictionary.variables:
        raise KeyError(f"variable '{variable}' not in dictionary")
    vm = dictionary.variables[variable]
    new_weights = vm.weights.astype(float).copy()
    for i, cat in enumerate(vm.categories):
        new_weights[i] *= float(factors.get(cat, factors.get(str(cat), 1.0)))
    if new_weights.sum() <= 0:
        raise ValueError("reweighting drove all weights to zero")

    new_var = VariableMarginal(
        name=vm.name,
        label=vm.label,
        vtype=vm.vtype,
        categories=list(vm.categories),
        weights=new_weights,
        frequency_source=getattr(vm, "frequency_source", "published"),
    )
    new_vars = dict(dictionary.variables)
    new_vars[variable] = new_var
    return DataDictionary(
        name=f"{dictionary.name} [reweighted: {variable}]",
        source=dictionary.source,
        version=dictionary.version,
        n_records=dictionary.n_records,
        variables=new_vars,
        notes=dictionary.notes,
    )


def oversample_values(
    dictionary: DataDictionary,
    variable: str,
    values: Sequence[object],
    factor: float = 10.0,
) -> DataDictionary:
    """Boost the relative frequency of specific categories by ``factor``."""
    if factor <= 0:
        raise ValueError("factor must be positive")
    return reweight_variable(dictionary, variable, {v: factor for v in values})


def oversample_with_report(
    dictionary: DataDictionary,
    variable: str,
    values: Sequence[object],
    factor: float = 10.0,
) -> Tuple[DataDictionary, Dict[str, Any]]:
    """Like :func:`oversample_values`, also returning what was applied.

    The report records the factor applied to each matched category, any requested
    values that matched no category, and the proportions before and after, so a run
    manifest can state exactly how the cohort departs from natural proportions.
    """
    vm = dictionary.variables[variable]
    wanted = {str(v) for v in values}
    applied = {str(c): float(factor) for c in vm.categories if c in values or str(c) in wanted}
    unmatched = [v for v in values if not any(c == v or str(c) == str(v) for c in vm.categories)]
    reweighted = oversample_values(dictionary, variable, values, factor)
    report = {
        "variable": variable,
        "factor": float(factor),
        "factors_applied": applied,
        "unmatched_values": unmatched,
        "proportions_before": effective_proportions(dictionary, variable),
        "proportions_after": effective_proportions(reweighted, variable),
    }
    return reweighted, report


def rare_categories(
    dictionary: DataDictionary, variable: str, threshold: float = 0.01
) -> list:
    """List categories of ``variable`` whose published proportion is below ``threshold``."""
    if variable not in dictionary.variables:
        raise KeyError(f"variable '{variable}' not in dictionary")
    vm = dictionary.variables[variable]
    probs = vm.probabilities
    return [cat for cat, p in zip(vm.categories, probs) if p < threshold]


def oversample_rare(
    dictionary: DataDictionary,
    variable: str,
    threshold: float = 0.01,
    factor: float = 10.0,
) -> DataDictionary:
    """Convenience: oversample every category below ``threshold`` by ``factor``."""
    return oversample_values(
        dictionary, variable, rare_categories(dictionary, variable, threshold), factor
    )


def effective_proportions(dictionary: DataDictionary, variable: str) -> dict:
    """Current (possibly reweighted) proportions for ``variable`` — for reporting."""
    vm = dictionary.variables[variable]
    return {str(c): float(p) for c, p in zip(vm.categories, vm.probabilities)}
