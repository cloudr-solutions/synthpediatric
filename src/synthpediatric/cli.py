"""Command line interface: sources / profile / generate / run / evaluate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

from . import __version__
from .constraints import RuleSet
from .dictionary import DataDictionary
from .evaluate import PROVENANCE_STATEMENT, marginal_fidelity, overall_score
from .generate import generate

_REMOTE_KEYWORDS = ("remote", "nccr")


def _is_rdf_spec(spec: str) -> bool:
    return spec.lower() in _REMOTE_KEYWORDS or spec.lower().endswith(".ttl")


def _load_dictionary(args: argparse.Namespace) -> DataDictionary:
    """Load a dictionary from JSON, a local Turtle file, or the published NCCR metadata.

    - ``foo.json``            -> JSON marginals dictionary
    - ``nccr_instances.ttl``  -> local NCCR RDF metadata (requires --source)
    - ``remote`` / ``nccr``   -> published NCCR RDF metadata (requires --source)
    """
    spec = args.dictionary
    if not _is_rdf_spec(spec):
        return DataDictionary.load(spec)

    source = getattr(args, "source", None)
    if not source:
        raise SystemExit(
            "--source is required when loading NCCR RDF metadata (e.g. --source CTC). "
            "Run 'synthpediatric sources <ttl|remote>' to list available datasources."
        )
    from .nccr_rdf import build_dictionary, load_graph

    sources = None if spec.lower() in _REMOTE_KEYWORDS else [spec]
    graph = load_graph(sources)
    return build_dictionary(graph, source, value_mode=getattr(args, "value_mode", "label"))


def _write_frame(df: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()
    if suffix == ".csv":
        df.to_csv(out, index=False)
    elif suffix in (".parquet", ".pq"):
        df.to_parquet(out, index=False)
    else:
        raise SystemExit(f"unsupported output extension '{suffix}' (use .csv or .parquet)")


def cmd_sources(args: argparse.Namespace) -> int:
    from .nccr_rdf import list_datasources, load_graph

    spec = args.dictionary
    sources = None if spec.lower() in _REMOTE_KEYWORDS else [spec]
    graph = load_graph(sources)
    rows = list_datasources(graph)
    header = f"{'source':<8} {'records':>14}  {'label'}"
    print(header)
    print("-" * (len(header) + 20))
    for r in rows:
        total = f"{r['total_record_count']:,}" if r["total_record_count"] is not None else "-"
        print(f"{r['source_id']:<8} {total:>14}  {r['label']}")
    print("\nUse a source id with --source (e.g. --source CTC) to profile or generate.")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    d = _load_dictionary(args)
    print(f"Dictionary : {d.name}")
    print(f"Source     : {d.source}")
    print(f"Version    : {d.version}")
    print(f"Records    : {d.n_records:,}" if d.n_records else "Records    : (unspecified)")
    print(f"Variables  : {len(d.variables)}")
    print()
    header = f"{'variable':<24} {'type':<12} {'#values':>8}"
    print(header)
    print("-" * len(header))
    for name, var in d.variables.items():
        print(f"{name:<24} {var.vtype:<12} {var.n_categories:>8}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    d = _load_dictionary(args)
    ruleset: Optional[RuleSet] = None
    if args.rules:
        ruleset = RuleSet.from_json(args.rules)

    result = generate(d, n=args.n, rng=args.seed, ruleset=ruleset)
    out = Path(args.out)
    _write_frame(result.data, out)

    print(f"Generated {len(result.data):,} synthetic records -> {out}")
    if ruleset is not None:
        print(f"Consistency rules applied: {len(ruleset.constraints)}")
        if result.total_repairs:
            print(f"Records repaired ({result.total_repairs:,} total):")
            for rule_name, count in result.repairs.items():
                if count:
                    print(f"  - {rule_name}: {count:,}")
        else:
            print("Records repaired: 0")
    if args.evaluate:
        print()
        _print_fidelity(d, result.data)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .config import ConfigError
    from .recipe import run_recipe, write_run

    try:
        bundle = run_recipe(args.recipe)
    except ConfigError as exc:
        raise SystemExit(f"config error: {exc}")
    config = bundle["config"]
    outputs = config.get("outputs") or {}
    out_dir = args.out_dir or outputs.get("dir") or "out/run"
    fmt = args.format or outputs.get("format") or "csv"
    path = write_run(bundle, out_dir, fmt=fmt)

    df = bundle["data"]
    result = bundle["result"]
    print(f"Recipe: {config.get('name', '(unnamed)')}")
    print(f"Profile: {bundle['profile']}")
    for entry in bundle["rules"]:
        print(f"  {entry['order']:>3} {entry['name']:<12} {entry['status']:<9} {entry['reason']}")
    for msg in bundle["warnings"]:
        print(f"warning: {msg}")
    print(f"Generated {len(df):,} records -> {path}/")
    if result.total_repairs:
        print(f"Consistency repairs: {result.total_repairs:,}")
    print("Wrote: cohort, coverage.csv, conformance.csv, fidelity.csv,")
    print("       dictionary.json, manifest.json")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    d = _load_dictionary(args)
    path = Path(args.cohort)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_parquet(path)
    _print_fidelity(d, df)
    return 0


def _print_fidelity(d: DataDictionary, df: pd.DataFrame) -> None:
    report = marginal_fidelity(d, df)
    print("Marginal fidelity (total variation distance vs. published marginals)")
    print("lower is better; 0 = identical\n")
    header = f"{'variable':<24} {'#values':>8} {'tv_distance':>13} {'max_abs_diff':>14}"
    print(header)
    print("-" * len(header))
    for _, row in report.iterrows():
        print(
            f"{row['variable']:<24} {int(row['n_categories']):>8} "
            f"{row['tv_distance']:>13.4f} {row['max_abs_diff']:>14.4f}"
        )
    print("-" * len(header))
    print(f"{'OVERALL (mean TVD)':<24} {'':>8} {overall_score(report):>13.4f}")
    print(f"\n{PROVENANCE_STATEMENT}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthpediatric",
        description="Generate privacy-safe synthetic cancer cohorts from published NCCR metadata.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # A dictionary spec is a JSON file, a local .ttl file, or 'remote'/'nccr'.
    dict_help = (
        "dictionary source: a JSON marginals file, a local NCCR .ttl file, "
        "or 'remote' to fetch the published NCCR metadata"
    )

    def _add_rdf_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--source",
            help="NCCR datasource id when loading RDF metadata (e.g. CTC, PHARM, MCD)",
        )
        p.add_argument(
            "--value-mode",
            choices=("label", "code"),
            default="label",
            help="use human-readable value labels (default) or raw code notations",
        )

    p_sources = sub.add_parser("sources", help="list NCCR datasources in RDF metadata")
    p_sources.add_argument("dictionary", help="a local NCCR .ttl file or 'remote'")
    p_sources.set_defaults(func=cmd_sources)

    p_profile = sub.add_parser("profile", help="summarize a marginals dictionary")
    p_profile.add_argument("dictionary", help=dict_help)
    _add_rdf_opts(p_profile)
    p_profile.set_defaults(func=cmd_profile)

    p_gen = sub.add_parser("generate", help="generate a synthetic cohort")
    p_gen.add_argument("dictionary", help=dict_help)
    p_gen.add_argument("-n", type=int, default=1000, help="number of records (default: 1000)")
    p_gen.add_argument("-o", "--out", default="out/cohort.parquet", help="output .csv or .parquet")
    p_gen.add_argument("--rules", help="optional consistency-rules JSON file")
    p_gen.add_argument("--seed", type=int, default=None, help="random seed for reproducibility")
    p_gen.add_argument(
        "--evaluate", action="store_true", help="print the fidelity scorecard after generating"
    )
    _add_rdf_opts(p_gen)
    p_gen.set_defaults(func=cmd_generate)

    p_run = sub.add_parser("run", help="run a generation config (YAML or JSON; reproducible)")
    p_run.add_argument("recipe", help="path to a config .yaml/.yml or .json file")
    p_run.add_argument("--out-dir", default=None, help="output dir (default: outputs.dir)")
    p_run.add_argument(
        "--format", choices=("csv", "parquet"), default=None,
        help="cohort file format (default: outputs.format, else csv)",
    )
    p_run.set_defaults(func=cmd_run)

    p_eval = sub.add_parser("evaluate", help="score a generated cohort against the dictionary")
    p_eval.add_argument("dictionary", help=dict_help)
    p_eval.add_argument("cohort", help="path to a generated .csv or .parquet cohort")
    _add_rdf_opts(p_eval)
    p_eval.set_defaults(func=cmd_evaluate)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
