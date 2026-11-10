"""Unit tests for multi-outlet and warehouse stock processing, filtering, and export analytics."""

from unittest.mock import patch
import pandas as pd
import pytest

from src.components.dashboard.outlet_stock_view import (
    export_stock_inventory_to_excel,
    render_outlet_stock_view,
)
from src.processing.stock_analytics import (
    build_stock_pivot_from_flat,
    compute_stock_kpis,
    ensure_stock_pivot_structure,
    filter_stock_inventory,
)


@pytest.fixture
def sample_stock_pivot():
    return pd.DataFrame(
        [
            {
                "Product": "Classic Panjabi Black",
                "Size": "M",
                "SKU": "PJ-BLK-M",
                "Category": "Panjabi",
                "Warehouse": 10,
                "Mirpur": 2,
                "Wari": 0,
                "Cumilla": 1,
                "Sylhet": 0,
                "Total": 13,
                "Status": "In Stock",
            },
            {
                "Product": "Classic Panjabi Black",
                "Size": "L",
                "SKU": "PJ-BLK-L",
                "Category": "Panjabi",
                "Warehouse": 2,
                "Mirpur": 1,
                "Wari": 0,
                "Cumilla": 0,
                "Sylhet": 0,
                "Total": 3,
                "Status": "Low Stock",
            },
            {
                "Product": "Luxury Thobe White",
                "Size": "54",
                "SKU": "TH-WHT-54",
                "Category": "Thobe",
                "Warehouse": 0,
                "Mirpur": 0,
                "Wari": 0,
                "Cumilla": 0,
                "Sylhet": 0,
                "Total": 0,
                "Status": "Out of Stock",
            },
            {
                "Product": "Bifold Leather Wallet",
                "Size": "",
                "SKU": "WLT-001",
                "Category": "Wallet",
                "Warehouse": 15,
                "Mirpur": 0,
                "Wari": 5,
                "Cumilla": 2,
                "Sylhet": 1,
                "Total": 23,
                "Status": "In Stock",
            },
        ]
    )


def test_build_stock_pivot_from_flat():
    flat_df = pd.DataFrame(
        [
            {
                "Product Name": "Cotton Panjabi",
                "SKU": "PJ-COT-01",
                "Stock": 8,
                "Size": "Size: XL",
                "Category": "Panjabi",
            }
        ]
    )
    pivot = build_stock_pivot_from_flat(flat_df)
    assert not pivot.empty
    assert "Product" in pivot.columns
    assert "Warehouse" in pivot.columns
    assert "Mirpur" in pivot.columns
    assert "Total" in pivot.columns
    assert pivot.iloc[0]["Size"] == "XL"
    assert pivot.iloc[0]["Warehouse"] == 8
    assert pivot.iloc[0]["Total"] == 8
    assert pivot.iloc[0]["Status"] == "In Stock"


def test_ensure_stock_pivot_structure(sample_stock_pivot):
    df_raw = sample_stock_pivot.drop(columns=["Total", "Status"])
    res = ensure_stock_pivot_structure(df_raw)
    assert "Total" in res.columns
    assert "Status" in res.columns
    assert res.iloc[0]["Total"] == 13
    assert res.iloc[0]["Status"] == "In Stock"
    assert res.iloc[1]["Status"] == "Low Stock"
    assert res.iloc[2]["Status"] == "Out of Stock"


def test_compute_stock_kpis(sample_stock_pivot):
    kpis = compute_stock_kpis(sample_stock_pivot)
    assert kpis["total_skus"] == 4
    # 13 + 3 + 0 + 23 = 39 total units
    assert kpis["total_stock"] == 39
    # 10 + 2 + 0 + 15 = 27 warehouse units
    assert kpis["warehouse_stock"] == 27
    # 39 - 27 = 12 outlet units
    assert kpis["outlets_stock"] == 12
    assert kpis["low_stock_count"] == 1
    assert kpis["out_of_stock_count"] == 1
    assert kpis["outlet_breakdown"]["Mirpur"] == 3
    assert kpis["outlet_breakdown"]["Wari"] == 5


def test_filter_stock_inventory_by_outlet(sample_stock_pivot):
    # Filter for Mirpur In Stock (> 0)
    mirpur_instock = filter_stock_inventory(
        sample_stock_pivot,
        outlet="Mirpur",
        stock_status="In Stock",
    )
    assert len(mirpur_instock) == 2
    assert all(mirpur_instock["Mirpur"] > 0)


def test_filter_stock_inventory_replenish_needed(sample_stock_pivot):
    # Mirpur replenishment needed: Warehouse > 0 but Mirpur <= 0
    # Row 3 (Wallet): Warehouse=15, Mirpur=0
    replenish = filter_stock_inventory(
        sample_stock_pivot,
        outlet="Mirpur",
        stock_status="Replenish Needed",
    )
    assert len(replenish) == 1
    assert replenish.iloc[0]["SKU"] == "WLT-001"


def test_filter_stock_inventory_search(sample_stock_pivot):
    # Search by SKU
    res = filter_stock_inventory(sample_stock_pivot, search_query="PJ-BLK-L")
    assert len(res) == 1
    assert res.iloc[0]["Size"] == "L"

    # Search by Name
    res2 = filter_stock_inventory(sample_stock_pivot, search_query="Thobe")
    assert len(res2) == 1
    assert res2.iloc[0]["Category"] == "Thobe"


def test_export_stock_inventory_to_excel(sample_stock_pivot):
    excel_bytes = export_stock_inventory_to_excel(sample_stock_pivot)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 0


def test_render_outlet_stock_view():
    with (
        patch("streamlit.session_state", {}),
        patch("streamlit.dataframe"),
        patch("streamlit.download_button"),
    ):
        render_outlet_stock_view()
