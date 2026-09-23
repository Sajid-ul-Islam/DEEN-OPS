"""Unit tests verifying consolidation of Order Tracking and elimination of redundancy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import streamlit as st


def test_woocommerce_orders_tab_contains_merged_pathao_tracking():
    """Verify render_woocommerce_orders_tab exposes Pathao Courier Tracking tab."""
    from src.pages.woocommerce_orders import render_woocommerce_orders_tab

    created_tab_labels = []

    def mock_tabs(labels):
        nonlocal created_tab_labels
        created_tab_labels = labels
        return [MagicMock() for _ in labels]

    with patch.object(st, "tabs", side_effect=mock_tabs):
        with (
            patch("src.pages.woocommerce_orders._render_live_orders_view") as mock_live,
            patch(
                "src.pages.pathao_orders.tracking_tab._render_status_tracking_tab"
            ) as mock_pathao_track,
            patch(
                "src.pages.woocommerce_orders._render_customer_profiles_view"
            ) as mock_cust,
            patch("src.pages.woocommerce_orders._render_bulk_updater_tab") as mock_sync,
        ):
            render_woocommerce_orders_tab()

            assert any("Pathao" in label for label in created_tab_labels)
            assert any("Live Orders" in label for label in created_tab_labels)
            assert any("Customer Profiles" in label for label in created_tab_labels)
            assert any("Bulk Status Sync" in label for label in created_tab_labels)
            assert len(created_tab_labels) == 4
            assert mock_live.called
            assert mock_pathao_track.called
            assert mock_cust.called
            assert mock_sync.called


def test_pathao_tab_no_longer_has_redundant_order_tracking():
    """Verify render_pathao_tab exclusively renders the Item Description Helper."""
    from src.pages.pathao_orders import render_pathao_tab

    with patch(
        "src.pages.pathao_orders.processing_tab._render_item_description_tab"
    ) as mock_helper:
        render_pathao_tab()
        assert mock_helper.called


def test_delivery_parser_is_unified_without_split_tabs():
    """Verify delivery parser renders as a unified smart parser without duplicate tabs."""
    from src.pages.delivery_parser import render_fuzzy_parser_tab

    tabs_called = False

    def mock_tabs(labels):
        nonlocal tabs_called
        tabs_called = True
        return [MagicMock() for _ in labels]

    with patch.object(st, "tabs", side_effect=mock_tabs):
        render_fuzzy_parser_tab()
        # Ensure it does NOT use split tabs anymore
        assert not tabs_called


def test_data_parser_has_delivery_and_item_description_features():
    """Verify render_data_parser_tab renders Delivery Data Parser and Item Description Helper."""
    from src.pages.delivery_parser import render_data_parser_tab

    created_tab_labels = []

    def mock_tabs(labels):
        nonlocal created_tab_labels
        created_tab_labels = labels
        return [MagicMock() for _ in labels]

    with patch.object(st, "tabs", side_effect=mock_tabs):
        with (
            patch(
                "src.pages.delivery_parser.render_delivery_parser_content"
            ) as mock_deliv,
            patch(
                "src.pages.delivery_parser.render_item_description_content"
            ) as mock_item_desc,
        ):
            render_data_parser_tab()
            assert any("Delivery" in label for label in created_tab_labels)
            assert any("Item Description" in label for label in created_tab_labels)
            assert len(created_tab_labels) == 2
            assert mock_deliv.called
            assert mock_item_desc.called


def test_stock_analytics_does_not_set_nav_override():
    """Verify render_stock_analytics_tab does not hijack navigation with _nav_override."""
    from src.pages.stock_analytics import render_stock_analytics_tab

    if "_nav_override" in st.session_state:
        del st.session_state["_nav_override"]

    with (
        patch("streamlit.tabs", return_value=[MagicMock(), MagicMock(), MagicMock()]),
        patch("src.pages.stock_analytics.render_woocommerce_stock_tab"),
        patch("src.pages.stock_analytics.render_outlet_stock_analysis_tab"),
        patch("src.pages.stock_analytics.render_sip_live_stock_tab"),
    ):
        render_stock_analytics_tab()
        assert "_nav_override" not in st.session_state
