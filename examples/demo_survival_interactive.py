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

import numpy as np

from synthpediatric import generate, kaplan_meier_by_group
from synthpediatric.constraints import RuleSet
from synthpediatric.nccr_rdf import NCCR_INSTANCES_URL, build_dictionary, load_graph

# Illustrative 5-year overall survival by ICCC major group (demonstration only).
ICCC_5YR = {
    "I": 0.88, "II": 0.90, "III": 0.75, "IV": 0.80, "V": 0.97, "VI": 0.90,
    "VII": 0.70, "VIII": 0.70, "IX": 0.72, "X": 0.92, "XI": 0.93, "XII": 0.75,
}
DEFAULT_5YR = 0.80
HORIZON = 120.0


def simulate_survival(iccc: np.ndarray, rng: np.random.Generator):
    months = np.empty(iccc.size)
    event = np.zeros(iccc.size, dtype=int)
    for i, label in enumerate(iccc):
        s5 = ICCC_5YR.get(str(label).split(".", 1)[0].strip(), DEFAULT_5YR)
        rate = -np.log(s5) / 60.0
        t_event = rng.exponential(1.0 / rate) if rate > 0 else np.inf
        t_cens = rng.uniform(12.0, HORIZON)
        months[i] = min(t_event, t_cens)
        event[i] = int(t_event <= t_cens)
    return months, event


def write_interactive_km(curves, path: str, title: str) -> None:
    import plotly.graph_objects as go

    fig = go.Figure()
    # Order groups best -> worst 5-year survival for a tidy legend.
    for group, km in sorted(curves.items(), key=lambda kv: -kv[1].survival_at(60.0)):
        fig.add_trace(
            go.Scatter(
                x=km.time,
                y=km.survival,
                mode="lines",
                line_shape="hv",  # proper Kaplan-Meier step
                name=str(group)[:44],
                customdata=km.at_risk,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Month %{x:.0f}<br>"
                    "Survival %{y:.3f}<br>"
                    "At risk %{customdata}<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="Months since diagnosis",
        yaxis_title="Survival probability",
        xaxis_range=[0, HORIZON],
        yaxis_range=[0, 1.02],
        hovermode="closest",
        legend_title_text="ICCC group (click to toggle)",
        template="plotly_white",
        height=620,
    )
    fig.write_html(path, include_plotlyjs=True, full_html=True)


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

    rng = np.random.default_rng(args.seed)
    cohort["months"], cohort["event"] = simulate_survival(cohort["icccMajor"].to_numpy(), rng)

    curves = kaplan_meier_by_group(cohort, "months", "event", "icccMajor")
    write_interactive_km(
        curves,
        args.out,
        title=f"Kaplan-Meier by ICCC group (synthetic CTC cohort, n={len(cohort):,})",
    )
    print(f"Wrote interactive KM -> {args.out}")
    print("Open in a browser: hover for survival + at-risk, click legend to toggle, drag to zoom.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
