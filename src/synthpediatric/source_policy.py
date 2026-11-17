"""Per-source policy: documented defaults for each NCCR source, overridable in a config.

Every NCCR source is generated as an *unlinked, single-source table* unless the config has a
``linked:`` block (see ``synthpediatric.linked``). Three behaviours
depend on the source, so they live here, in one table, instead of in the rules:

- ``no_frequency``: what to do with columns that have a value set but no published count
  anywhere (invented by uniform fallback). MCE has 359 of them, so MCE blanks them.
- ``value_modes``: per-variable ``label`` / ``code`` choice. PHARM
  ``medicationDispenseDuration`` publishes the record count as the value's label and the
  real day value as its code, so it is read in ``code`` mode.
- ``survival``: ``allow`` or ``refuse``. Survival makes a time and an event per row, which
  only means something when a row is a person. Only the CTC registry table is one.

Precedence for each setting, highest first: a value the user sets explicitly in the config
(top-level ``no_frequency`` / ``value_mode`` / ``value_modes``), then the config's
``source_policy:`` block, then the built-in default below, then the generic default.
``resolve_source_policy`` returns the effective value of each setting and who supplied it,
and the manifest records that.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .config import (
    NO_FREQUENCY_MODES,
    VALUE_MODES,
    ConfigError,
    check_choice,
    check_keys,
)

TABLE_TYPE = "unlinked_single_source"
TABLE_LABEL = "unlinked, single-source table"
LINKAGE_STATEMENT = (
    "Unlinked, single-source table. Rows cannot be joined to rows of any other NCCR source: "
    "the published metadata has no participant key (dataRequestPatientId is not a variable "
    "in nccr_instances.ttl), so any join would be invented."
)

LINKED_TABLE_TYPE = "linked_source"
LINKED_TABLE_LABEL = "linked table"


def linked_statement(source: str, parent: str = "CTC") -> str:
    """The linkage text of a table written by a linked run."""
    if source == parent:
        return (
            "Linked table (parent). nccrId is a synthetic primary key, one per patient, and "
            "(nccrId, tumorRecordNumber) is unique per row. The other NCCR sources of this run "
            "join to it on nccrId; the links are generated, not observed."
        )
    extra = " and tumorRecordNumber" if source == "ABM" else ""
    return (
        f"Linked table (child of {parent}). Rows join to {parent} on nccrId{extra}. The "
        "links are generated, not observed: there is no real patient behind any key."
    )


# A "person table": one row stands for one patient's cancer record and the source has a
# vital status, which is what survival needs. Only the CTC registry table qualifies. ABM is
# one row per tumor but holds area measures, COG and MCE are enrollment flags, the claims
# tables (MCD, MCP, PHARM) are one row per claim or fill, RO per radiation record, CCDI per
# resource mapping.
PERSON_TABLES = ("CTC",)

SURVIVAL_CHOICES = ("allow", "refuse")
POLICY_KEYS = ("no_frequency", "value_modes", "survival")

# Built-in defaults. A source not listed here has only the generic defaults.
DEFAULT_POLICIES: Dict[str, Dict[str, Any]] = {
    "CTC": {"survival": "allow"},
    "ABM": {"survival": "refuse"},
    "CCDI": {"survival": "refuse"},
    "COG": {"survival": "refuse"},
    "MCD": {"survival": "refuse"},
    "MCE": {"no_frequency": "nullify", "survival": "refuse"},
    "MCP": {"survival": "refuse"},
    "PHARM": {
        "value_modes": {"medicationDispenseDuration": "code"},
        "survival": "refuse",
    },
    "RO": {"survival": "refuse"},
}

# ``na_fraction`` (see ``nullcodes``) is on for every NCCR source (generic default). A JSON
# dictionary has no source policy at all, so it never gets the fraction.
GENERIC = {"no_frequency": "uniform", "value_mode": "label", "na_fraction": "on"}


def normalize_source_policy(where: str, value: Any) -> Dict[str, Any]:
    """Shape-check a config's ``source_policy:`` block (names are checked at run time)."""
    check_keys(where, value, POLICY_KEYS)
    out: Dict[str, Any] = {}
    if "no_frequency" in value:
        out["no_frequency"] = check_choice(
            f"{where}.no_frequency", value["no_frequency"], NO_FREQUENCY_MODES
        )
    if "survival" in value:
        out["survival"] = check_choice(f"{where}.survival", value["survival"], SURVIVAL_CHOICES)
    if "value_modes" in value:
        out["value_modes"] = normalize_value_modes(f"{where}.value_modes", value["value_modes"])
    return out


