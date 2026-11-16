"""Load real NCCR Data Platform metadata (RDF/Turtle) into a ``DataDictionary``.

The NCCR Data Platform publishes machine-readable, FAIR metadata as linked data:
an OWL vocabulary, a DATMM dataset catalog, and instance data describing all 533
variables across 9 datasources, including per-value record counts. See
https://nci-dccps.github.io/nccr-metadata.

This module parses that Turtle, extracts the published marginal (permissible-value
frequency) distribution for every variable that has one, and returns the same
:class:`~synthpediatric.dictionary.DataDictionary` objects the rest of ``synthpediatric``
already understands. In other words: point the existing Phase-0 generator at the
real NCCR frequencies with no other code changes.

Only aggregate ``nccr:recordCount`` values are read - no individual-level data
exists in this metadata - so the privacy-by-design property is preserved.

Requires the optional ``rdflib`` dependency (``pip install synthpediatric[rdf]``).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Union

import numpy as np

from .config import ConfigError, unknown_message
from .dictionary import DataDictionary, VariableMarginal
from .nullcodes import load_overrides, merge_overrides, variable_na_info

# Raw Turtle published by the NCCR metadata project (main branch).
_RAW_BASE = "https://raw.githubusercontent.com/NCI-DCCPS/nccr-metadata/main"
NCCR_INSTANCES_URL = f"{_RAW_BASE}/nccr_instances.ttl"
NCCR_VOCAB_URL = f"{_RAW_BASE}/nccr_vocab.ttl"
NCCR_DATMM_URL = f"{_RAW_BASE}/nccr_datmm.ttl"

# The 9 NCCR datasources (sourceId -> human label), for reference/validation.
KNOWN_SOURCES = {
    "CTC": "Consolidated Tumor Case",
    "ABM": "Area-Based Measures",
    "CCDI": "CCDI Mappings",
    "COG": "Children's Oncology Group",
    "MCD": "Medical Claims Diagnosis",
    "MCE": "Medical Claims Enrollment",
    "MCP": "Medical Claims Procedure",
    "PHARM": "Pharmacy Claims",
    "RO": "Radiation Oncology",
}

_VOCAB = "https://nccrdataplatform.ccdi.cancer.gov/vocab#"

# One row per (variable, coded value) that carries a published record count.
_MARGINALS_QUERY = """
PREFIX nccr: <https://nccrdataplatform.ccdi.cancer.gov/vocab#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?sid ?col ?vlabel ?stype ?notation ?plabel ?desc ?rc WHERE {
    ?var a nccr:Variable ;
         nccr:sourceColumn ?col ;
         nccr:belongsToSource ?ds ;
         nccr:hasValueSet ?vs .
    ?ds nccr:sourceId ?sid .
    OPTIONAL { ?var rdfs:label ?vlabel }
    OPTIONAL { ?var nccr:semanticType ?stype }
    ?cv skos:inScheme ?vs .
    OPTIONAL { ?cv nccr:recordCount ?rc }
    OPTIONAL { ?cv skos:prefLabel ?plabel }
    OPTIONAL { ?cv skos:notation ?notation }
    OPTIONAL { ?cv nccr:codeDescription ?desc }
}
"""

# Every variable of every source, whether or not it has a value set.
_COLUMNS_QUERY = """
PREFIX nccr: <https://nccrdataplatform.ccdi.cancer.gov/vocab#>
SELECT DISTINCT ?sid ?col WHERE {
    ?var a nccr:Variable ;
         nccr:sourceColumn ?col ;
         nccr:belongsToSource ?ds .
    ?ds nccr:sourceId ?sid .
}
"""

# Why a metadata variable is not a column of the generated table.
SKIP_REASONS = {
    "no_value_set": "the metadata gives the variable no permissible values (ids, codes, free text)",
    "too_few_values": "fewer than min_values distinct values after labels were merged",
    "zero_counts": "every published count is zero",
    "no_counts_excluded": "no published counts and no_frequency='exclude'",
}
VALUE_MODES = ("label", "code")

_SOURCES_QUERY = """
PREFIX nccr: <https://nccrdataplatform.ccdi.cancer.gov/vocab#>
SELECT ?sid ?label ?total WHERE {
    ?ds a nccr:DataSource ;
        nccr:sourceId ?sid .
    OPTIONAL { ?ds nccr:sourceLabel ?label }
    OPTIONAL { ?ds nccr:totalRecordCount ?total }
}
ORDER BY DESC(?total)
"""


def _require_rdflib():
    try:
        import rdflib  # noqa: F401
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "Loading NCCR RDF metadata requires 'rdflib'. Install it with:\n"
            "    pip install synthpediatric[rdf]\n"
            "or\n"
            "    pip install rdflib"
        ) from exc
    return rdflib


def load_graph(sources: Optional[Sequence[Union[str, Path]]] = None):
    """Parse one or more Turtle sources (local paths or URLs) into an rdflib Graph.

    Defaults to the published NCCR instance data (which alone contains every
    variable, value set, record count, and datasource total needed here).
    """
    rdflib = _require_rdflib()
    if sources is None:
        sources = [NCCR_INSTANCES_URL]
    graph = rdflib.Graph()
    for src in sources:
        graph.parse(str(src), format="turtle")
    return graph


def list_datasources(graph) -> List[Dict[str, object]]:
    """Return each datasource with its label and total record count."""
    out: List[Dict[str, object]] = []
    for row in graph.query(_SOURCES_QUERY):
        out.append(
            {
                "source_id": str(row.sid),
                "label": str(row.label) if row.label is not None else "",
                "total_record_count": int(row.total) if row.total is not None else None,
            }
        )
    return out


def source_columns(graph, source_id: str) -> List[str]:
    """Every variable (``sourceColumn``) the metadata lists for a datasource, sorted."""
    sid = source_id.upper()
    return sorted({str(r.col) for r in graph.query(_COLUMNS_QUERY) if str(r.sid).upper() == sid})


def _build_marginals(
    graph,
    value_mode: str = "label",
    value_modes: Optional[Mapping[str, str]] = None,
    source_id: Optional[str] = None,
) -> Dict[str, Dict[str, Dict[str, object]]]:
    """Collect per-(source, variable) permissible values and optional counts.

    Returns: source_id -> column -> {label, vtype, values: {value: count-or-None}}.
    A value with ``None`` count is a permissible value with no published frequency
    (either never counted or a suppressed small cell).
    """
    if value_mode not in VALUE_MODES:
        raise ValueError("value_mode must be 'label' or 'code'")
    # value_modes: variable -> 'label' | 'code', for the variables of ``source_id`` only.
    value_modes = value_modes or {}

    acc: Dict[str, Dict[str, Dict[str, object]]] = defaultdict(dict)

    for row in graph.query(_MARGINALS_QUERY):
        sid = str(row.sid)
        col = str(row.col)
        pref = str(row.plabel) if row.plabel is not None else None
        notation = str(row.notation) if row.notation is not None else None

        mode = value_mode
        if sid.upper() == (source_id or "").upper():
            mode = value_modes.get(col, value_mode)
        if mode == "code":
            value = notation if notation is not None else pref
        else:
            value = pref if pref is not None else notation
        if value is None:
            value = "(unlabeled)"

        rc = float(row.rc) if row.rc is not None else None

        var_acc = acc[sid].get(col)
        if var_acc is None:
            var_acc = {
                "label": str(row.vlabel) if row.vlabel is not None else col,
                "vtype": str(row.stype) if row.stype is not None else "categorical",
                "values": {},
                "meta": {},  # value -> [(code, description)], for the null-code classifier
            }
            acc[sid][col] = var_acc
        desc = str(row.desc) if row.desc is not None else (pref or notation or "")
        var_acc["meta"].setdefault(value, []).append(
            (notation if notation is not None else (pref or ""), desc)
        )
        values = var_acc["values"]
        if value in values:
            if rc is not None:
                values[value] = (values[value] or 0.0) + rc
        else:
            values[value] = rc  # None when no published count

    return acc


def build_dictionary(
    graph,
    source_id: str,
    value_mode: str = "label",
    min_values: int = 2,
    no_frequency: str = "uniform",
    suppressed_fill: float = 0.0,
    value_modes: Optional[Mapping[str, str]] = None,
    null_overrides: Optional[Mapping[str, Mapping[str, object]]] = None,
) -> DataDictionary:
    """Build a :class:`DataDictionary` for a single NCCR datasource.

    Every variable with a value set is included (to abide by the complete data
    dictionary), using published ``nccr:recordCount`` frequencies where available.

    - ``no_frequency``: for a variable with *no* published counts at all —
      ``"uniform"`` (default) samples uniformly across its permissible values;
      ``"exclude"`` drops it.
    - ``suppressed_fill``: weight given to individual permissible values that lack a
      count within an otherwise-counted variable (suppressed small cells). Default
      ``0.0`` keeps them in the permissible set but unsampled; raise it to represent
      rare values at a small floor.
    - ``min_values``: skip value sets with fewer than this many permissible values.
    - ``value_modes``: per-variable override of ``value_mode`` (variable -> ``"label"`` or
      ``"code"``). A name that is not a variable of the source is a ``ConfigError``.
    - ``null_overrides``: per-code corrections for the null-code classifier, on top of the
      shipped ones (see ``nullcodes.load_overrides``). Each variable carries ``na_info``
      (summed counts, the kind of each value) for the not-applicable fraction.

    Variables that are left out are not lost silently: ``dictionary.skipped`` maps each
    one to a reason in ``SKIP_REASONS`` (variables with no value set at all included).
    """
    source_id = source_id.upper()
    if no_frequency not in ("uniform", "exclude"):
        raise ValueError("no_frequency must be 'uniform' or 'exclude'")
    value_modes = dict(value_modes or {})
    for var, mode in value_modes.items():
        if mode not in VALUE_MODES:
            raise ConfigError(
                f"value_modes.{var}: unknown value {mode!r}. Valid choices: "
                f"{', '.join(VALUE_MODES)}"
            )
    marginals = _build_marginals(
        graph, value_mode=value_mode, value_modes=value_modes, source_id=source_id
    )
    if source_id not in marginals:
        available = ", ".join(sorted(marginals)) or "(none)"
        raise ValueError(
            f"source '{source_id}' not found in metadata. Available: {available}"
        )

    # Datasource label + total records.
    label, total = source_id, None
    for ds in list_datasources(graph):
        if ds["source_id"].upper() == source_id:
            label = ds["label"] or source_id
            total = ds["total_record_count"]
            break

    all_columns = source_columns(graph, source_id)
    unknown = [v for v in value_modes if v not in all_columns]
    if unknown:
        raise ConfigError(
            unknown_message("value_modes", "variable", unknown[0], all_columns)
        )
    skipped: Dict[str, str] = {
        c: "no_value_set" for c in all_columns if c not in marginals[source_id]
    }

    overrides = merge_overrides(load_overrides(), null_overrides)
    variables: Dict[str, VariableMarginal] = {}
    for col, spec in marginals[source_id].items():
        values: Dict[str, Optional[float]] = spec["values"]
        cats = list(values.keys())
        if len(cats) < min_values:
            skipped[col] = "too_few_values"
            continue
        has_freq = any(v is not None for v in values.values())
        if has_freq:
            weights = np.asarray(
                [values[c] if values[c] is not None else suppressed_fill for c in cats],
                dtype=float,
            )
            if weights.sum() <= 0:
                skipped[col] = "zero_counts"
                continue
            freq_source = "published"
        else:
            if no_frequency == "exclude":
                skipped[col] = "no_counts_excluded"
                continue
            weights = np.ones(len(cats), dtype=float)  # uniform over permissible values
            freq_source = "uniform"
        variables[col] = VariableMarginal(
            name=col,
            label=spec["label"],
            vtype=spec["vtype"],
            categories=cats,
            weights=weights,
            frequency_source=freq_source,
            na_info=variable_na_info(
                values, spec["meta"], source=source_id, variable=col, total=total,
                overrides=overrides,
            ),
        )

    if not variables:
        raise ValueError(f"source '{source_id}' has no usable variables")

    return DataDictionary(
        name=f"NCCR {label} [{source_id}]",
        source="NCCR Data Platform (nccr-metadata)",
        version="DATMM 6.0.0",
        n_records=total,
        variables=variables,
        source_id=source_id,
        skipped=dict(sorted(skipped.items())),
        notes=(
            "Built from published NCCR RDF metadata (nccr_instances.ttl). All "
            "permissible value sets are included; variables with published "
            "nccr:recordCount use those frequencies, variables without any are "
            "sampled uniformly (frequency_source='uniform'). No individual-level "
            "data used."
        ),
    )


def load_nccr_dictionary(
    source_id: str,
    sources: Optional[Sequence[Union[str, Path]]] = None,
    value_mode: str = "label",
    min_values: int = 2,
    no_frequency: str = "uniform",
) -> DataDictionary:
    """Convenience: parse Turtle and build the dictionary for ``source_id``.

    Example
    -------
    >>> d = load_nccr_dictionary("CTC")            # from the published metadata
    >>> d = load_nccr_dictionary("CTC", ["nccr_instances.ttl"])  # from a local file
    """
    graph = load_graph(sources)
    return build_dictionary(
        graph, source_id, value_mode=value_mode, min_values=min_values,
        no_frequency=no_frequency,
    )
