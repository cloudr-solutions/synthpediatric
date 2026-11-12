"""Config-driven generation runs: one config composes the whole pipeline.

A config (YAML or JSON, or a dict) names the metadata source, a ``profile`` (how many
rules are on by default), and the parameters of each rule: marginals, overrides, cohort,
oversample, joints, constraints, survival. See ``synthpediatric.rules`` for the rule
registry and execution order, ``synthpediatric.config`` for the schema, and
``docs/config-and-rules.md`` for the full specification.

``run_recipe`` executes the pipeline; ``write_run`` writes the cohort plus a coverage
report, a conformance check, a fidelity scorecard, the data dictionary, and a
reproducibility manifest (resolved profile, resolved rule list, applied oversampling
factors, config hash). The config is the reproducible artifact: rerun it next year
against refreshed metadata and you get a comparable synthetic cohort.

Pre-YAML JSON recipes (``override_marginals``, ``oversample``, ``rules: path.json``,
``survival``, ``cohort``) are still accepted and normalize to the same canonical config.
"""

from __future__ import annotations

import json
import platform as _platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Union

from .calibrate import generate_calibrated
from .config import ConfigError, config_hash, effective_strict, load_config, normalize_config
from .conformance import conformance_report, coverage_report
from .dictionary import DataDictionary
from .evaluate import marginal_fidelity, overall_score
from .generate import generate
from .rules import Context, resolve_rules, run_preflight, run_stage

_REMOTE = ("remote", "nccr")


def _load_dictionary(cfg: Mapping[str, Any]) -> DataDictionary:
    metadata = str(cfg["metadata"])
    is_rdf = metadata.lower() in _REMOTE or metadata.lower().endswith(".ttl")
    if not is_rdf:
        return DataDictionary.load(metadata)

    source = cfg.get("source")
    if not source:
        raise ConfigError("source: required when loading NCCR RDF metadata (e.g. source: CTC)")
    from .nccr_rdf import build_dictionary, load_graph

    sources = None if metadata.lower() in _REMOTE else [metadata]
    graph = load_graph(sources)
    # Always load with the uniform fallback; the `no_frequency` mode is applied below.
    return build_dictionary(graph, source, value_mode=cfg["value_mode"], no_frequency="uniform")


def _uniform_variables(d: DataDictionary) -> List[str]:
    return [
        n for n, v in d.variables.items()
        if getattr(v, "frequency_source", "published") == "uniform"
    ]


def _without(d: DataDictionary, names: List[str]) -> DataDictionary:
    kept = {n: v for n, v in d.variables.items() if n not in names}
    if not kept:
        raise ConfigError("no_frequency: 'suppress' would remove every variable")
    return DataDictionary(
        name=d.name, source=d.source, version=d.version, n_records=d.n_records,
        variables=kept, notes=d.notes,
    )


def run_recipe(recipe: Union[Mapping[str, Any], str, Path]) -> Dict[str, Any]:
    """Execute a config (YAML/JSON path or dict) and return a result bundle.

    Keys: dictionary, result, data, recipe (as given), config (canonical),
    config_sha256, profile, strict, rules (resolved rule list with per-rule details), warnings,
    oversampling, no_frequency, nullified, input_files.
    """
    raw = load_config(recipe)
    cfg = normalize_config(raw)
    resolved = resolve_rules(cfg)
    sha = config_hash(cfg, resolved)

    d = _load_dictionary(cfg)
    mode = cfg["no_frequency"]
    uniform_vars = _uniform_variables(d)
    loaded = d
    if mode == "suppress" and uniform_vars:
        d = _without(d, uniform_vars)

    strict = effective_strict(raw, cfg)
    # References are checked against the dictionary as loaded: a suppressed variable has no
    # published frequency, but a marginals/overrides table may still supply one.
    ctx = Context(config=cfg, dictionary=d, strict=strict, base_dictionary=loaded)
    # Every reference in the config is checked against the dictionary here, before any record
    # is sampled; ConfigError reaches the caller before write_run creates a file.
    run_stage(ctx, resolved, "dictionary")
    run_preflight(ctx, resolved)
    run_stage(ctx, resolved, "generate")

    n, seed = cfg["n"], cfg["seed"]
    if ctx.joint is not None:
        result = generate_calibrated(ctx.dictionary, ctx.joint, n, rng=seed, ruleset=ctx.ruleset)
    else:
        result = generate(ctx.dictionary, n=n, rng=seed, ruleset=ctx.ruleset)
    ctx.df = result.data

    run_stage(ctx, resolved, "post")

    nullified: List[str] = []
    if mode == "nullify":
        # Sampled first (so rules and the random stream are unchanged), blanked at the end.
        nullified = [v for v in uniform_vars if v in ctx.dictionary.variables]
        for name in nullified:
            ctx.df[name] = None

    return {
        "dictionary": ctx.dictionary, "result": result, "data": ctx.df,
        "recipe": raw, "config": cfg, "config_sha256": sha, "profile": cfg["profile"],
        "strict": strict, "rules": resolved, "warnings": ctx.warnings,
        "oversampling": ctx.oversampling,
        "no_frequency": {"mode": mode, "variables": uniform_vars},
        "nullified": nullified, "input_files": ctx.input_files,
    }