def normalize_value_modes(where: str, value: Any) -> Dict[str, str]:
    """A mapping of variable name -> ``label`` | ``code``."""
    if not isinstance(value, Mapping) or not value:
        raise ConfigError(f"{where}: expected a non-empty mapping of variable -> label|code")
    return {
        str(var): check_choice(f"{where}.{var}", mode, VALUE_MODES) for var, mode in value.items()
    }


NA_FRACTION_KEYS = ("mode", "min_share", "variables", "overrides")


def _on_off(where: str, value: Any, choices: Sequence[str]) -> str:
    """``on``/``off``/``auto``; YAML turns bare on/off into booleans, so those are accepted."""
    if value is True:
        value = "on"
    elif value is False:
        value = "off"
    return check_choice(where, value, choices)


def normalize_na_fraction(where: str, value: Any) -> Dict[str, Any]:
    """Shape-check the ``na_fraction`` setting: on / off, or a block.

    ``mode`` (on | off), ``min_share`` (0 to 1), ``variables`` (name -> on | off | auto) and
    ``overrides`` (path of a null-code overrides file). Variable names are checked later,
    against the metadata. Only the keys given are written.
    """
    from .config import as_number, as_str
    from .nullcodes import NA_MODES, NA_VARIABLE_CHOICES

    if value is True or value is False or isinstance(value, str):
        return {"mode": _on_off(where, value, NA_MODES)}
    check_keys(where, value, NA_FRACTION_KEYS)
    out: Dict[str, Any] = {}
    if "mode" in value:
        out["mode"] = _on_off(f"{where}.mode", value["mode"], NA_MODES)
    if "min_share" in value:
        share = as_number(f"{where}.min_share", value["min_share"], nonneg=True)
        if share > 1:
            raise ConfigError(f"{where}.min_share: must be between 0 and 1, got {share}")
        out["min_share"] = share
    if "variables" in value:
        table = value["variables"]
        if not isinstance(table, Mapping) or not table:
            raise ConfigError(f"{where}.variables: expected a non-empty mapping of variable -> "
                              "on|off|auto")
        out["variables"] = {
            str(v): _on_off(f"{where}.variables.{v}", m, NA_VARIABLE_CHOICES)
            for v, m in table.items()
        }
    if "overrides" in value:
        out["overrides"] = as_str(f"{where}.overrides", value["overrides"])
    return out


def _entry(value: Any, supplied_by: str) -> Dict[str, Any]:
    return {"value": value, "supplied_by": supplied_by}


