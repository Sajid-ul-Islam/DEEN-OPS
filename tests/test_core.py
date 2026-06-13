import pandas as pd
import pytest
from src.inventory import core as inv_core


def test_identify_columns():
    df = pd.DataFrame(
        {
            "item name": ["A", "B"],
            "price": [10, 20],
            "quantity": [1, 2],
            "sku": ["SKU1", "SKU2"],
        }
    )

    a_col, q_col, t_col, s_col = inv_core.identify_columns(df)

    assert t_col == "item name"
    assert q_col == "quantity"
    assert s_col == "sku"


def test_get_group_by_column():
    df = pd.DataFrame(
        {"Order Number": ["1001", "1001", "1002"], "product name": ["A", "B", "C"]}
    )

    g_col = inv_core.get_group_by_column(df)
    assert g_col == "Order Number"


def test_split_variation():
    title, var = inv_core.item_name_to_title_size("Product A - Size M")
    assert title == "Product A"
    assert var == "Size M"

    title3, var3 = inv_core.item_name_to_title_size("Plain Product")
    assert title3 == "Plain Product"
    assert var3 == "NO_SIZE"


def test_add_stock_columns():
    master_df = pd.DataFrame(
        {
            "item name": ["Product A", "Product B", "Product C"],
            "sku": ["SKUA", "SKUB", "SKUC"],
        }
    )

    inv_map = {
        "product a": {"Store1": 5, "Store2": 2},
        "product b": {"Store1": 0, "Store2": 10},
    }

    sku_map = {"SKUA": "product a", "SKUB": "product b"}

    res, _ = inv_core.add_stock_columns_from_inventory(
        product_df=master_df,
        item_name_col="item name",
        inventory=inv_map,
        locations=["Store1", "Store2"],
        sku_col="sku",
        sku_to_title_size=sku_map,
    )
    assert "Store1" in res.columns
    assert "Store2" in res.columns
    assert "Fulfillment" in res.columns
    assert "Dispatch Suggestion" in res.columns

    assert res.loc[0, "Store1"] == 5
    assert res.loc[0, "Store2"] == 2
    assert res.loc[1, "Store2"] == 10

    assert len(res) == 3


def test_add_stock_columns_size_mismatch_oos():
    # Product A is ordered in XL size but inventory only has Product A in M and L sizes
    master_df = pd.DataFrame(
        {
            "item name": ["Product A - XL"],
            "sku": ["SKUA"],
        }
    )

    inv_map = {
        "product a - m": {"Store1": 5},
        "product a - l": {"Store1": 2},
        "skua": {"Store1": 7},
        "sku:skua_sz:m": {"Store1": 5},
        "sku:skua_sz:l": {"Store1": 2},
    }

    sku_map = {"SKUA": "product a - l"}

    res, matched_count = inv_core.add_stock_columns_from_inventory(
        product_df=master_df,
        item_name_col="item name",
        inventory=inv_map,
        locations=["Store1"],
        sku_col="sku",
        sku_to_title_size=sku_map,
    )

    # Since XL is requested, and Product A has size variations (M, L) in inventory,
    # the matching should NOT fall back to SKUA (which has 7 pcs). The XL stock should be 0.
    assert res.loc[0, "Store1"] == 0
    assert "OOS" in res.loc[0, "Dispatch Suggestion"] or "Unfulfillable" in res.loc[0, "Dispatch Suggestion"]
    assert matched_count == 0
