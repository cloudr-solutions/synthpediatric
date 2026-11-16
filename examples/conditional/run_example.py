"""Run one conditional-rule example config and print what the run achieved.

Usage (from the repository root, so the relative paths in the examples resolve):
    python examples/conditional/run_example.py \\
        examples/conditional/age_sex_by_iccc_placeholder.yaml \\
        --metadata nccr_instances.ttl --out out/conditional

The metadata path in the YAML is replaced by --metadata. The script times the run, writes the
output files, then prints the rule's verification summary, an independent consistency check
(it parses the labels in the output records, it does not reuse the rule's tables) and the
conformance counts. A DisclosureRefusal is printed and the script exits with code 2; nothing
is written in that case.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from synthpediatric import conditional
from synthpediatric.conditional import DisclosureRefusal, parse_band
from synthpediatric.config import load_config
from synthpediatric.conformance import conformance_report
from synthpediatric.recipe import run_recipe, write_run


def _overlaps(label: str, band) -> bool:
    got = parse_band(label)
    return got is not None and got[0] <= band[1] and band[0] <= got[1]


def inconsistent_records(df, anchor, age_variables) -> dict:
    """Records whose age variables disagree with the anchor, by variable (labels parsed here)."""
    out = {}
    for var in age_variables:
        if var == anchor:
            continue
        bad = 0
        for a, b in df[[anchor, var]].drop_duplicates().itertuples(index=False):
            band = parse_band(a)
            if band is None or parse_band(b) is None:
                continue  # 'Unknown' is never generated; nothing to compare
            if not _overlaps(b, band):
                bad += int(((df[anchor] == a) & (df[var] == b)).sum())
        out[var] = bad
    return out


def _numeral(label: str) -> str:
    return str(label).split(" ")[0].split(".")[0].rstrip("abcdefghijklmnopqrstuvwxyz0123456789")


def inconsistent_iccc(df, group_variable, variables) -> dict:
    """Records whose ICCC subgroup variable disagrees with the group (roman numeral compared)."""
    out = {}
    for var in variables:
        pairs = df[[group_variable, var]].drop_duplicates()
        bad = 0
        for g, s in pairs.itertuples(index=False):
            if str(g).startswith("Not classified") or str(s).startswith("Not classified"):
                ok = str(g).startswith("Not classified") == str(s).startswith("Not classified")
            else:
                ok = _numeral(g) == _numeral(s)
            if not ok:
                bad += int(((df[group_variable] == g) & (df[var] == s)).sum())
        out[var] = bad
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", help="path of the YAML config")
    ap.add_argument("--metadata", required=True, help="NCCR snapshot (.ttl) or dictionary JSON")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    cfg["metadata"] = args.metadata
    started = time.time()
    try:
        bundle = run_recipe(cfg)
    except DisclosureRefusal as exc:
        print("REFUSED by the minimum-cell check:")
        print(exc)
        return 2
    out = write_run(bundle, args.out)
    seconds = time.time() - started
    print(f"wrote {out}  ({len(bundle['data'])} records, {seconds:.1f} s)")

    rule = [r for r in bundle["rules"] if r["name"] == "conditional"][0]["details"]
    summary = conditional.verification_summary(bundle["extra_tables"])
    print("verification summary:")
    for key in ("cells", "max_abs_diff", "max_z", "expected_max_noise"):
        print(f"  {key}: {summary[key]:.4g}")
    for var, block in summary["per_target"].items():
        print(f"  {var}: max_abs_diff {block['max_abs_diff']:.4g}, max_z {block['max_z']:.2f}")
    if "group_mix" in summary:
        print(f"  group mix: max_abs_diff {summary['group_mix']['max_abs_diff']:.4g}, "
              f"max_z {summary['group_mix']['max_z']:.2f}")

    df = bundle["data"]
    anchor = bundle["config"]["targets"]["conditional"].get("age", {}).get("anchor")
    ages = rule.get("age_variables", [])
    bad_age = inconsistent_records(df, anchor, ages) if anchor else {}
    hierarchy = rule.get("hierarchy")
    bad_iccc = {}
    if isinstance(hierarchy, dict):
        bad_iccc = inconsistent_iccc(df, hierarchy["group_variable"], hierarchy["derived"])
    print(f"age variables checked: {ages}")
    print(f"inconsistent records (age): {bad_age}")
    print(f"inconsistent records (ICCC): {bad_iccc}")

    conf = conformance_report(bundle["dictionary"], df)
    print(f"out-of-vocabulary values: {int(conf['n_out_of_vocabulary'].sum())} "
          f"in {int((conf['n_out_of_vocabulary'] > 0).sum())} variable(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