def resolve_source_policy(
    source_id: Optional[str],
    *,
    no_frequency: Optional[str] = None,
    value_mode: Optional[str] = None,
    value_modes: Optional[Mapping[str, str]] = None,
    override: Optional[Mapping[str, Any]] = None,
    columns: Optional[Sequence[str]] = None,
    na_fraction: Optional[str] = None,
) -> Dict[str, Any]:
    """Effective settings for one run.

    ``no_frequency``, ``value_mode`` and ``value_modes`` are what the user set explicitly
    (None / empty when not set). ``override`` is the config's ``source_policy`` block.
    ``columns`` are the source's variables: a policy default naming a variable the metadata
    does not have is left out and reported under ``warnings``; a name the user gave is
    checked later, by the loader.

    Returns ``source``, ``known_source``, ``person_table``, ``no_frequency``, ``survival``,
    ``value_mode`` (each ``{value, supplied_by}``), ``value_modes`` (variable ->
    ``{value, supplied_by}``) and ``warnings``. ``supplied_by`` is ``config`` (set
    explicitly), ``config.source_policy`` (the override block), ``policy`` (built-in
    default) or ``default`` (generic).
    """
    sid = source_id.upper() if source_id else None
    defaults = DEFAULT_POLICIES.get(sid or "", {})
    override = override or {}
    warnings: List[str] = []

    if no_frequency is not None:
        nf = _entry(no_frequency, "config")
    elif "no_frequency" in override:
        nf = _entry(override["no_frequency"], "config.source_policy")
    elif "no_frequency" in defaults:
        nf = _entry(defaults["no_frequency"], "policy")
    else:
        nf = _entry(GENERIC["no_frequency"], "default")

    if "survival" in override:
        sv = _entry(override["survival"], "config.source_policy")
    elif "survival" in defaults:
        sv = _entry(defaults["survival"], "policy")
    else:
        sv = _entry("allow", "default")

    if value_mode is not None:
        vm = _entry(value_mode, "config")
    else:
        vm = _entry(GENERIC["value_mode"], "default")

    per_var: Dict[str, Dict[str, Any]] = {}
    for var, mode in defaults.get("value_modes", {}).items():
        if columns is not None and var not in columns:
            warnings.append(
                f"source_policy: default value mode for '{var}' ({mode}) not applied: the "
                f"metadata has no variable '{var}' in source {sid}"
            )
            continue
        per_var[var] = _entry(mode, "policy")
    if value_mode is not None:  # an explicit global choice beats the built-in default
        per_var = {v: e for v, e in per_var.items() if e["supplied_by"] != "policy"}
    for var, mode in (override.get("value_modes") or {}).items():
        per_var[var] = _entry(mode, "config.source_policy")
    for var, mode in (value_modes or {}).items():
        per_var[var] = _entry(mode, "config")

    if na_fraction is not None:
        na = _entry(na_fraction, "config")
    elif "na_fraction" in defaults:
        na = _entry(defaults["na_fraction"], "policy")
    else:
        na = _entry(GENERIC["na_fraction"], "default")

    return {
        "na_fraction": na,
        "source": sid,
        "known_source": sid in DEFAULT_POLICIES,
        "person_table": sid in PERSON_TABLES,
        "no_frequency": nf,
        "survival": sv,
        "value_mode": vm,
        "value_modes": dict(sorted(per_var.items())),
        "warnings": warnings,
    }


def loader_value_modes(policy: Mapping[str, Any]) -> Dict[str, str]:
    """The ``variable -> mode`` mapping to hand to ``build_dictionary``."""
    return {var: e["value"] for var, e in policy["value_modes"].items()}


def policy_supplied(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """What the built-in policy (not the user) decided, for the config hash.

    Empty for CTC and for any run whose settings all came from the config, so those
    hashes are the same as before source policies existed.
    """
    out: Dict[str, Any] = {}
    if policy["no_frequency"]["supplied_by"] == "policy":
        out["no_frequency"] = policy["no_frequency"]["value"]
    modes = {
        v: e["value"] for v, e in policy["value_modes"].items() if e["supplied_by"] == "policy"
    }
    if modes:
        out["value_modes"] = modes
    if policy["survival"]["supplied_by"] == "policy" and policy["survival"]["value"] == "refuse":
        out["survival"] = "refuse"
    return out


def survival_refusal(policy: Mapping[str, Any]) -> Optional[str]:
    """The config error message when survival is refused for this source, else None."""
    if policy["survival"]["value"] != "refuse":
        return None
    sid = policy["source"]
    how = (
        "set by the config's source_policy"
        if policy["survival"]["supplied_by"] == "config.source_policy"
        else "the built-in policy for this source"
    )
    return (
        f"targets.survival: refused for source '{sid}'. Survival adds a time and an event to "
        f"each row, which only means something when a row is a person, and only the CTC "
        f"registry table is one ({how}). To generate it anyway, add "
        f"'source_policy: {{survival: allow}}' to the config"
    )

