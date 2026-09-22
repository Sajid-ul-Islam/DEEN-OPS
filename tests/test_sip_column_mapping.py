"""Tests for the SIP mapper's semantic column auto-mapping and its tolerance
of missing (optional) columns in uploaded order exports."""

from __future__ import annotations

import pandas as pd

from src.processing.sip_outlet_processor import (
    auto_map_columns,
    generate_outlet_product_listing,
    process_order_item_outlets,
)


def _standard_export() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Order Number": [1001, 1001, 1002],
            "Order Date": ["2026-09-01", "2026-09-01", "2026-09-01"],
            "Item Name": ["Widget A", "Widget B", "Widget A"],
            "SKU": ["WA-1", "WB-1", "WA-1"],
            "Quantity": [2, 1, 1],
            "Item Cost": [100.0, 50.0, 100.0],
            "SIP": [
                '{"w1":"warehouse"}',
                '{"w1":"mirpur-12"}',
                '{"w1":"cumilla"}',
            ],
        }
    )


class TestAutoMapColumns:
    def test_standard_woocommerce_headers_map_exactly(self):
        m = auto_map_columns(_standard_export())
        assert m["order"] == "Order Number"
        assert m["sip"] == "SIP"
        assert m["item"] == "Item Name"
        assert m["sku"] == "SKU"
        assert m["qty"] == "Quantity"
        assert m["cost"] == "Item Cost"

    def test_variant_headers_map_by_normalization(self):
        df = pd.DataFrame(
            columns=[
                "order_number",
                "Product_Name",
                "item_sku",
                "Qty",
                "Routing Json",
            ]
        )
        m = auto_map_columns(df)
        assert m["order"] == "order_number"
        assert m["item"] == "Product_Name"
        assert m["sku"] == "item_sku"
        assert m["qty"] == "Qty"

    def test_missing_optional_roles_are_none(self):
        df = pd.DataFrame({"Order Number": [1], "Product": ["A"]})
        m = auto_map_columns(df)
        assert m["order"] == "Order Number"
        assert m["item"] == "Product"
        assert m["sku"] is None
        assert m["qty"] is None
        assert m["sip"] is None

    def test_empty_dataframe_yields_all_none(self):
        m = auto_map_columns(pd.DataFrame())
        assert all(v is None for v in m.values())

    def test_one_column_never_serves_two_roles(self):
        # "Item Cost" must map to cost, not qty, even though 'cost' appears later.
        df = pd.DataFrame(columns=["Item Cost", "Item Name"])
        m = auto_map_columns(df)
        assert m["cost"] == "Item Cost"
        assert m["qty"] is None


class TestMissingColumnResilience:
    def test_process_without_sip_column_defaults_to_warehouse(self):
        df = pd.DataFrame(
            {
                "Order Number": [1, 1, 2],
                "Item Name": ["A", "B", "C"],
            }
        )
        out = process_order_item_outlets(df, order_col="Order Number", sip_col="SIP")
        assert out["Item Outlet"].tolist() == ["Warehouse", "Warehouse", "Warehouse"]

    def test_listing_without_qty_column_counts_units_as_one(self):
        df = pd.DataFrame(
            {
                "Order Number": [1, 1, 2],
                "Product": ["A", "B", "A"],
                "Item Outlet": ["Warehouse", "Warehouse", "Mirpur"],
            }
        )
        out = generate_outlet_product_listing(
            df,
            outlet="Warehouse",
            item_col="Product",
            qty_col="Quantity",
            sku_col=None,
            outlet_col="Item Outlet",
        )
        assert len(out) == 2  # A and B, qty placeholder of 1 each
        assert out["__qty_placeholder__"].sum() == 2

    def test_listing_without_sku_column_still_aggregates(self):
        df = pd.DataFrame(
            {
                "Order Number": [1, 1],
                "Product": ["A", "A"],
                "Quantity": [2, 3],
                "Item Outlet": ["Warehouse", "Warehouse"],
            }
        )
        out = generate_outlet_product_listing(
            df,
            outlet="Warehouse",
            item_col="Product",
            qty_col="Quantity",
            sku_col=None,
            outlet_col="Item Outlet",
        )
        assert out.iloc[0]["Quantity"] == 5
