"""Load, validate and normalize generation configs (YAML or JSON).

A config says *which rules apply, with what parameters, under which profile*. This
module owns the file formats and the top-level schema; ``synthpediatric.rules`` owns
the per-rule parameter schemas and the profile bundles.

``normalize_config`` turns any accepted spelling of a config into ONE canonical form:

- the spec layout (``targets:`` / ``constraints:`` / ``cohort:`` ...) and the legacy flat
  recipe keys (``override_marginals``, ``survival``, ``rules: path.json``) both land in
  the same place, with defaults filled in;
- the canonical form is itself a valid config, so ``normalize(normalize(x)) == normalize(x)``;
- ``config_hash`` hashes the canonical form, so YAML and equivalent JSON hash identically.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union


class ConfigError(ValueError):
    """A config is malformed. The message names the offending key and valid choices."""


DEFAULT_N = 1000
NO_FREQUENCY_MODES = ("uniform", "nullify", "suppress")
_NO_FREQUENCY_ALIASES = {"exclude": "suppress"}  # legacy spelling from build_dictionary
MISSINGNESS_MODES = ("none", "realistic")
VALUE_MODES = ("label", "code")
OUTPUT_FORMATS = ("csv", "parquet")
DEFAULT_SUPPRESSION_MIN = 16
# Longest list of valid names an error message prints before it truncates.
MAX_LISTED_CHOICES = 15

# Sections of the spec layout that live under ``targets:``.
TARGET_KEYS = ("marginals", "overrides", "joints", "survival")
# Legacy flat keys -> the canonical (section, key) they move to.
_LEGACY_KEYS = {"override_marginals": "marginals", "survival": "survival"}
TOP_LEVEL_KEYS = (
    "name", "metadata", "source", "n", "seed", "profile", "value_mode", "no_frequency",
    "missingness", "strict", "rules", "cohort", "targets", "oversample", "constraints",
    "validate", "outputs",
)
LEGACY_TOP_LEVEL_KEYS = tuple(_LEGACY_KEYS)


# --------------------------------------------------------------------------- #
# Small validation helpers (shared with rules.py)
# --------------------------------------------------------------------------- #

def fmt_choices(choices: Iterable[object]) -> str:
    return ", ".join(str(c) for c in choices)


def fmt_valid(choices: Iterable[object], limit: int = MAX_LISTED_CHOICES) -> str:
    """List valid names for a message: all of them, or the first ``limit`` plus the total."""
    names = [str(c) for c in choices]
    if len(names) <= limit:
        return ", ".join(names)
    return f"{', '.join(names[:limit])}, ... ({len(names)} in total)"


def unknown_message(
    where: str, kind: str, value: object, choices: Iterable[object], note: str = ""
) -> str:
    """``<where>: unknown <kind> '<value>'. Did you mean '<closest>'? Valid <kind>s: ...``."""
    names = [str(c) for c in choices]
    close = difflib.get_close_matches(str(value), names, n=1)
    hint = f" Did you mean '{close[0]}'?" if close else ""
    plural = "categories" if kind == "category" else f"{kind}s"
    return f"{where}: unknown {kind} '{value}'{note}.{hint} Valid {plural}: {fmt_valid(names)}"


def is_legacy_style(raw: Mapping[str, Any]) -> bool:
    """True for a pre-YAML recipe: it uses a legacy flat key (``override_marginals``,
    top-level ``survival``, or ``rules: path.json``)."""
    return any(k in raw for k in LEGACY_TOP_LEVEL_KEYS) or isinstance(raw.get("rules"), str)


def effective_strict(raw: Mapping[str, Any], canonical: Mapping[str, Any]) -> bool:
    """The strictness a run uses: the config's ``strict``, else on, except legacy recipes."""
    if "strict" in canonical:
        return bool(canonical["strict"])
    return not is_legacy_style(raw)