def _dictionary_to_json(d: DataDictionary) -> Dict[str, Any]:
    return {
        "name": d.name, "source": d.source, "version": d.version,
        "n_records": d.n_records,
        "variables": [
            {
                "name": vm.name, "label": vm.label, "type": vm.vtype,
                "frequency_source": getattr(vm, "frequency_source", "published"),
                "values": [
                    {"value": c, "weight": float(w)}
                    for c, w in zip(vm.categories, vm.weights)
                ],
            }
            for vm in d.variables.values()
        ],
    }


def write_run(bundle: Dict[str, Any], out_dir: Union[str, Path], fmt: str = "csv") -> Path:
    """Write cohort + coverage + conformance + fidelity + dictionary + manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    d = bundle["dictionary"]
    df = bundle["data"]
    recipe = bundle["recipe"]
    result = bundle["result"]
    nullified = list(bundle.get("nullified", []))

    cohort_path = out / (f"cohort.{ 'parquet' if fmt in ('parquet', 'pq') else 'csv'}")
    if fmt in ("parquet", "pq"):
        df.to_parquet(cohort_path, index=False)
    else:
        df.to_csv(cohort_path, index=False)

    # Nullified columns are all-blank by design: report them as such, and leave them out
    # of the conformance/fidelity comparison (blank is not an out-of-vocabulary value).
    coverage = coverage_report(d)
    coverage.loc[coverage["variable"].isin(nullified), "frequency_source"] = "nullified"
    coverage.to_csv(out / "coverage.csv", index=False)
    d_scored = DataDictionary(
        name=d.name, source=d.source, version=d.version, n_records=d.n_records,
        variables={k: v for k, v in d.variables.items() if k not in nullified}, notes=d.notes,
    )
    conformance_report(d_scored, df).to_csv(out / "conformance.csv", index=False)
    fidelity = marginal_fidelity(d_scored, df)
    fidelity.to_csv(out / "fidelity.csv", index=False)
    (out / "dictionary.json").write_text(json.dumps(_dictionary_to_json(d), indent=2, default=str))

    from . import __version__  # lazy to avoid an import cycle at package init

    cov_counts = coverage["frequency_source"].value_counts().to_dict()
    config = bundle["config"]
    manifest = {
        "tool": "synthpediatric",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": _platform.python_version(),
        "recipe": recipe,
        "config": config,
        "config_sha256": bundle["config_sha256"],
        "recipe_sha256": bundle["config_sha256"],  # kept for older readers; same value
        "profile": bundle["profile"],
        "strict": bundle["strict"],
        "rules": bundle["rules"],
        "no_frequency": bundle["no_frequency"],
        "missingness": config["missingness"],
        "oversampling": bundle["oversampling"],
        "validate": config.get("validate"),
        "input_files": bundle["input_files"],
        "warnings": bundle["warnings"],
        "n_records": int(len(df)),
        "seed": config["seed"],
        "repairs": result.repairs,
        "overall_tv_distance": overall_score(fidelity),
        "coverage": {str(k): int(v) for k, v in cov_counts.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return out
