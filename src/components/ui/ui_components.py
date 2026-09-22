import streamlit as st


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
    Expects to be wrapped in a <div class="metric-container">.

    Emitted as a single line with no leading indentation: st.markdown parses
    CommonMark, and any HTML line indented 4+ spaces becomes an indented code
    block, which would render the raw HTML as literal text instead of cards.
    """
    return (
        f'<div class="metric-card"><div>'
        f'<div class="metric-label">{label.upper()}</div>'
        f'<div class="metric-value">{value}</div>'
        f'</div><div class="metric-icon">{icon}</div></div>'
    )


def render_metric_grid(metrics: list):
    """
    Renders a grid of metric cards.
    `metrics` should be a list of dicts: [{"label": "Orders", "value": "150", "icon": "📦"}, ...]
    """
    html = '<div class="metric-container">'
    for m in metrics:
        html += generate_metric_card(
            m.get("label", ""), str(m.get("value", "")), m.get("icon", "")
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
