import streamlit as st


class MetricCard:
    """Canonical KPI card model for DEEN-OPS.

    Every KPI card in the app — from the live dashboard's 5-card grid to the
    stock, return, and order-tracking cards — should be built as a MetricCard
    and rendered through ``render_metric_cards``. This replaces the three tiers
    of card HTML that previously lived in ``ui_components.py``,
    ``dashboard_metrics.py``, and a dozen hand-rolled f-strings across pages.

    The HTML shape is deliberately stable: a single ``<div class="metric-card">``
    containing ``.metric-content`` + ``.metric-icon``, so every card in the app
    shares one CSS surface (``assets/styles.css`` ``.metric-card`` rules) and one
    renderer. New visual variants (e.g. ``stock-critical``) are expressed through
    the ``extra_class`` field, not by inventing a new HTML structure.
    """

    def __init__(
        self,
        label: str,
        value: str,
        icon: str = "",
        *,
        prefix: str = "",
        delta: str | None = None,
        delta_pct: float | None = None,
        delta_kind: str = "none",
        prev_label: str | None = None,
        prev_value: str | None = None,
        sparkline_svg: str = "",
        sparkline_delta_svg: str = "",
        badge: str = "",
        extra_class: str = "",
        value_style: str = "",
        content_extra_classes: str = "",
    ):
        self.label = label
        self.value = value
        self.icon = icon
        self.prefix = prefix
        self.delta = delta
        self.delta_pct = delta_pct
        self.delta_kind = delta_kind
        self.prev_label = prev_label
        self.prev_value = prev_value
        self.sparkline_svg = sparkline_svg
        self.sparkline_delta_svg = sparkline_delta_svg
        self.badge = badge
        self.extra_class = extra_class
        self.value_style = value_style
        self.content_extra_classes = content_extra_classes

    def to_html(self) -> str:
        """Render the card as a single ``<div class="metric-card">`` block.

        The output is intentionally a single line (no leading indentation) so
        that Streamlit's markdown parser does not turn it into a code block.
        """
        card_class = "metric-card"
        if self.extra_class:
            card_class += f" {self.extra_class}"

        prefix = self.prefix
        if prefix and not self.value.startswith(prefix):
            display_value = f"{prefix}{self.value}"
        else:
            display_value = self.value

        value_style_attr = ""
        if self.value_style:
            value_style_attr = f' style="{self.value_style}"'

        content_class = "metric-content"
        if self.content_extra_classes:
            content_class += f" {self.content_extra_classes}"

        html = f'<div class="{card_class}"><div class="{content_class}">'
        html += f'<div class="metric-label">{self.label}</div>'
        html += f'<div class="metric-value"{value_style_attr}>{display_value}</div>'

        if self.badge:
            html += self.badge

        if self.delta or self.delta_pct is not None:
            html += _render_delta(
                self.delta,
                self.delta_pct,
                self.delta_kind,
                self.prev_label,
                self.prev_value,
            )

        if self.sparkline_svg:
            html += f'<div class="metric-sparkline">{self.sparkline_svg}</div>'

        if self.sparkline_delta_svg:
            html += f'<div class="metric-sparkline">{self.sparkline_delta_svg}</div>'

        html += "</div>"

        if self.icon:
            html += f'<div class="metric-icon">{self.icon}</div>'

        html += "</div>"
        return html


def _render_delta(
    delta: str | None,
    delta_pct: float | None,
    delta_kind: str,
    prev_label: str | None,
    prev_value: str | None,
) -> str:
    """Render the delta / comparison snippet below a card's value.

    Parameters
    ----------
    delta : str | None
        The delta string, e.g. ``'+12'`` or ``'-TK 500'``. When present this
        drives the arrow direction and CSS class; otherwise ``delta_kind`` is
        used.
    delta_pct : float | None
        Optional percentage change to append, e.g. ``12.3`` renders as
        ``( +12.3% )``.
    delta_kind : str
        One of ``'up'``, ``'down'``, ``'neutral'``, ``'none'``. Used when
        ``delta`` is empty but a directional cue is still wanted.
    prev_label : str | None
        Label for the comparison period shown in the ``(Label: value)`` suffix,
        e.g. ``'Today'`` or ``'Last Day'``.
    prev_value : str | None
        The previous period's absolute value shown in that suffix.
    """
    if not delta and delta_kind == "none":
        return ""

    if delta:
        is_up = not str(delta).startswith("-")
    elif delta_kind == "up":
        is_up = True
    elif delta_kind == "down":
        is_up = False
    else:
        is_up = False

    cls = "delta-up" if is_up else "delta-down"
    arrow = "\u25b2" if is_up else "\u25bc"

    parts = [f'<div class="metric-delta {cls}">{arrow}']

    if delta:
        parts.append(delta)

    if delta_pct is not None and not _is_nan(delta_pct):
        parts.append(f" ({delta_pct:+.1f}%)")

    parts.append("</div>")

    if prev_label and prev_value:
        parts.append(f' <span class="delta-prev">({prev_label}: {prev_value})</span>')

    return "".join(parts)


def _is_nan(val: float) -> bool:
    """Return True when *val* is a NaN float."""
    try:
        return float(val) != float(val)
    except (TypeError, ValueError):
        return False


def render_metric_cards(
    cards: list[MetricCard], container_class: str = "metric-container"
) -> None:
    """Render a list of ``MetricCard`` instances through Streamlit markdown.

    Parameters
    ----------
    cards : list[MetricCard]
        The cards to render.
    container_class : str
        CSS class for the wrapping ``<div>``. Defaults to ``'metric-container'``;
        pass ``'metric-container-5'`` for the live dashboard's 5-card grid, or
        ``'metric-container-4'`` for a 4-card strip.
    """
    if not cards:
        return
    html = f'<div class="{container_class}">'
    for card in cards:
        html += card.to_html()
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
