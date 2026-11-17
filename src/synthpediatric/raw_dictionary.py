"""The NCCR RAW-JSON data dictionaries: the full column list of each source.

``nccr-metadata/RAW-JSON/<source>_metadata.json`` lists every column of a source
(``Dictionary_Elements``), starting with the primary key ``nccrId``. The RDF metadata
(``nccr_instances.ttl``) carries the value sets but differs a little in its column list, so a
linked run uses the union of both (``reconcile``): the RAW-JSON order first, then the columns
only the RDF metadata knows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .config import ConfigError

KEY = "nccrId"
TUMOR_KEY = "tumorRecordNumber"


@dataclass(frozen=True)
class RawColumn:
    name: str
    semantic_type: Optional[str]
    field_length: Optional[int]
    description: str = ""


@dataclass
class RawDictionary:
    source: str
    path: str
    columns: List[RawColumn] = field(default_factory=list)

    @property
    def names(self) -> List[str]:
        return [c.name for c in self.columns]

    def get(self, name: str) -> Optional[RawColumn]:
        for c in self.columns:
            if c.name == name:
                return c
        return None


@dataclass
class Reconciliation:
    columns: List[str]
    raw_only: List[str]
    ttl_only: List[str]


def _length(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_raw_dictionary(directory: Union[str, Path], source: str) -> RawDictionary:
    """Read ``<directory>/<source lower>_metadata.json``; the first column must be ``nccrId``."""
    path = Path(directory) / f"{source.lower()}_metadata.json"
    if not path.is_file():
        raise ConfigError(f"linked.dictionaries: RAW-JSON dictionary not found: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        elements = doc["Dictionary_Elements"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ConfigError(f"{path}: not a RAW-JSON dictionary (Dictionary_Elements): {exc}")
    columns: List[RawColumn] = []
    seen = set()
    for element in elements:
        name = element.get("Column_Name_at_Source")
        if not name or name in seen:
            continue
        seen.add(name)
        dtype = element.get("Column_DataType_at_Source") or {}
        columns.append(
            RawColumn(
                name=name,
                semantic_type=dtype.get("Semantic_Type"),
                field_length=_length(dtype.get("Field_Length")),
                description=str(element.get("Item_Description") or ""),
            )
        )
    if not columns or columns[0].name != KEY:
        raise ConfigError(f"{path}: the first dictionary element must be '{KEY}'")
    return RawDictionary(source=source.upper(), path=str(path), columns=columns)


def reconcile(raw: RawDictionary, ttl_names: Sequence[str]) -> Reconciliation:
    """The full column list of a source: ``nccrId``, the tumor key if any, the rest.

    Order: ``nccrId``; ``tumorRecordNumber`` (sources that have it); the other RAW-JSON
    columns in RAW-JSON order; then the columns only the RDF metadata has, sorted.
    """
    raw_names = raw.names
    ttl = set(ttl_names)
    raw_set = set(raw_names)
    ttl_only = sorted(ttl - raw_set)
    raw_only = [n for n in raw_names if n not in ttl]
    head = [KEY]
    if TUMOR_KEY in raw_set:
        head.append(TUMOR_KEY)
    rest = [n for n in raw_names if n not in head]
    return Reconciliation(columns=head + rest + ttl_only, raw_only=raw_only, ttl_only=ttl_only)


def key_definition(raw: RawDictionary, name: str) -> Dict[str, Any]:
    """Type and length of a key column as the dictionary defines it."""
    col = raw.get(name)
    if col is None:
        raise ConfigError(f"{raw.path}: key column '{name}' is not in the dictionary")
    return {"name": name, "type": col.semantic_type, "length": col.field_length}
