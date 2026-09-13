"""Unit tests for product categorization and normalization rules.

Ensures:
- Formal Panjabi is classified as Panjabi
- Executive Formal / Formal Shirt is classified as FS Shirt / Formal Shirt / Formal
"""

import pytest

from src.components.dashboard.dashboard_charts import get_short_category_label
from src.processing.categorization import (
    get_category_for_sales,
    get_sub_category_for_sales,
)
from src.processing.order_processor import get_short_sub_category
from src.processing.stock_categorization import map_to_csv_category


@pytest.mark.parametrize(
    ("product_name", "expected_cat", "expected_subcat"),
    [
        ("Formal Panjabi", "Panjabi", "Panjabi"),
        ("Formal Panjabi - L", "Panjabi", "Panjabi"),
        ("White Formal Panjabi", "Panjabi", "Panjabi"),
        ("Executive Formal", "FS Shirt", "Formal Shirt"),
        ("Executive Formal Shirt", "FS Shirt", "Formal Shirt"),
        ("Executive Formal Shirt - XL", "FS Shirt", "Formal Shirt"),
        ("White Executive Formal Shirt", "FS Shirt", "Formal Shirt"),
        ("Formal Shirt", "FS Shirt", "Formal Shirt"),
        ("Formal Shirt - M", "FS Shirt", "Formal Shirt"),
        ("Executive Shirt", "FS Shirt", "Formal Shirt"),
    ],
)
def test_sales_categorization(product_name, expected_cat, expected_subcat):
    cat = get_category_for_sales(product_name)
    assert cat == expected_cat
    subcat = get_sub_category_for_sales(product_name, cat)
    assert subcat == expected_subcat


@pytest.mark.parametrize(
    ("product_name", "expected_short_label"),
    [
        ("Formal Panjabi", "Panjabi"),
        ("Formal Panjabi - L", "Panjabi"),
        ("Executive Formal", "Formal"),
        ("Executive Formal Shirt", "Formal"),
        ("Formal Shirt", "Formal"),
        ("Formal Shirt - M", "Formal"),
        ("Casual Shirt", "Casual"),
        ("Casual Shirt - Full Sleeve", "Casual"),
        ("Full Sleeve Shirt", "FS Shirt"),
        ("FS Shirt", "FS Shirt"),
    ],
)
def test_dashboard_short_category_label(product_name, expected_short_label):
    label = get_short_category_label(product_name)
    assert label == expected_short_label


@pytest.mark.parametrize(
    ("product_name", "expected_stock_cat"),
    [
        ("Formal Panjabi", "Panjabi"),
        ("White Formal Panjabi - XL", "Panjabi"),
        ("Executive Formal", "Formal Shirt"),
        ("Executive Formal Shirt", "Formal Shirt"),
        ("Formal Shirt", "Formal Shirt"),
    ],
)
def test_stock_categorization(product_name, expected_stock_cat):
    stock_cat = map_to_csv_category(product_name)
    assert stock_cat == expected_stock_cat


@pytest.mark.parametrize(
    ("product_name", "expected_type"),
    [
        ("Formal Panjabi", "Panjabi"),
        ("Executive Formal", "Formal"),
        ("Executive Formal Shirt", "Formal"),
        ("Formal Shirt", "Formal"),
        ("Casual Shirt", "Casual"),
        ("Casual Shirt - Full Sleeve", "Casual"),
        ("Casual Shirt - Half Sleeve", "Casual"),
        ("Full Sleeve Casual Shirt", "Casual"),
        ("Full Sleeve Shirt", "FS Shirt"),
        ("FS Shirt", "FS Shirt"),
        ("Half Sleeve Shirt", "HS Shirt"),
        ("HS Shirt", "HS Shirt"),
        ("Full Sleeve T-Shirt", "FS T-Shirt"),
        ("HS T-Shirt", "HS T-Shirt"),
    ],
)
def test_order_processor_get_short_sub_category(product_name, expected_type):
    item_type = get_short_sub_category(product_name)
    assert item_type == expected_type
