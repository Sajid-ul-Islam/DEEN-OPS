import streamlit as st

from src.components.ui.metric_card import (
    MetricCard,
    render_metric_cards,
)


def render_premium_header(
    title: str, subtitle: str, icon: str = "🚀", active_badge: bool = True
):
    """
    Renders a unified glassmorphism gradient header banner across the DEEN-OPS app.
    """
    badge_html = ""
    if active_badge:
        badge_html = """<div style="text-align: right;">
<div style="display: inline-block; background: rgba(16, 185, 129, 0.1); color: #10b981; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.875rem; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.2);">
● ACTIVE
</div>
</div>"""

    html = f"""<div style="background: linear-gradient(135deg, #1f2937, #111827); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid #374151; margin-bottom: 1.5rem; display: flex; align-items: center; justify-content: space-between;">
<div>
<h1 style="margin: 0; padding: 0; font-size: 1.8rem; color: #f9fafb; font-weight: 700; display: flex; align-items: center; gap: 0.5rem;">
<span style="font-size: 2.2rem;">{icon}</span> {title}
</h1>
<p style="margin: 0.25rem 0 0 0; color: #9ca3af; font-size: 1rem;">{subtitle}</p>
</div>
{badge_html}
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def generate_metric_card(label: str, value: str, icon: str = "") -> str:
    """
    Generates a single premium metric card HTML block.

    Deprecated: prefer ``MetricCard(label, value, icon).to_html()`` or
    ``render_metric_cards([...])`` from ``src.components.ui.metric_card``.
    This wrapper exists so existing call sites continue to work during the
    migration; it deliberately does NOT uppercase the label (the old behaviour
    was an accident of the legacy template, not an intentional contract).
    """
    return MetricCard(label, value, icon).to_html()


def render_metric_grid(metrics: list):
    """
    Renders a grid of metric cards.

    Accepted input (for the migration window):
    * a list of ``MetricCard`` instances, or
    * a list of dicts ``{"label": ..., "value": ..., "icon": ...}``.

    Once all call sites have migrated, this can be replaced with a direct call
    to ``render_metric_cards``.
    """
    if not metrics:
        return

    cards: list[MetricCard] = []
    for m in metrics:
        if isinstance(m, MetricCard):
            cards.append(m)
        else:
            cards.append(
                MetricCard(
                    str(m.get("label", "")),
                    str(m.get("value", "")),
                    str(m.get("icon", "")),
                )
            )

    render_metric_cards(cards)