def check_keys(
    where: str,
    mapping: Mapping[str, Any],
    allowed: Sequence[str],
    required: Sequence[str] = (),
) -> None:
    if not isinstance(mapping, Mapping):
        raise ConfigError(f"{where}: expected a mapping, got {type(mapping).__name__}")
    for key in mapping:
        if key not in allowed:
            raise ConfigError(f"{where}: unknown key '{key}'. Valid keys: {fmt_choices(allowed)}")
    for key in required:
        if key not in mapping:
            raise ConfigError(f"{where}: missing required key '{key}'")


def check_choice(where: str, value: Any, choices: Sequence[str]) -> str:
    if value not in choices:
        raise ConfigError(
            f"{where}: unknown value {value!r}. Valid choices: {fmt_choices(choices)}"
        )
    return value


def as_int(where: str, value: Any, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where}: expected an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where}: must be >= {minimum}, got {value}")
    return value


def as_number(where: str, value: Any, positive: bool = False, nonneg: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: expected a number, got {value!r}")
    if positive and value <= 0:
        raise ConfigError(f"{where}: must be > 0, got {value}")
    if nonneg and value < 0:
        raise ConfigError(f"{where}: must be >= 0, got {value}")
    return float(value)


def as_str(where: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def as_label(where: str, value: Any) -> Any:
    """A category label. YAML 1.1 turns bare Yes/No/on/off into booleans: refuse them."""
    if isinstance(value, bool):
        raise ConfigError(
            f"{where}: {value!r} was parsed as a YAML boolean; quote the value "
            "(e.g. \"Yes\" / \"No\") so it stays a text label"
        )
    if isinstance(value, (Mapping, list)) or value is None:
        raise ConfigError(f"{where}: expected a scalar label, got {value!r}")
    return value


# --------------------------------------------------------------------------- #
# File loading
# --------------------------------------------------------------------------- #

def _yaml_module():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ConfigError(
            "YAML configs require PyYAML: pip install 'synthpediatric[yaml]'"
        ) from exc
    return yaml


def read_structured(path: Union[str, Path]) -> Any:
    """Read a .json / .yaml / .yml file (unknown suffix: try JSON, then YAML)."""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"file not found: {p}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text)
        if suffix in (".yaml", ".yml"):
            return _yaml_module().safe_load(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return _yaml_module().safe_load(text)
    except ConfigError:
        raise
    except Exception as exc:  # json / yaml syntax errors
        kind = suffix.lstrip(".") or "JSON/YAML"
        raise ConfigError(f"{p}: could not parse as {kind}: {exc}") from exc


def load_config(source: Union[Mapping[str, Any], str, Path]) -> Dict[str, Any]:
    """Return the raw (un-normalized) config mapping from a dict or a YAML/JSON file."""
    raw = dict(source) if isinstance(source, Mapping) else read_structured(source)
    if not isinstance(raw, Mapping):
        raise ConfigError(f"config must be a mapping at the top level, got {type(raw).__name__}")
    return dict(raw)


# --------------------------------------------------------------------------- #
# Normalization (top level)
# --------------------------------------------------------------------------- #

def _validate_block(value: Any) -> Dict[str, Any]:
    """Shape-check the reserved ``validate:`` block. No metric is evaluated here."""
    check_keys("validate", value, ("fidelity", "utility", "privacy", "suppression_min"))
    out: Dict[str, Any] = {}
    for key in ("fidelity", "utility", "privacy"):
        items = value.get(key, [])
        if not isinstance(items, list):
            raise ConfigError(f"validate.{key}: expected a list of metric names, got {items!r}")
        out[key] = [as_str(f"validate.{key}[{i}]", item) for i, item in enumerate(items)]
    out["suppression_min"] = as_int(
        "validate.suppression_min", value.get("suppression_min", DEFAULT_SUPPRESSION_MIN), 1
    )
    return out


def _outputs_block(value: Any) -> Dict[str, Any]:
    check_keys("outputs", value, ("dir", "format"))
    out: Dict[str, Any] = {}
    if "dir" in value:
        out["dir"] = as_str("outputs.dir", value["dir"])
    if "format" in value:
        out["format"] = check_choice("outputs.format", value["format"], OUTPUT_FORMATS)
    return out


def _collect_sections(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Gather rule sections from the spec layout and the legacy flat keys."""
    sections: Dict[str, Any] = {}

    def put(name: str, value: Any, origin: str) -> None:
        if value is None or value == {} or value == [] or value == "":
            return  # an empty section means "not configured" (as in pre-YAML recipes)
        if name in sections:
            raise ConfigError(
                f"{origin}: duplicates the '{name}' section given elsewhere in the config"
            )
        sections[name] = value

    targets = raw.get("targets")
    if targets is not None:
        check_keys("targets", targets, TARGET_KEYS)
        for key, value in targets.items():
            put(key, value, f"targets.{key}")
    for legacy, name in _LEGACY_KEYS.items():
        if legacy in raw:
            put(name, raw[legacy], legacy)
    for key in ("cohort", "oversample"):
        if key in raw:
            put(key, raw[key], key)
    if "constraints" in raw:
        put("constraints", raw["constraints"], "constraints")
    if isinstance(raw.get("rules"), str):  # legacy: rules: path/to/rules.json
        put("constraints", {"file": raw["rules"]}, "rules")
    return sections


def normalize_config(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a raw config and return its canonical form (see module docstring)."""
    from . import rules  # local import: rules depends on this module's helpers

    check_keys("config", raw, TOP_LEVEL_KEYS + LEGACY_TOP_LEVEL_KEYS)

    cfg: Dict[str, Any] = {}
    if raw.get("name") is not None:
        cfg["name"] = as_str("name", raw["name"])
    cfg["metadata"] = as_str("metadata", raw.get("metadata", "remote"))
    if raw.get("source") is not None:
        cfg["source"] = as_str("source", raw["source"])
    cfg["n"] = as_int("n", raw.get("n", DEFAULT_N), 1)
    seed = raw.get("seed")
    cfg["seed"] = None if seed is None else as_int("seed", seed)
    cfg["value_mode"] = check_choice("value_mode", raw.get("value_mode", "label"), VALUE_MODES)

    mode = raw.get("no_frequency", "uniform")
    mode = _NO_FREQUENCY_ALIASES.get(mode, mode)
    cfg["no_frequency"] = check_choice("no_frequency", mode, NO_FREQUENCY_MODES)

    missingness = check_choice("missingness", raw.get("missingness", "none"), MISSINGNESS_MODES)
    if missingness == "realistic":
        raise ConfigError(
            "missingness: 'realistic' is reserved but not implemented yet; use 'none' "
            "(records are generated without missing values)"
        )
    cfg["missingness"] = missingness

    if "strict" in raw:  # only written when given: absent means "default for this style"
        if not isinstance(raw["strict"], bool):
            raise ConfigError(f"strict: expected true or false, got {raw['strict']!r}")
        cfg["strict"] = raw["strict"]

    sections = _collect_sections(raw)
    toggles = raw.get("rules") or {}
    if isinstance(toggles, str):
        toggles = {}
    profile, toggles, params = rules.normalize_rules(raw.get("profile"), toggles, sections)
    cfg["profile"] = profile
    cfg["rules"] = toggles

    # Canonical layout: targets.* for distributional rules, flat for the rest.
    targets_out = {k: params[k] for k in TARGET_KEYS if k in params}
    if targets_out:
        cfg["targets"] = targets_out
    for key in ("cohort", "oversample", "constraints"):
        if key in params:
            cfg[key] = params[key]

    if raw.get("validate") is not None:
        cfg["validate"] = _validate_block(raw["validate"])
    if raw.get("outputs") is not None:
        cfg["outputs"] = _outputs_block(raw["outputs"])
    return cfg


def config_hash(
    canonical: Mapping[str, Any], resolved_rules: Optional[List[Dict[str, Any]]] = None
) -> str:
    """SHA-256 of the canonical config (plus the resolved rule list when given)."""
    payload = {"config": canonical, "resolved_rules": resolved_rules}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def file_sha256(path: Union[str, Path]) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
