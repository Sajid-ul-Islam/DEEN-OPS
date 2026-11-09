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


def test_kpi_card_exchange_sub_number():
    mapping = {
        "name": "Item Name",
        "cost": "Item Cost",
        "qty": "Quantity",
        "date": "Order Date",
        "order_id": "Order ID",
        "phone": "Phone (Billing)",
        "sku": "SKU",
    }
    # 2 regular orders, 1 exchange order
    df = pd.DataFrame(
        [
            {
                "Order ID": "1001",
                "Item Name": "Product A",
                "Item Cost": 1500.0,
                "Quantity": 1,
                "Order Date": "2026-11-09",
                "Order Status": "completed",
                "Created via": "checkout",
            },
            {
                "Order ID": "1002",
                "Item Name": "Product B",
                "Item Cost": 2000.0,
                "Quantity": 1,
                "Order Date": "2026-11-09",
                "Order Status": "completed",
                "Created via": "checkout",
            },
            {
                "Order ID": "18085",
                "Item Name": "Product A",
                "Item Cost": 0.0,
                "Quantity": 1,
                "Order Date": "2026-11-09",
                "Order Status": "completed",
                "Created via": "sip_exchange",
                "_sip_exchange_of": "17839",
            },
        ]
    )
    with (
        patch("streamlit.session_state", {}),
        patch(
            "src.components.dashboard.dashboard_metrics.render_metric_cards"
        ) as mock_cards,
    ):
        render_operational_metrics(df, None, "Today", mapping, mapping)
        assert mock_cards.called
        cards = mock_cards.call_args[0][0]
        # Order card is index 2
        order_card = cards[2]
        # Primary value should be regular checkout orders (2), NOT total orders (3)
        assert order_card.value == "2"
        # Sub-badge should include the exchange count (1 Exchange)
        assert "1 Exchange" in order_card.badge
        assert "3 Total" in order_card.badge
