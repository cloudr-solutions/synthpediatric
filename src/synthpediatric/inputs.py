"""Ingestion layer: turn external inputs into synthpediatric's internal objects.

The generator works from a :class:`~synthpediatric.dictionary.DataDictionary`
(marginals) plus optional calibration targets and survival specs. In practice the
"inputs" come from several external artifacts, and this module normalizes them:

- **Frequency tables** (SEER*Stat exports, platform Report JSON, hand-built):
  build a dictionary, or override specific variables' marginals in an existing
  (metadata-derived) dictionary with authoritative frequencies.
- **Cohort definitions** (the platform's cohort spec): restrict a dictionary to a
  cohort via EQUALS / MIN / MAX filters, so generation targets *that* cohort.

Cross-tab -> joint-distribution ingestion lives in
:meth:`synthpediatric.calibrate.JointDistribution.from_counts`.

Keeping ingestion separate means new input formats are added here without touching
generation, calibration, or analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Union

import numpy as np

from .dictionary import DataDictionary, VariableMarginal

Number = Union[int, float]


# --------------------------------------------------------------------------- #
# Frequency tables -> marginals
# --------------------------------------------------------------------------- #

FrequencyTable = Mapping[object, Number]  # value -> count or proportion


def _variable_from_frequencies(
    name: str, freqs: FrequencyTable, label: Optional[str] = None, vtype: str = "categorical"
) -> VariableMarginal:
    if not freqs:
        raise ValueError(f"variable '{name}': empty frequency table")
    categories = list(freqs.keys())
    weights = np.asarray([float(freqs[c]) for c in categories], dtype=float)
    return VariableMarginal(
        name=name, label=label or name, vtype=vtype, categories=categories, weights=weights
    )


def dictionary_from_frequencies(
    tables: Mapping[str, FrequencyTable],
    name: str = "frequency-built",
    source: str = "frequency tables",
    version: str = "",
    n_records: Optional[int] = None,
    labels: Optional[Mapping[str, str]] = None,
) -> DataDictionary:
    """Build a DataDictionary from per-variable frequency tables.

    ``tables`` maps variable name -> {value: count-or-proportion}. Use this to drive
    generation directly from SEER*Stat / Report JSON frequency output.
    """
    labels = labels or {}
    variables: Dict[str, VariableMarginal] = {}
    for var_name, freqs in tables.items():
        variables[var_name] = _variable_from_frequencies(var_name, freqs, labels.get(var_name))
    if not variables:
        raise ValueError("no variables provided")
    return DataDictionary(
        name=name, source=source, version=version, n_records=n_records,
        variables=variables, notes="Built from external frequency tables.",
    )


def override_marginals(
    dictionary: DataDictionary,
    tables: Mapping[str, FrequencyTable],
    add_missing: bool = True,
) -> DataDictionary:
    """Return a copy of ``dictionary`` with given variables' marginals replaced.

    Authoritative frequencies (e.g. the Input team's SEER*Stat numbers) supersede the
    metadata's record counts. Variables not in the dictionary are added when
    ``add_missing`` is true, otherwise a KeyError is raised.
    """
    new_vars = dict(dictionary.variables)
    for var_name, freqs in tables.items():
        existing = dictionary.variables.get(var_name)
        if existing is None and not add_missing:
            raise KeyError(f"variable '{var_name}' not in dictionary")
        label = existing.label if existing is not None else var_name
        vtype = existing.vtype if existing is not None else "categorical"
        new_vars[var_name] = _variable_from_frequencies(var_name, freqs, label, vtype)
    return DataDictionary(
        name=f"{dictionary.name} [marginals overridden]",
        source=dictionary.source, version=dictionary.version,
        n_records=dictionary.n_records, variables=new_vars, notes=dictionary.notes,
    )


# --------------------------------------------------------------------------- #
# Cohort definitions -> dictionary restriction
# --------------------------------------------------------------------------- #

@dataclass
class CohortFilter:
    """A single cohort filter. ``op`` is 'equals' (keep ``values``), 'min', or 'max'."""

    variable: str
    op: str
    values: Optional[Sequence[object]] = None
    threshold: Optional[Number] = None

    def __post_init__(self) -> None:
        self.op = self.op.lower()
        if self.op not in ("equals", "min", "max"):
            raise ValueError(f"unsupported filter op: {self.op}")
        if self.op == "equals" and not self.values:
            raise ValueError(f"filter on '{self.variable}': equals requires values")
        if self.op in ("min", "max") and self.threshold is None:
            raise ValueError(f"filter on '{self.variable}': {self.op} requires a threshold")


@dataclass
class CohortSpec:
    """A cohort definition: a named set of filters over variables."""

    filters: List[CohortFilter] = field(default_factory=list)
    name: str = "cohort"


def cohort_from_dict(spec: Mapping[str, object]) -> CohortSpec:
    """Build a CohortSpec from a plain dict (JSON-friendly).

    Example::

        {"name": "ALL ages 7-17",
         "filters": [
            {"variable": "icccMajor", "op": "equals",
             "values": ["I. Leukemias, Myeloproliferative And Myelodysplastic Diseases"]},
            {"variable": "ageRecodeSingle85p", "op": "min", "threshold": 7},
            {"variable": "ageRecodeSingle85p", "op": "max", "threshold": 17}]}
    """
    filters = [
        CohortFilter(
            variable=f["variable"],
            op=f["op"],
            values=f.get("values"),
            threshold=f.get("threshold"),
        )
        for f in spec.get("filters", [])
    ]
    return CohortSpec(filters=filters, name=str(spec.get("name", "cohort")))


def _leading_number(label: object) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", str(label))
    return float(m.group()) if m else None


def _filter_variable(vm: VariableMarginal, flt: CohortFilter) -> VariableMarginal:
    keep = np.ones(len(vm.categories), dtype=bool)
    if flt.op == "equals":
        selected = {str(v) for v in flt.values}
        keep = np.array([str(c) in selected for c in vm.categories])
    else:
        nums = np.array([_leading_number(c) for c in vm.categories], dtype=object)
        for i, nmbr in enumerate(nums):
            if nmbr is None:
                raise ValueError(
                    f"filter '{flt.op}' on '{flt.variable}': category {vm.categories[i]!r} "
                    "is not numeric; use an 'equals' filter instead"
                )
        vals = np.array([float(n) for n in nums])
        keep = vals >= flt.threshold if flt.op == "min" else vals <= flt.threshold
    if not keep.any():
        raise ValueError(f"filter on '{flt.variable}' removed all categories")
    cats = [c for c, k in zip(vm.categories, keep) if k]
    weights = vm.weights[keep]
    return VariableMarginal(
        vm.name, vm.label, vm.vtype, cats, weights,
        frequency_source=getattr(vm, "frequency_source", "published"),
    )


def apply_cohort(dictionary: DataDictionary, cohort: CohortSpec) -> DataDictionary:
    """Restrict a dictionary to a cohort definition.

    EQUALS keeps only the selected permissible values; MIN/MAX restrict numeric (or
    numeric-labeled) variables. Unfiltered variables are unchanged. Remaining weights
    are retained (renormalized implicitly at sampling) so each variable reflects the
    within-cohort distribution. Band-labeled variables (e.g. 5-year age groups) filter
    at band granularity.
    """
    new_vars = dict(dictionary.variables)
    for flt in cohort.filters:
        if flt.variable not in new_vars:
            raise KeyError(f"cohort filter variable '{flt.variable}' not in dictionary")
        new_vars[flt.variable] = _filter_variable(new_vars[flt.variable], flt)
    return DataDictionary(
        name=f"{dictionary.name} [cohort: {cohort.name}]",
        source=dictionary.source, version=dictionary.version,
        n_records=dictionary.n_records, variables=new_vars, notes=dictionary.notes,
    )
