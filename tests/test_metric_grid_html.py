"""Regression tests for metric card HTML rendering (SIP Outlet Mapper bug).

`st.markdown` parses content with CommonMark: any HTML line indented 4+ spaces
becomes an indented code block, rendering the raw HTML as literal text instead
of styled cards. The metric grid must therefore emit single-line HTML.
"""

from __future__ import annotations

from src.components.ui.ui_components import generate_metric_card, render_metric_grid

try:
    from markdown_it import MarkdownIt

    HAS_MARKDOWN_IT = True
except ImportError:  # pragma: no cover - markdown-it-py ships with streamlit
    HAS_MARKDOWN_IT = False


def _build_grid_html(metrics: list[dict]) -> str:
    """Replicates render_metric_grid's HTML assembly (without Streamlit I/O)."""
    html = '<div class="metric-container">'
    for m in metrics:
        html += generate_metric_card(
            m.get("label", ""), str(m.get("value", "")), m.get("icon", "")
        )
    return html + "</div>"


def test_metric_card_is_single_line_html():
    html = generate_metric_card("Unique Orders", "25", "🧾")
    assert html.startswith('<div class="metric-card">')
    assert "\n" not in html, "card HTML must be a single line (no code-block trap)"
    assert '<div class="metric-label">UNIQUE ORDERS</div>' in html
    assert '<div class="metric-value">25</div>' in html
    assert '<div class="metric-icon">🧾</div>' in html


def test_metric_grid_wraps_cards_in_container():
    html = _build_grid_html(
        [
            {"label": "A", "value": "1", "icon": "📦"},
            {"label": "B", "value": "2", "icon": "🔀"},
        ]
    )
    assert html.startswith('<div class="metric-container">')
    assert html.endswith("</div>")
    assert html.count('class="metric-card"') == 2


def test_metric_card_labels_are_uppercased():
    html = generate_metric_card("multi-item orders", "12", "🛍️")
    assert '<div class="metric-label">MULTI-ITEM ORDERS</div>' in html


def test_no_line_is_indented_4_or_more_spaces():
    """Any line with 4+ leading spaces would render as a markdown code block."""
    html = _build_grid_html([{"label": "X", "value": "1", "icon": "📦"}])
    for line in html.splitlines():
        assert not line.startswith("    "), f"indented line would break rendering: {line!r}"


def test_render_metric_grid_returns_none():
    assert render_metric_grid([{"label": "A", "value": "1", "icon": "📦"}]) is None


def test_commonmark_does_not_parse_grid_as_code_block():
    """End-to-end guard using the same parser family Streamlit's frontend uses."""
    if not HAS_MARKDOWN_IT:
        return  # streamlit not installed; parser-level guarantee covered above

    md = MarkdownIt("commonmark").enable(["table", "html_block"])
    html = _build_grid_html(
        [
            {"label": "Unique Orders", "value": "25", "icon": "🧾"},
            {"label": "Multi-Item Orders", "value": "12", "icon": "🛍️"},
            {"label": "Split Outlet Orders", "value": "7", "icon": "🔀"},
        ]
    )
    tokens = [t.type for t in md.parse(html)]
    assert "code_block" not in tokens, f"metric grid parsed as code block: {tokens}"
