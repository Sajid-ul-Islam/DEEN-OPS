"""Unit tests for dispatch_export_view component."""

from unittest.mock import patch
import pandas as pd

from src.components.dashboard.dispatch_export_view import render_dispatch_export
from src.config.constants import bd_now


def test_render_dispatch_export_empty_df():
    # Should safely return without error when dataframe is empty
    with patch("streamlit.session_state", {}):
        render_dispatch_export(raw_df=pd.DataFrame())


def test_render_dispatch_export_none_df():
    with patch("streamlit.session_state", {}):
        render_dispatch_export(raw_df=None)


def test_render_dispatch_export_with_data():
    now_ts = bd_now().strftime("%Y-%m-%d %H:%M:%S")
    sample_df = pd.DataFrame(
        [
            {
                "Order ID": 19001,
                "Item Name": "Classic Panjabi - M",
                "SKU": "DEEN-PJ-001",
                "Product ID": 501,
                "Variation ID": 502,
                "Quantity": 1,
                "Item Cost": 2500.0,
                "Order Status": "completed",
                "Order Date Modified": now_ts,
                "mod_dt_parsed": pd.to_datetime(now_ts),
                "dt_parsed": pd.to_datetime(now_ts),
                "_order_source": "Online",
                "Stock Out Outlet": "Mirpur",
                "Full Name (Billing)": "Rahim Khan",
                "Phone (Billing)": "01711000000",
                "Shipping City": "Dhaka",
                "Shipping Address 1": "Mirpur 10",
                "Pathao Consignment ID": "PTC123456",
            }
        ]
    )

    with (
        patch("streamlit.session_state", {}),
        patch("streamlit.dataframe") as mock_df,
        patch("streamlit.download_button"),
    ):
        render_dispatch_export(raw_df=sample_df)

        # Ensure dataframe was displayed
        assert mock_df.called
        displayed_df = mock_df.call_args_list[0][0][0]
        assert "Stock Out Outlet" in displayed_df.columns
        assert displayed_df.iloc[0]["Stock Out Outlet"] == "Mirpur"
        assert "Unit COGS" in displayed_df.columns
        assert "Line Total" in displayed_df.columns


def test_flatten_order_stock_out_outlet():
    from src.services.woocommerce.client import _flatten_order

    order = {
        "id": 19856,
        "number": "19856",
        "status": "completed",
        "date_created": "2026-11-09T10:00:00",
        "date_modified": "2026-11-09T12:00:00",
        "date_completed": "2026-11-09T12:00:00",
        "total": "4000.00",
        "billing": {"first_name": "Rahim", "last_name": "Khan"},
        "shipping": {"city": "Dhaka"},
        "meta_data": [
            {
                "key": "_sip_waterfall_deductions",
                "value": [
                    {
                        "outlet_id": 2,
                        "outlet_slug": "mirpur-12",
                        "product_id": 9462,
                        "variation_id": 9467,
                        "qty": 1,
                    },
                    {
                        "outlet_id": 8,
                        "outlet_slug": "wari",
                        "product_id": 9462,
                        "variation_id": 9468,
                        "qty": 1,
                    },
                ],
            }
        ],
        "line_items": [
            {
                "id": 1,
                "name": "Item 1",
                "product_id": 9462,
                "variation_id": 9467,
                "quantity": 1,
                "price": 2000,
                "total": "2000",
            },
            {
                "id": 2,
                "name": "Item 2",
                "product_id": 9462,
                "variation_id": 9468,
                "quantity": 1,
                "price": 2000,
                "total": "2000",
            },
        ],
    }

    flattened = _flatten_order(order)
    assert len(flattened) == 2
    assert flattened[0]["Stock Out Outlet"] == "Mirpur"
    assert flattened[1]["Stock Out Outlet"] == "Wari"
