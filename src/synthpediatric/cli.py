"""Command line interface: sources / profile / generate / run / evaluate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from . import __version__
from .constraints import RuleSet
from .dictionary import DataDictionary
from .evaluate import PROVENANCE_STATEMENT, fidelity_summary, marginal_fidelity
from .generate import generate

_REMOTE_KEYWORDS = ("remote", "nccr")


def _is_rdf_spec(spec: str) -> bool:
    return spec.lower() in _REMOTE_KEYWORDS or spec.lower().endswith(".ttl")


def _parse_var_modes(items: Optional[List[str]]) -> dict:
    """``--var-value-mode NAME=label|code`` (repeatable) -> {NAME: mode}."""
    out = {}
    for item in items or []:
        name, sep, mode = item.partition("=")
        if not sep or not name or mode not in ("label", "code"):
            raise SystemExit(f"--var-value-mode: expected NAME=label or NAME=code, got '{item}'")
        out[name] = mode
    return out


def _load_with_policy(args: argparse.Namespace) -> Tuple[DataDictionary, Optional[dict]]:
    """Load a dictionary and the effective source policy (None unless NCCR RDF metadata).

    - ``foo.json``            -> JSON marginals dictionary
    - ``nccr_instances.ttl``  -> local NCCR RDF metadata (requires --source)
    - ``remote`` / ``nccr``   -> published NCCR RDF metadata (requires --source)

    A value set on the command line (--value-mode, --var-value-mode, --no-frequency) beats
    the built-in source policy, as an explicit config value does.
    """
    spec = args.dictionary
    if not _is_rdf_spec(spec):
        return DataDictionary.load(spec), None

    source = getattr(args, "source", None)
    if not source:
        raise SystemExit(
            "--source is required when loading NCCR RDF metadata (e.g. --source CTC). "
            "Run 'synthpediatric sources <ttl|remote>' to list available datasources."
        )
    from .config import ConfigError
    from .recipe import _load_dictionary as load_rdf

    value_mode = getattr(args, "value_mode", None)
    no_frequency = getattr(args, "no_frequency", None)
    cfg = {
        "metadata": spec, "source": source, "value_mode": value_mode or "label",
        "no_frequency": no_frequency or "uniform",
        "value_modes": _parse_var_modes(getattr(args, "var_value_mode", None)),
        "explicit": [
            k for k, v in (("value_mode", value_mode), ("no_frequency", no_frequency)) if v
        ],
    }
    try:
        d = load_rdf(cfg)
        return d, d.source_policy
    except ConfigError as exc:
        raise SystemExit(f"config error: {exc}")


def _load_dictionary(args: argparse.Namespace) -> DataDictionary:
    return _load_with_policy(args)[0]


def _table_tag(source: Optional[str]) -> str:
    from .source_policy import TABLE_LABEL

    return f"[{TABLE_LABEL}: {source}]" if source else f"[{TABLE_LABEL}]"


def _print_labels(report: dict, policy: Optional[dict]) -> None:
    """Say what the table is (unlinked, single source) and what was dropped or invented."""
    from .conformance import report_lines
    from .source_policy import LINKAGE_STATEMENT

    print(LINKAGE_STATEMENT)
    for line in report_lines(report):
        print(line)
    if policy:
        parts = []
        nf = policy["no_frequency"]
        if nf["supplied_by"] != "default":
            parts.append(f"no_frequency={nf['value']} ({nf['supplied_by']})")
        for var, e in policy["value_modes"].items():
            parts.append(f"{var}={e['value']} ({e['supplied_by']})")
        if policy["survival"]["value"] == "refuse":
            parts.append(f"survival=refuse ({policy['survival']['supplied_by']})")
        if parts:
            print(f"Source policy [{policy['source']}]: " + "; ".join(parts))


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
    from .conformance import generation_report
    from .recipe import _without

    loaded, policy = _load_with_policy(args)
    mode = policy["no_frequency"]["value"] if policy else "uniform"
    report = generation_report(loaded, mode)
    invented = report["invented"]
    d = _without(loaded, invented) if mode == "suppress" and invented else loaded
    ruleset: Optional[RuleSet] = None
    if args.rules:
        ruleset = RuleSet.from_json(args.rules)
        from .rules import repair_target_errors

        for i, constraint in enumerate(ruleset.constraints):
            for message in repair_target_errors(
                constraint, d.variables, f"{args.rules}[{i}]", args.rules
            ):
                raise SystemExit(f"config error: {message}")
    result = generate(d, n=args.n, rng=args.seed, ruleset=ruleset)
    if mode == "nullify":  # sampled first, blanked at the end, as in `run`
        for name in invented:
            result.data[name] = None
        d = _without(d, invented)  # blank columns are not scored
    out = Path(args.out)
    _write_frame(result.data, out)

    tag = _table_tag(loaded.source_id)
    print(f"Generated {len(result.data):,} synthetic records -> {out}  {tag}")
    _print_labels(report, policy)
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
    try:
        path = write_run(
            bundle, out_dir, fmt=fmt, archive=args.archive,
            archive_name=args.archive_name, keep_csv=True if args.keep_csv else None,
        )
    except ConfigError as exc:
        raise SystemExit(f"config error: {exc}")

    df = bundle["data"]
    result = bundle["result"]
    print(f"Recipe: {config.get('name', '(unnamed)')}")
    print(f"Profile: {bundle['profile']}")
    for entry in bundle["rules"]:
        print(f"  {entry['order']:>3} {entry['name']:<12} {entry['status']:<9} {entry['reason']}")
    for msg in bundle["warnings"]:
        print(f"warning: {msg}")
    print(f"Generated {len(df):,} records -> {path}/  {_table_tag(bundle.get('source'))}")
    _print_labels(bundle["report"], bundle.get("source_policy"))
    if result.total_repairs:
        print(f"Consistency repairs: {result.total_repairs:,}")
    print("Wrote: cohort, coverage.csv, conformance.csv, fidelity.csv,")
    print("       dictionary.json, manifest.json")
    if bundle.get("validation"):
        print("       validation_report.json, validation_summary.txt "
              f"({len(bundle['validation']['skipped'])} requested metric(s) skipped)")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from .conformance import generation_report
    from .recipe import _without

    d, policy = _load_with_policy(args)
    invented = generation_report(d)["invented"]
    if policy and policy["no_frequency"]["value"] in ("nullify", "suppress") and invented:
        d = _without(d, invented)  # blank or removed columns are not scored
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
    summary = fidelity_summary(report)
    published = summary["overall_tv_distance_published"]
    shown = f"{published:>13.4f}" if published is not None else f"{'n/a':>13}"
    print(f"{'OVERALL (published)':<24} {'':>8} {shown}")
    if summary["invented_columns"]:
        print(
            f"{summary['invented_columns']} invented (uniform fallback) columns are listed "
            "above but not in the overall score; mean over all columns incl. invented: "
            f"{summary['overall_tv_distance_all_columns']:.4f}"
        )
    print(f"\n{PROVENANCE_STATEMENT}")


def cmd_validate(args: argparse.Namespace) -> int:
    from .validate import run_cli

    return run_cli(args)


def cmd_measure(args: argparse.Namespace) -> int:
    from .measure import run_cli

    return run_cli(args)


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
            default=None,
            help="use human-readable value labels (default) or raw code notations",
        )
        p.add_argument(
            "--var-value-mode",
            action="append",
            metavar="NAME=MODE",
            help="value mode for one variable (label or code); repeatable; beats the "
            "source policy and --value-mode",
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
    p_gen.add_argument(
        "--no-frequency", choices=("uniform", "nullify", "suppress"), default=None,
        help="columns with no published counts: fill uniformly, leave blank, or remove "
        "(default: the source policy, else uniform)",
    )
    p_gen.set_defaults(func=cmd_generate)

    p_run = sub.add_parser("run", help="run a generation config (YAML or JSON; reproducible)")
    p_run.add_argument("recipe", help="path to a config .yaml/.yml or .json file")
    p_run.add_argument("--out-dir", default=None, help="output dir (default: outputs.dir)")
    p_run.add_argument(
        "--archive", choices=("none", "zip"), default=None,
        help="zip the data CSV (only the CSV, reports stay beside it; default: outputs.archive)",
    )
    p_run.add_argument("--archive-name", default=None, help="base name of the zip and its CSV")
    p_run.add_argument(
        "--keep-csv", action="store_true", help="with --archive zip, also keep the bare CSV",
    )
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

    p_val = sub.add_parser(
        "validate", help="compare synthetic cohort(s) with a real cohort (discriminator AUC etc.)"
    )
    p_val.add_argument("real", help="real cohort .csv/.parquet")
    p_val.add_argument(
        "synthetic", nargs="+", help="synthetic cohort file(s); several files = replicates"
    )
    p_val.add_argument(
        "--dictionary", help="optional context: dictionary JSON, generation config, .ttl or remote"
    )
    p_val.add_argument("--label", required=True, help="run label for the history, e.g. v0")
    p_val.add_argument("--out-dir", required=True, help="directory for the report files")
    p_val.add_argument("--history", help="history CSV (default: <out-dir>/history.csv)")
    p_val.add_argument("--seed", type=int, default=0, help="seed for the discriminator")
    p_val.add_argument("--min-count", type=int, default=16, help="suppress counts below this")
    p_val.add_argument("--folds", type=int, default=5, help="discriminator CV folds")
    p_val.add_argument("--metrics", help="comma-separated metric names (default: all)")
    p_val.add_argument("--exclude", help="comma-separated columns to leave out (e.g. IDs)")
    p_val.add_argument(
        "--privacy", help="comma-separated privacy metrics, or 'all' (default: none)"
    )
    p_val.add_argument("--holdout", help="real records not used to build the synthetic data")
    p_val.add_argument("--sensitive", help="comma-separated sensitive fields (attribute inference)")
    p_val.add_argument("--max-records", type=int, default=2000, help="privacy sampling cap")
    _add_rdf_opts(p_val)
    p_val.set_defaults(func=cmd_validate)

    p_meas = sub.add_parser(
        "measure",
        help="run in CGC on real data: export disclosure-controlled aggregates for the generator",
    )
    p_meas.add_argument("config", help="measure config (.yaml/.yml or .json)")
    p_meas.add_argument("--out-dir", default=None, help="output directory (default: outputs.dir)")
    p_meas.add_argument(
        "--overwrite", action="store_true", help="replace the results of an earlier measure run"
    )
    p_meas.set_defaults(func=cmd_measure)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
