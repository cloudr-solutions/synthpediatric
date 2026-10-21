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
from typing import Dict, List, Optional, Sequence, Union

import numpy as np

from .dictionary import DataDictionary, VariableMarginal

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
SELECT ?sid ?col ?vlabel ?stype ?notation ?plabel ?rc WHERE {
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
}
"""

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


def _build_marginals(
    graph, value_mode: str = "label"
) -> Dict[str, Dict[str, Dict[str, object]]]:
    """Collect per-(source, variable) permissible values and optional counts.

    Returns: source_id -> column -> {label, vtype, values: {value: count-or-None}}.
    A value with ``None`` count is a permissible value with no published frequency
    (either never counted or a suppressed small cell).
    """
    if value_mode not in ("label", "code"):
        raise ValueError("value_mode must be 'label' or 'code'")

    acc: Dict[str, Dict[str, Dict[str, object]]] = defaultdict(dict)

    for row in graph.query(_MARGINALS_QUERY):
        sid = str(row.sid)
        col = str(row.col)
        pref = str(row.plabel) if row.plabel is not None else None
        notation = str(row.notation) if row.notation is not None else None

        if value_mode == "code":
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
            }
            acc[sid][col] = var_acc
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
    """
    source_id = source_id.upper()
    if no_frequency not in ("uniform", "exclude"):
        raise ValueError("no_frequency must be 'uniform' or 'exclude'")
    marginals = _build_marginals(graph, value_mode=value_mode)
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

    variables: Dict[str, VariableMarginal] = {}
    for col, spec in marginals[source_id].items():
        values: Dict[str, Optional[float]] = spec["values"]
        cats = list(values.keys())
        if len(cats) < min_values:
            continue
        has_freq = any(v is not None for v in values.values())
        if has_freq:
            weights = np.asarray(
                [values[c] if values[c] is not None else suppressed_fill for c in cats],
                dtype=float,
            )
            if weights.sum() <= 0:
                continue
            freq_source = "published"
        else:
            if no_frequency == "exclude":
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
        )

    if not variables:
        raise ValueError(f"source '{source_id}' has no usable variables")

    return DataDictionary(
        name=f"NCCR {label} [{source_id}]",
        source="NCCR Data Platform (nccr-metadata)",
        version="DATMM 6.0.0",
        n_records=total,
        variables=variables,
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
