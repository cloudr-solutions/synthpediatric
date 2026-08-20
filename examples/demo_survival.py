"""Demo: cohort-level survival analysis on a synthetic pediatric/AYA cancer cohort.

This is the kind of analysis the NCCR Data Platform does not offer today: take a
cohort and produce Kaplan-Meier survival by disease group, median and 5-year
survival, and a log-rank test.

Pipeline: generate a synthetic CTC cohort from the real published NCCR metadata
(real ICCC / age / sex / vital-status distributions) -> run the synthpediatric
survival toolkit.

IMPORTANT — survival time is illustrative here. NCCR's *published metadata* provides
value frequencies, not individual follow-up times, so survival months cannot be drawn
from it. For this offline demo, survival times are SIMULATED from a documented
per-ICCC 5-year-survival model (values below are rough, for demonstration only). In
production the identical toolkit consumes real survival months from an approved NCCR
download or from SEER public-use data.

Usage:
    python examples/demo_survival.py --metadata nccr_instances.ttl -n 20000
"""

from __future__ import annotations

import argparse

import numpy as np

from synthpediatric import generate, kaplan_meier_by_group, logrank_test
from synthpediatric.constraints import RuleSet
from synthpediatric.nccr_rdf import NCCR_INSTANCES_URL, build_dictionary, load_graph

# Illustrative 5-year overall survival by ICCC major group (demonstration only).
ICCC_5YR = {
    "I": 0.88, "II": 0.90, "III": 0.75, "IV": 0.80, "V": 0.97, "VI": 0.90,
    "VII": 0.70, "VIII": 0.70, "IX": 0.72, "X": 0.92, "XI": 0.93, "XII": 0.75,
}
DEFAULT_5YR = 0.80
HORIZON = 120.0  # administrative follow-up cap, months


def simulate_survival(iccc: np.ndarray, rng: np.random.Generator):
    """Illustrative time-to-event with right-censoring, by ICCC 5-year survival."""
    months = np.empty(iccc.size)
    event = np.zeros(iccc.size, dtype=int)
    for i, label in enumerate(iccc):
        prefix = str(label).split(".", 1)[0].strip()
        s5 = ICCC_5YR.get(prefix, DEFAULT_5YR)
        rate = -np.log(s5) / 60.0          # exponential hazard from 5-yr survival
        t_event = rng.exponential(1.0 / rate) if rate > 0 else np.inf
        t_cens = rng.uniform(12.0, HORIZON)  # mix of dropout + administrative cutoff
        months[i] = min(t_event, t_cens)
        event[i] = int(t_event <= t_cens)
    return months, event


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metadata", default=NCCR_INSTANCES_URL)
    ap.add_argument("-n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="out/km_curves.csv")
    args = ap.parse_args()

    print("1. Generate synthetic CTC cohort from published NCCR metadata")
    d = build_dictionary(load_graph([args.metadata]), "CTC")
    rules = RuleSet.from_json("examples/ctc_consistency_rules.json")
    cohort = generate(d, n=args.n, rng=args.seed, ruleset=rules).data
    print(f"   {len(cohort):,} synthetic records")

    print("\n2. Attach illustrative survival times (see header note)")
    rng = np.random.default_rng(args.seed)
    cohort["months"], cohort["event"] = simulate_survival(
        cohort["icccMajor"].to_numpy(), rng
    )

    print("\n3. Kaplan-Meier by ICCC major group (synthpediatric.analyze)")
    curves = kaplan_meier_by_group(cohort, "months", "event", "icccMajor")
    rows = []
    for group, km in curves.items():
        rows.append((group, km.n, km.n_events, km.survival_at(60.0), km.median_survival()))
    rows.sort(key=lambda r: -r[3])

    print(f"\n   {'ICCC group':<52} {'n':>6} {'events':>7} {'5-yr S':>7} {'median(mo)':>11}")
    print("   " + "-" * 88)
    for group, n, ev, s5, med in rows:
        med_s = "not reached" if np.isnan(med) else f"{med:.0f}"
        print(f"   {str(group)[:52]:<52} {n:>6,} {ev:>7,} {s5:>7.2f} {med_s:>11}")

    print("\n4. Log-rank test across ICCC groups")
    lr = logrank_test(cohort, "months", "event", "icccMajor")
    p = "n/a (install scipy)" if lr["p_value"] is None else f"{lr['p_value']:.2e}"
    print(f"   chi2 = {lr['chi2']:.1f}   df = {lr['df']}   p = {p}")

    # Export the KM step functions so a curve can be plotted downstream.
    import csv
    from pathlib import Path

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["iccc_group", "time_months", "survival"])
        for group, km in curves.items():
            for t, s in zip(km.time, km.survival):
                w.writerow([group, f"{t:.3f}", f"{s:.6f}"])
    print(f"\n5. Wrote KM curves -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
