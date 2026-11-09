"""Unit tests for 7-day average KPI delta comparison."""

import pandas as pd
import streamlit as st
from unittest.mock import patch

from src.components.dashboard.dashboard_metrics import (
    _format_delta_html,
    _resolve_cmp_label,
    render_operational_metrics,
)


def test_format_delta_html_7d_avg():
    # Test positive delta
    html_up = _format_delta_html(
        "+5", prev_val_str="21.3", pct_val=23.5, cmp_label="7D Avg"
    )
    assert "delta-up" in html_up
    assert "▲ +5 (+23.5%)" in html_up
    assert "vs 7D Avg (21.3)" in html_up

    # Test negative delta
    html_down = _format_delta_html(
        "-TK 4,500", prev_val_str="TK 41,847", pct_val=-10.8, cmp_label="7D Avg"
    )
    assert "delta-down" in html_down
    assert "▼ -TK 4,500 (-10.8%)" in html_down
    assert "vs 7D Avg (TK 41,847)" in html_down


def test_resolve_cmp_label():
    assert _resolve_cmp_label(None, "7D Avg", "Today", st) == "7D Avg"
    assert _resolve_cmp_label(pd.DataFrame(), "7D Avg", "Today", st) == "7D Avg"


def test_render_operational_metrics_smoke():
    mapping = {
        "name": "Item Name",
        "cost": "Item Cost",
        "qty": "Quantity",
        "date": "Order Date",
        "order_id": "Order ID",
        "phone": "Phone (Billing)",
        "sku": "SKU",
    }
    # Test with empty DataFrame and None comparison frame
    with (
        patch("streamlit.session_state", {}),
        patch("src.components.dashboard.dashboard_metrics.render_metric_cards"),
    ):
        render_operational_metrics(pd.DataFrame(), None, "Today", mapping, mapping)
        render_operational_metrics(None, None, "Today", mapping, mapping)
