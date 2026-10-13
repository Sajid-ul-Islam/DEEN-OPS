"""Regression tests for metric card HTML rendering (SIP Outlet Mapper bug).

`st.markdown` parses content with CommonMark: any HTML line indented 4+ spaces
becomes an indented code block, rendering the raw HTML as literal text instead
of styled cards. The metric grid must therefore emit single-line HTML.
"""

from __future__ import annotations

from src.components.ui.metric_card import MetricCard, render_metric_cards
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


def _build_metric_card_grid_html(cards: list[MetricCard]) -> str:
    """Replicates render_metric_cards' HTML assembly (without Streamlit I/O)."""
    html = '<div class="metric-container">'
    for card in cards:
        html += card.to_html()
    return html + "</div>"


def test_metric_card_is_single_line_html():
    html = generate_metric_card("Unique Orders", "25", "🧾")
    assert html.startswith('<div class="metric-card">')
    assert "\n" not in html, "card HTML must be a single line (no code-block trap)"
    assert '<div class="metric-label">Unique Orders</div>' in html
    assert '<div class="metric-value">25</div>' in html
    assert '<div class="metric-icon">🧾</div>' in html


def test_metric_card_pipes_prefix_into_value():
    card = MetricCard("Revenue", "45,000", prefix="৳ ")
    html = card.to_html()
    assert '<div class="metric-value">৳ 45,000</div>' in html


def test_metric_card_extra_class_and_badge():
    card = MetricCard(
        "Low Stock",
        "12",
        "⚠️",
        extra_class="stock-critical",
        badge='<div class="badge">Critical</div>',
    )
    html = card.to_html()
    assert 'class="metric-card stock-critical"' in html
    assert '<div class="badge">Critical</div>' in html


def test_metric_card_delta_renders_arrow_and_pct():
    card = MetricCard(
        "Orders",
        "150",
        "📦",
        delta="+12",
        delta_pct=8.3,
        prev_label="Last Day",
        prev_value="138",
    )
    html = card.to_html()
    assert (
        '<div class="metric-delta delta-up">▲+12 (+8.3%)</div> <span class="delta-prev">(Last Day: 138)</span>'
        in html
    )


def test_metric_card_down_delta_uses_down_class():
    card = MetricCard(
        "Revenue",
        "TK 4,500",
        "৳",
        delta="-TK 300",
        delta_pct=-6.2,
        prev_label="Today",
        prev_value="TK 4,800",
    )
    html = card.to_html()
    assert 'class="metric-delta delta-down"' in html
    assert "▼-TK 300 (-6.2%)" in html
    assert '<span class="delta-prev">(Today: TK 4,800)</span>' in html


def test_metric_card_no_delta_when_all_none():
    card = MetricCard("Orders", "50", "📦")
    html = card.to_html()
    assert "metric-delta" not in html


def test_metric_card_sparkline_renders():
    card = MetricCard(
        "Units",
        "120",
        "📦",
        sparkline_svg="<svg>...</svg>",
    )
    html = card.to_html()
    assert '<div class="metric-sparkline"><svg>...</svg></div>' in html


def test_metric_card_value_style_applies():
    card = MetricCard(
        "AOV",
        "TK 4,500",
        "৳",
        value_style="font-size:1.3rem;",
    )
    html = card.to_html()
    assert '<div class="metric-value" style="font-size:1.3rem;">TK 4,500</div>' in html


def test_metric_card_no_icon_when_empty():
    card = MetricCard("Items", "500", "")
    html = card.to_html()
    assert '<div class="metric-icon">' not in html


def test_metric_grid_wraps_cards_in_container():
    html = _build_metric_card_grid_html(
        [
            MetricCard("A", "1", "📦"),
            MetricCard("B", "2", "🔀"),
        ]
    )
    assert html.startswith('<div class="metric-container">')
    assert html.endswith("</div>")
    assert html.count('class="metric-card"') == 2


def test_metric_card_labels_are_not_uppercased_by_default():
    html = generate_metric_card("multi-item orders", "12", "🛍️")
    assert '<div class="metric-label">multi-item orders</div>' in html


def test_no_line_is_indented_4_or_more_spaces():
    """Any line with 4+ leading spaces would render as a markdown code block."""
    html = _build_metric_card_grid_html([MetricCard("X", "1", "📦")])
    for line in html.splitlines():
        assert not line.startswith("    "), (
            f"indented line would break rendering: {line!r}"
        )


def test_render_metric_grid_returns_none():
    assert render_metric_grid([{"label": "A", "value": "1", "icon": "📦"}]) is None


def test_render_metric_cards_returns_none():
    assert render_metric_cards([MetricCard("A", "1", "📦")]) is None


def test_commonmark_does_not_parse_grid_as_code_block():
    """End-to-end guard using the same parser family Streamlit's frontend uses."""
    if not HAS_MARKDOWN_IT:
        return  # streamlit not installed; parser-level guarantee covered above

    md = MarkdownIt("commonmark").enable(["table", "html_block"])
    html = _build_metric_card_grid_html(
        [
            MetricCard("Unique Orders", "25", "🧾"),
            MetricCard("Multi-Item Orders", "12", "🛍️"),
            MetricCard("Split Outlet Orders", "7", "🔀"),
        ]
    )
    tokens = [t.type for t in md.parse(html)]
    assert "code_block" not in tokens, f"metric grid parsed as code block: {tokens}"
