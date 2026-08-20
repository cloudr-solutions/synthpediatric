"""End-to-end demo: synthetic NCCR CTC cohort from published metadata.

Tells the whole story in one run, suitable for a live walkthrough:

  1. Load the real published NCCR metadata (RDF/Turtle).
  2. Generate a synthetic registry cohort from the real published frequencies.
  3. Show the incoherence that pure marginal sampling produces.
  4. Apply clinical consistency rules and show the same checks, now fixed.
  5. Report marginal fidelity and the privacy posture.
  6. Export the cohort.

Usage:
    python examples/demo_ctc.py                      # fetch published metadata
    python examples/demo_ctc.py --metadata nccr_instances.ttl -n 20000
"""

from __future__ import annotations

import argparse
from pathlib import Path

from synthpediatric import generate, marginal_fidelity, overall_score
from synthpediatric.constraints import RuleSet
from synthpediatric.evaluate import PROVENANCE_STATEMENT
from synthpediatric.nccr_rdf import NCCR_INSTANCES_URL, build_dictionary, load_graph

RULES_FILE = Path(__file__).with_name("ctc_consistency_rules.json")

# Checks that make the before/after obvious.
GLEASON = "gleasonScoreClinicalRecode"
RETINO_YOUNG = {"00 years", "01-04 years", "05-09 years"}


def _rule(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def coherence_checks(df) -> None:
    females = df[df["sex"] == "Female"]
    bad_gleason = (females[GLEASON] != "Not applicable").sum()
    retino = df[df["icccMajor"] == "V. Retinoblastoma"]
    old_retino = (~retino["ageRecode19Groups"].isin(RETINO_YOUNG)).sum()
    print(f"  females assigned a prostate Gleason score : {bad_gleason:,} / {len(females):,}")
    print(f"  retinoblastoma cases aged >= 10 years      : {old_retino:,} / {len(retino):,}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--metadata",
        default=NCCR_INSTANCES_URL,
        help="NCCR instances .ttl (local path or URL); default fetches the published file",
    )
    ap.add_argument("-n", type=int, default=20000, help="number of synthetic records")
    ap.add_argument("--seed", type=int, default=7, help="random seed")
    ap.add_argument("--out", default="out/ctc_demo.parquet", help="output .csv/.parquet")
    args = ap.parse_args()

    _rule("1. Load real published NCCR metadata")
    print(f"  source: {args.metadata}")
    graph = load_graph([args.metadata])
    d = build_dictionary(graph, "CTC")
    print(f"  {d.name}")
    print(f"  published records: {d.n_records:,}")
    print(f"  variables with published marginals: {len(d.variables)}")

    _rule(f"2. Generate {args.n:,} synthetic records (marginals only, no rules)")
    raw = generate(d, n=args.n, rng=args.seed)
    print(f"  generated {len(raw.data):,} records x {raw.data.shape[1]} variables")

    _rule("3. Coherence BEFORE rules (independent marginal sampling)")
    coherence_checks(raw.data)
    print("\n  -> marginals are individually faithful but records are incoherent:")
    print("     prostate markers have counts only for prostate cases, so sampling")
    print("     independently assigns a Gleason score to everyone.")

    _rule("4. Apply clinical consistency rules")
    rules = RuleSet.from_json(RULES_FILE)
    fixed = generate(d, n=args.n, rng=args.seed, ruleset=rules)
    print(f"  rules applied: {len(rules.constraints)}   records repaired: {fixed.total_repairs:,}")
    print("\n  Coherence AFTER rules:")
    coherence_checks(fixed.data)

    _rule("5. Marginal fidelity (synthetic vs. published) + privacy")
    report = marginal_fidelity(d, fixed.data)
    print(f"  mean total-variation distance across variables: {overall_score(report):.4f}")
    print("  (site-gated variables like Gleason intentionally diverge from their")
    print("   prostate-only published marginal - that is the rules working.)")
    print(f"\n  {PROVENANCE_STATEMENT}")

    _rule("6. Export")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == ".csv":
        fixed.data.to_csv(out, index=False)
    else:
        fixed.data.to_parquet(out, index=False)
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
