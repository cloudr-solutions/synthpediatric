"""Interactive result rendering (presentation layer).

Turns computed result objects (e.g. Kaplan-Meier curves from
:mod:`synthpediatric.analyze`) into self-contained interactive HTML using Plotly.

Kept deliberately separate from computation: the analysis engine produces
disclosure-safe result objects; renderers only visualize them. New templates get an
interactive renderer by adding a function here that consumes their result object.

Requires the optional ``viz`` extra: ``pip install synthpediatric[viz]``.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .analyze import KMResult


def _require_plotly():
    try:
        import plotly.graph_objects as go
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "Interactive rendering requires plotly: pip install synthpediatric[viz]"
        ) from exc
    return go


def survival_to_figure(
    curves: Mapping[object, KMResult],
    title: str = "Kaplan-Meier survival",
    horizon: Optional[float] = None,
    height: int = 620,
):
    """Build an interactive Plotly figure of Kaplan-Meier curves by group.

    Curves are drawn as proper KM step functions; hover shows survival probability
    and the number at risk; legend entries toggle groups on/off.
    """
    go = _require_plotly()
    fig = go.Figure()
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
        yaxis_range=[0, 1.02],
        hovermode="closest",
        legend_title_text="group (click to toggle)",
        template="plotly_white",
        height=height,
    )
    if horizon is not None:
        fig.update_layout(xaxis_range=[0, horizon])
    return fig


def write_survival_html(
    curves: Mapping[object, KMResult],
    path,
    title: str = "Kaplan-Meier survival",
    horizon: Optional[float] = None,
    height: int = 620,
    embed_js: bool = True,
) -> str:
    """Render KM curves to a self-contained interactive HTML file; return the path.

    ``embed_js=True`` embeds Plotly JS so the file works offline (larger); set False
    to load Plotly from a CDN (smaller file, needs internet).
    """
    fig = survival_to_figure(curves, title=title, horizon=horizon, height=height)
    fig.write_html(str(path), include_plotlyjs=bool(embed_js), full_html=True)
    return str(path)
