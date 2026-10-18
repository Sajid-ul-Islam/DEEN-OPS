"""Unit tests verifying Data Parser functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import streamlit as st


def test_delivery_parser_content_does_not_fragment_tabs():
    """Verify the delivery parser content renderer does not open split tabs."""
    from src.pages.delivery_parser import render_delivery_parser_content

    tabs_called = False

    def mock_tabs(labels):
        nonlocal tabs_called
        tabs_called = True
        return [MagicMock() for _ in labels]

    with patch.object(st, "tabs", side_effect=mock_tabs):
        render_delivery_parser_content()
        # Ensure content renderer does NOT use split tabs
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
