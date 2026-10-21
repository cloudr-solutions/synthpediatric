"""Demo: interactive Kaplan-Meier rendered to a self-contained HTML (Plotly).

Same synthetic cohort + survival toolkit as demo_survival.py, but instead of a static
PNG it writes an interactive HTML you can open in a browser:

  * hover any curve for survival probability + number-at-risk at that month,
  * click legend entries to show/hide ICCC groups,
  * box/lasso zoom and pan.

The file is self-contained (Plotly JS embedded) - no server, no internet needed.
This is the "interactive HTML renderer" tier of the result-presentation layer:
the engine computes disclosure-safe result tables; the renderer just visualizes them.

Survival times are illustrative (see demo_survival.py header). Requires: pip install plotly.

Usage:
    python examples/demo_survival_interactive.py --metadata nccr_instances.ttl -n 20000
"""

from __future__ import annotations

import argparse

from synthpediatric import generate, kaplan_meier_by_group, sample_survival, write_survival_html
from synthpediatric.constraints import RuleSet
from synthpediatric.nccr_rdf import NCCR_INSTANCES_URL, build_dictionary, load_graph

# Illustrative 5-year overall survival by ICCC major group (demonstration only).
# At the Jamboree this spec is supplied by the Input team from SEER*Stat survival stats.
ICCC_5YR = {
    "I": 0.88, "II": 0.90, "III": 0.75, "IV": 0.80, "V": 0.97, "VI": 0.90,
    "VII": 0.70, "VIII": 0.70, "IX": 0.72, "X": 0.92, "XI": 0.93, "XII": 0.75,
}
DEFAULT_5YR = 0.80
HORIZON = 120.0


def survival_specs(iccc_values) -> dict:
    """Map each present icccMajor label to a 5-year-survival spec via its ICCC prefix."""
    specs = {}
    for label in set(map(str, iccc_values)):
        prefix = label.split(".", 1)[0].strip()
        specs[label] = ICCC_5YR.get(prefix, DEFAULT_5YR)
    return specs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metadata", default=NCCR_INSTANCES_URL)
    ap.add_argument("-n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="out/km_interactive.html")
    args = ap.parse_args()

    d = build_dictionary(load_graph([args.metadata]), "CTC")
    rules = RuleSet.from_json("examples/ctc_consistency_rules.json")
    cohort = generate(d, n=args.n, rng=args.seed, ruleset=rules).data

    iccc = cohort["icccMajor"].to_numpy()
    cohort["months"], cohort["event"] = sample_survival(
        iccc, survival_specs(iccc), rng=args.seed, horizon_months=HORIZON
    )

    curves = kaplan_meier_by_group(cohort, "months", "event", "icccMajor")
    write_survival_html(
        curves,
        args.out,
        title=f"Kaplan-Meier by ICCC group (synthetic CTC cohort, n={len(cohort):,})",
        horizon=HORIZON,
    )
    print(f"Wrote interactive KM -> {args.out}")
    print("Open in a browser: hover for survival + at-risk, click legend to toggle, drag to zoom.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
