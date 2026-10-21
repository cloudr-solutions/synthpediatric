"""Config-driven generation runs — one recipe chains the whole pipeline.

A recipe (a JSON/dict) specifies: the metadata source, optional marginal overrides,
an optional cohort filter, optional rare-category oversampling, consistency rules,
optional survival generation, and how many records to produce. ``run_recipe`` executes
that pipeline; ``write_run`` writes the cohort plus a coverage report, a conformance
check, a fidelity scorecard, the data dictionary, and a reproducibility manifest.

The recipe file is the reproducible artifact — rerun it next year against refreshed
metadata and you get a comparable synthetic cohort.

Recipe schema (all keys except ``source``/``metadata`` optional)::

    {
      "name": "Pediatric ALL",
      "metadata": "remote",            # "remote", a .ttl path, or a .json dictionary
      "source": "CTC",                 # required for NCCR metadata
      "n": 20000, "seed": 42,
      "value_mode": "label", "no_frequency": "uniform",
      "override_marginals": {"sex": {"Male": 560, "Female": 440}},
      "cohort": {"filters": [{"variable": "icccMajor", "op": "equals", "values": [...]}]},
      "oversample": {"variable": "icccMajor", "values": [...], "factor": 10},
      "rules": "examples/ctc_consistency_rules.json",
      "survival": {"group_col": "icccMajor", "specs": {"...": 0.9}, "horizon_months": 120}
    }
"""

from __future__ import annotations

import hashlib
import json
import platform as _platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .conformance import conformance_report, coverage_report
from .constraints import RuleSet
from .dictionary import DataDictionary
from .evaluate import marginal_fidelity, overall_score
from .generate import generate
from .inputs import apply_cohort, cohort_from_dict, override_marginals
from .resample import oversample_values
from .survival_gen import sample_survival

_REMOTE = ("remote", "nccr")


def _load_dictionary(recipe: Dict[str, Any]) -> DataDictionary:
    metadata = str(recipe.get("metadata", "remote"))
    is_rdf = metadata.lower() in _REMOTE or metadata.lower().endswith(".ttl")
    if not is_rdf:
        return DataDictionary.load(metadata)

    source = recipe.get("source")
    if not source:
        raise ValueError("recipe requires 'source' when loading NCCR RDF metadata")
    from .nccr_rdf import build_dictionary, load_graph

    sources = None if metadata.lower() in _REMOTE else [metadata]
    graph = load_graph(sources)
    return build_dictionary(
        graph, source,
        value_mode=recipe.get("value_mode", "label"),
        no_frequency=recipe.get("no_frequency", "uniform"),
    )


def run_recipe(recipe: Union[Dict[str, Any], str, Path]) -> Dict[str, Any]:
    """Execute a recipe and return a result bundle (dictionary, result, data, recipe)."""
    if isinstance(recipe, (str, Path)):
        with open(recipe, encoding="utf-8") as fh:
            recipe = json.load(fh)

    d = _load_dictionary(recipe)
    if recipe.get("override_marginals"):
        d = override_marginals(d, recipe["override_marginals"])
    if recipe.get("cohort"):
        d = apply_cohort(d, cohort_from_dict(recipe["cohort"]))
    if recipe.get("oversample"):
        ov = recipe["oversample"]
        d = oversample_values(d, ov["variable"], ov["values"], ov.get("factor", 10.0))

    ruleset: Optional[RuleSet] = (
        RuleSet.from_json(recipe["rules"]) if recipe.get("rules") else None
    )
    seed = recipe.get("seed")
    result = generate(d, n=int(recipe.get("n", 1000)), rng=seed, ruleset=ruleset)
    df = result.data

    if recipe.get("survival"):
        s = recipe["survival"]
        group_col = s["group_col"]
        months, event = sample_survival(
            df[group_col].to_numpy(), s["specs"], rng=seed,
            horizon_months=s.get("horizon_months", 120.0),
        )
        df[s.get("time_col", "months")] = months
        df[s.get("event_col", "event")] = event

    return {"dictionary": d, "result": result, "data": df, "recipe": recipe}


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

    cohort_path = out / (f"cohort.{ 'parquet' if fmt in ('parquet', 'pq') else 'csv'}")
    if fmt in ("parquet", "pq"):
        df.to_parquet(cohort_path, index=False)
    else:
        df.to_csv(cohort_path, index=False)

    coverage_report(d).to_csv(out / "coverage.csv", index=False)
    conformance_report(d, df).to_csv(out / "conformance.csv", index=False)
    fidelity = marginal_fidelity(d, df)
    fidelity.to_csv(out / "fidelity.csv", index=False)
    (out / "dictionary.json").write_text(json.dumps(_dictionary_to_json(d), indent=2, default=str))

    from . import __version__  # lazy to avoid an import cycle at package init

    cov_counts = coverage_report(d)["frequency_source"].value_counts().to_dict()
    manifest = {
        "tool": "synthpediatric",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": _platform.python_version(),
        "recipe": recipe,
        "recipe_sha256": hashlib.sha256(
            json.dumps(recipe, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "n_records": int(len(df)),
        "seed": recipe.get("seed"),
        "repairs": result.repairs,
        "overall_tv_distance": overall_score(fidelity),
        "coverage": {str(k): int(v) for k, v in cov_counts.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return out
