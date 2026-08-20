"""Demo: joint calibration (IPF) fixes marginals while preserving association.

Uses the real NCCR CTC marginals as calibration targets, and a small SELF-CONTAINED
synthetic "proxy" that stands in for individual-level data (e.g. SEER research
data). The proxy deliberately has (a) the WRONG marginals and (b) a REAL
association: retinoblastoma concentrated in early childhood.

The demo shows that after IPF:
  * each backbone variable's marginal matches the published NCCR marginal, and
  * the age-x-disease association survives (retinoblastoma stays a childhood cancer).

Usage:
    python examples/demo_calibration.py --metadata nccr_instances.ttl
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from synthpediatric.calibrate import (
    JointDistribution,
    calibrate_to_dictionary,
    targets_from_dictionary,
)
from synthpediatric.nccr_rdf import NCCR_INSTANCES_URL, build_dictionary, load_graph

BACKBONE = ["sex", "ageRecode19Groups", "icccMajor"]
YOUNG = {"00 years", "01-04 years", "05-09 years"}
RETINO = "V. Retinoblastoma"


def build_proxy(dictionary, n, seed):
    """A stand-in for individual-level data: wrong marginals, real association."""
    rng = np.random.default_rng(seed)
    sexes = dictionary.variables["sex"].categories
    ages = dictionary.variables["ageRecode19Groups"].categories
    icccs = dictionary.variables["icccMajor"].categories
    young_ages = [a for a in ages if a in YOUNG]

    # icccMajor drawn roughly uniformly (deliberately unlike the NCCR marginal).
    iccc = rng.choice(icccs, size=n)
    age = np.empty(n, dtype=object)
    for i, c in enumerate(iccc):
        if c == RETINO:
            # real association: retinoblastoma is an early-childhood cancer
            age[i] = rng.choice(young_ages)
        else:
            age[i] = rng.choice(ages)
    sex = rng.choice(sexes, size=n)
    return pd.DataFrame({"sex": sex, "ageRecode19Groups": age, "icccMajor": iccc})


def tvd(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


def retino_young_share(joint: JointDistribution) -> float:
    """P(age in early childhood | retinoblastoma) under a joint distribution."""
    df = joint.sample(200_000, rng=0)
    r = df[df["icccMajor"] == RETINO]
    if len(r) == 0:
        return float("nan")
    return (r["ageRecode19Groups"].isin(YOUNG)).mean()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metadata", default=NCCR_INSTANCES_URL)
    ap.add_argument("-n", type=int, default=60000, help="proxy size")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    print("Loading NCCR CTC marginals ...")
    d = build_dictionary(load_graph([args.metadata]), "CTC")
    targets = targets_from_dictionary(d, BACKBONE)

    proxy = build_proxy(d, args.n, args.seed)
    raw = JointDistribution.from_records(proxy, BACKBONE)

    result = calibrate_to_dictionary(proxy, BACKBONE, d)
    cal = result.joint
    print(f"IPF: converged={result.converged} in {result.iterations} iters "
          f"(max marginal dev {result.max_deviation:.2e})")
    if result.warnings:
        for w in result.warnings:
            print("  warning:", w)

    print("\nMarginal match to NCCR (total-variation distance; lower is better)")
    print(f"  {'variable':<20} {'proxy(before)':>14} {'calibrated(after)':>18}")
    for v in BACKBONE:
        before = tvd(raw.marginal(v), targets[v])
        after = tvd(cal.marginal(v), targets[v])
        print(f"  {v:<20} {before:>14.4f} {after:>18.4f}")

    print("\nAssociation preserved: P(early childhood | retinoblastoma)")
    print(f"  proxy (before calibration): {retino_young_share(raw):.3f}")
    print(f"  calibrated (after)        : {retino_young_share(cal):.3f}")
    print("  -> marginals were forced to NCCR, but retinoblastoma stayed a childhood cancer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
