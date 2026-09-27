"""Unit tests for DEEN Selects vs Regular Analytics module."""

import pandas as pd

from src.processing.selects_analytics import (
    REGULAR_LABEL,
    SELECTS_LABEL,
    classify_product_line,
    compute_selects_regular_analytics,
)


def test_classify_product_line_selects():
    """Verify that DEEN Selects products are properly classified."""
    assert classify_product_line("DEEN Selects Luxury Panjabi") == SELECTS_LABEL
    assert classify_product_line("Classic Shirt [Selects]") == SELECTS_LABEL
    assert classify_product_line("Select Oxford Shirt") == SELECTS_LABEL
    assert classify_product_line("Item Name", sku="DS-1001-L") == SELECTS_LABEL
    assert classify_product_line("Item Name", sku="SEL-092") == SELECTS_LABEL
    assert classify_product_line("Item Name", category="DEEN Selects") == SELECTS_LABEL
    # Live WooCommerce Category 1281 Brands
    assert classify_product_line("Pull & Bear Cargo Trouser in Black") == SELECTS_LABEL
    assert classify_product_line("Springfield Polo Shirt") == SELECTS_LABEL
    assert (
        classify_product_line("Calvin Klein Stretch Jeans - Regular Fit")
        == SELECTS_LABEL
    )
    assert (
        classify_product_line("Levi's 505 Non Stretch Jeans - Regular Fit")
        == SELECTS_LABEL
    )
    assert classify_product_line("Allen Solly Hoodie") == SELECTS_LABEL
    assert classify_product_line("Sorbino Denim Jacket") == SELECTS_LABEL
    assert classify_product_line("Lee Workwear Loose Carpenter Twill") == SELECTS_LABEL


def test_classify_product_line_regular():
    """Verify that regular products default to DEEN Regular."""
    assert classify_product_line("Classic Polo Shirt") == REGULAR_LABEL
    assert classify_product_line("Slim Fit Raw Jeans") == REGULAR_LABEL
    assert classify_product_line("Cotton Terry Sweatshirt") == REGULAR_LABEL
    assert (
        classify_product_line("", sku="POLO-001", category="Polo Shirt")
        == REGULAR_LABEL
    )


def test_compute_selects_regular_analytics_empty():
    """Verify handling of empty DataFrame."""
    res = compute_selects_regular_analytics(pd.DataFrame())
    assert res["summary"]["total_revenue"] == 0.0
    assert res["summary"]["total_qty"] == 0
    assert res["selects_cat_summary"].empty
    assert res["regular_cat_summary"].empty
    assert res["comparison_matrix"].empty


def test_compute_selects_regular_analytics_with_data():
    """Verify revenue, quantity, and category calculations."""
    df = pd.DataFrame(
        [
            {
                "Order ID": 101,
                "Product Name": "DEEN Selects Silk Panjabi - L",
                "SKU": "DS-PAN-01",
                "Category": "Panjabi",
                "Sub-Category": "Panjabi",
                "Quantity": 2,
                "Item Cost": 3500.0,
                "Total Amount": 7000.0,
            },
            {
                "Order ID": 102,
                "Product Name": "DEEN Selects Premium Jeans - 32",
                "SKU": "DS-JNS-02",
                "Category": "Jeans",
                "Sub-Category": "Slim Fit Jeans",
                "Quantity": 1,
                "Item Cost": 2500.0,
                "Total Amount": 2500.0,
            },
            {
                "Order ID": 103,
                "Product Name": "Basic Polo Shirt - Navy - M",
                "SKU": "REG-POLO-01",
                "Category": "Polo Shirt",
                "Sub-Category": "Polo Shirt",
                "Quantity": 3,
                "Item Cost": 1200.0,
                "Total Amount": 3600.0,
            },
            {
                "Order ID": 103,
                "Product Name": "Regular Fit Jeans - 34",
                "SKU": "REG-JNS-01",
                "Category": "Jeans",
                "Sub-Category": "Regular Fit Jeans",
                "Quantity": 1,
                "Item Cost": 1800.0,
                "Total Amount": 1800.0,
            },
        ]
    )

    analytics = compute_selects_regular_analytics(df)
    summary = analytics["summary"]

    # Selects: 7000 + 2500 = 9500, Qty: 2 + 1 = 3
    assert summary["selects_rev"] == 9500.0
    assert summary["selects_qty"] == 3
    assert summary["selects_orders"] == 2

    # Regular: 3600 + 1800 = 5400, Qty: 3 + 1 = 4
    assert summary["regular_rev"] == 5400.0
    assert summary["regular_qty"] == 4
    assert summary["regular_orders"] == 1

    # Total: 14900, Qty: 7
    assert summary["total_revenue"] == 14900.0
    assert summary["total_qty"] == 7

    # Shares
    assert round(summary["selects_rev_share"], 1) == round(9500.0 / 14900.0 * 100.0, 1)

    # Category summary
    sel_cat = analytics["selects_cat_summary"]
    assert len(sel_cat) == 2
    assert "Panjabi" in sel_cat["Category"].values
    assert "Jeans" in sel_cat["Category"].values

    reg_cat = analytics["regular_cat_summary"]
    assert len(reg_cat) == 2
    assert "Polo Shirt" in reg_cat["Category"].values
    assert "Jeans" in reg_cat["Category"].values

    # Comparison matrix
    matrix = analytics["comparison_matrix"]
    assert len(matrix) == 3  # Panjabi, Jeans, Polo Shirt
    jeans_row = matrix[matrix["Category"] == "Jeans"].iloc[0]
    assert jeans_row["Selects Revenue"] == 2500.0
    assert jeans_row["Regular Revenue"] == 1800.0
    assert jeans_row["Total Revenue"] == 4300.0
