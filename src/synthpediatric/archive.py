"""Zip packaging of the data CSV for upload.

A run with ``outputs.archive: zip`` writes the cohort CSV, packs it as the single entry of
``<base>.zip`` and checks the zip. The aggregate reports (coverage, conformance, fidelity,
manifest, dictionary) are never put in the zip. ``<base>`` is ``outputs.archive_name`` if
given, else the source id of the run, else the config name, else ``cohort``; the entry is
``<base>.csv``, so an extracted file is self-describing.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .config import ConfigError, check_choice

ARCHIVE_CHOICES = ("none", "zip")
_CHUNK = 1 << 20
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_base(text: Any) -> str:
    base = _UNSAFE.sub("_", str(text or "")).strip("._-")
    return base


def archive_base(name: Optional[str], source: Any, config_name: Any) -> str:
    """The base name for the zip and its CSV entry (no extension)."""
    if name:
        stem = name[:-4] if name.lower().endswith(".zip") else name
        return sanitize_base(stem) or "cohort"
    return sanitize_base(source) or sanitize_base(config_name) or "cohort"


def resolve_archive(archive: Optional[str], fmt: str) -> str:
    """Validate the archive mode against the cohort format; returns 'none' or 'zip'."""
    mode = check_choice("outputs.archive", archive or "none", ARCHIVE_CHOICES)
    if mode == "zip" and fmt in ("parquet", "pq"):
        raise ConfigError(
            "outputs.archive: 'zip' applies to csv output only, got format 'parquet'. "
            "Use format: csv, or archive: none"
        )
    return mode


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_csv(csv_path: Path, zip_path: Path, keep_csv: bool) -> Dict[str, Any]:
    """Pack ``csv_path`` as the only entry of ``zip_path``, verify it, return manifest facts.

    The CSV is streamed into the zip (ZIP64, deflate), so a large file is not held in
    memory. The bare CSV is removed unless ``keep_csv``.
    """
    csv_size = csv_path.stat().st_size
    digest = sha256_file(csv_path)
    entry = csv_path.name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.write(csv_path, arcname=entry)
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if zf.testzip() is not None or len(infos) != 1:
            raise RuntimeError(f"zip integrity check failed for {zip_path}")
        if infos[0].filename != entry or infos[0].file_size != csv_size:
            raise RuntimeError(
                f"zip entry mismatch for {zip_path}: expected {entry} ({csv_size} bytes)"
            )
    if not keep_csv:
        csv_path.unlink()
    return {
        "archive": zip_path.name,
        "entry": entry,
        "csv_bytes": csv_size,
        "zip_bytes": zip_path.stat().st_size,
        "csv_sha256": digest,
        "csv_kept": bool(keep_csv),
    }


def outputs_archive_options(outputs: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    o = outputs or {}
    return {
        "archive": o.get("archive"),
        "archive_name": o.get("archive_name"),
        "keep_csv": bool(o.get("keep_csv", False)),
    }
