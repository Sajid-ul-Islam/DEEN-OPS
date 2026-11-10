"""Unit tests for Orders Ledger & Parcel Audit View."""

from unittest.mock import patch
import pandas as pd

from src.components.dashboard.orders_ledger_view import render_orders_ledger_view


def test_render_orders_ledger_empty():
    """Verify empty DataFrame renders friendly notification without error."""
    with patch("streamlit.info") as mock_info:
        render_orders_ledger_view(pd.DataFrame())
        mock_info.assert_called_once_with(
            "No orders data available to display in ledger."
        )


def test_render_orders_ledger_missing_line_total():
    """Ensure ledger renders cleanly without KeyError when Line Total is absent."""
    df_no_line_total = pd.DataFrame(
        [
            {
                "Order ID": 1001,
                "Order Date": "2026-11-09 14:00:00",
                "Customer": "Karim Rahman",
                "Phone": "01711000000",
                "City": "Dhaka",
                "Order Status": "completed",
                "Quantity": 2,
                "Item Cost": 1250.0,
            },
            {
                "Order ID": 1001,
                "Order Date": "2026-11-09 14:00:00",
                "Customer": "Karim Rahman",
                "Phone": "01711000000",
                "City": "Dhaka",
                "Order Status": "completed",
                "Quantity": 1,
                "Item Cost": 850.0,
            },
            {
                "Order ID": 1002,
                "Order Date": "2026-11-09 15:30:00",
                "Customer": "Salma Begum",
                "Phone": "01811000000",
                "City": "Chittagong",
                "Order Status": "shipped",
                "Quantity": 1,
                "Item Cost": 2500.0,
            },
        ]
    )

    with (
        patch("streamlit.radio", return_value="Order-Wise (Consolidated)"),
        patch("streamlit.text_input", return_value=""),
        patch("streamlit.dataframe") as mock_df,
    ):
        render_orders_ledger_view(df_no_line_total)
        assert mock_df.called
        rendered_frame = mock_df.call_args[0][0]
        assert "Line Total" in rendered_frame.columns
        # Order 1001 total should be 2*1250 + 1*850 = 3350
        o1001 = rendered_frame[rendered_frame["Order ID"] == 1001]
        assert float(o1001["Line Total"].iloc[0]) == 3350.0


def test_render_orders_ledger_mixed_order_ids_and_item_wise():
    """Ensure mixed alphanumeric and integer Order IDs sort without TypeError."""
    df_mixed = pd.DataFrame(
        [
            {
                "Order ID": 1001,
                "Order Date": "2026-11-09 14:00:00",
                "Customer": "Karim",
                "Phone": "01711000000",
                "City": "Dhaka",
                "Status": "completed",
                "Quantity": 1,
                "Item Cost": 1500.0,
            },
            {
                "Order ID": "D-9999",
                "Order Date": "2026-11-09 15:00:00",
                "Customer": "Exchange Client",
                "Phone": "01911000000",
                "City": "Dhaka",
                "Status": "completed",
                "Quantity": 1,
                "Item Cost": 0.0,
            },
        ]
    )

    # Test Order-Wise view
    with (
        patch("streamlit.radio", return_value="Order-Wise (Consolidated)"),
        patch("streamlit.text_input", return_value=""),
        patch("streamlit.dataframe") as mock_df,
    ):
        render_orders_ledger_view(df_mixed)
        assert mock_df.called
        rendered = mock_df.call_args[0][0]
        assert len(rendered) == 2

    # Test Item-Wise view
    with (
        patch("streamlit.radio", return_value="Item-Wise (Granular)"),
        patch("streamlit.text_input", return_value=""),
        patch("streamlit.dataframe") as mock_df,
    ):
        render_orders_ledger_view(df_mixed)
        assert mock_df.called
        rendered = mock_df.call_args[0][0]
        assert len(rendered) == 2
        assert "Line Total" in rendered.columns
