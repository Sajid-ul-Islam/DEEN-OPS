"""Unit tests for WooCommerce Cost of Goods Sold (COGS) fetching and enrichment service."""

import pandas as pd
import pytest

from src.services.woocommerce.cogs_service import (
    _MEMORY_COGS_CACHE,
    enrich_dataframe_with_cogs,
    extract_cogs_from_meta,
    get_cogs_for_item,
)


def test_extract_cogs_from_meta():
    # Test _sip_buying_price
    meta_sip = [{"id": 1, "key": "_sip_buying_price", "value": "1180"}]
    assert extract_cogs_from_meta(meta_sip) == 1180.0

    # Test _alg_wc_cog_cost
    meta_alg = [{"id": 2, "key": "_alg_wc_cog_cost", "value": "450.50"}]
    assert extract_cogs_from_meta(meta_alg) == 450.50

    # Test fallback with comma
    meta_comma = [{"id": 3, "key": "_wc_cog_cost", "value": "1,250.00"}]
    assert extract_cogs_from_meta(meta_comma) == 1250.0

    # Test empty or invalid
    assert extract_cogs_from_meta([]) is None
    assert extract_cogs_from_meta(None) is None
    assert extract_cogs_from_meta([{"key": "unrelated", "value": "123"}]) is None
    assert extract_cogs_from_meta([{"key": "_sip_buying_price", "value": ""}]) is None


def test_get_cogs_for_item():
    _MEMORY_COGS_CACHE["101-0100-TEST"] = 990.0
    _MEMORY_COGS_CACHE["v_12345"] = 850.0
    _MEMORY_COGS_CACHE["p_67890"] = 600.0

    # By Variation ID
    assert get_cogs_for_item(variation_id="12345") == 850.0
    # By SKU
    assert get_cogs_for_item(sku="101-0100-TEST") == 990.0
    # By Product ID
    assert get_cogs_for_item(product_id="67890") == 600.0
    # Unknown
    assert get_cogs_for_item(sku="UNKNOWN-SKU") is None


def test_enrich_dataframe_with_cogs():
    _MEMORY_COGS_CACHE["101-0100-173"] = 1180.0
    _MEMORY_COGS_CACHE["115-0101-002"] = 450.0

    df = pd.DataFrame(
        [
            {
                "Order ID": 1001,
                "SKU": "101-0100-173",
                "Product ID": 19276,
                "Variation ID": 19282,
                "Quantity": 2,
                "Item Cost": 2000.0,
                "Line Total": 4000.0,
            },
            {
                "Order ID": 1002,
                "SKU": "115-0101-002",
                "Product ID": 19595,
                "Variation ID": 0,
                "Quantity": 1,
                "Item Cost": 800.0,
                "Line Total": 800.0,
            },
        ]
    )

    enriched = enrich_dataframe_with_cogs(df, fetch_missing=False)

    assert "Unit COGS" in enriched.columns
    assert "Total COGS" in enriched.columns
    assert "Gross Profit" in enriched.columns
    assert "Profit Margin (%)" in enriched.columns

    # Row 0: 2 units @ 1180 = 2360 Total COGS. Revenue = 4000. Profit = 1640.
    row0 = enriched.iloc[0]
    assert row0["Unit COGS"] == 1180.0
    assert row0["Total COGS"] == 2360.0
    assert row0["Gross Profit"] == 1640.0
    assert pytest.approx(row0["Profit Margin (%)"], abs=0.1) == 41.0

    # Row 1: 1 unit @ 450 = 450 Total COGS. Revenue = 800. Profit = 350.
    row1 = enriched.iloc[1]
    assert row1["Unit COGS"] == 450.0
    assert row1["Total COGS"] == 450.0
    assert row1["Gross Profit"] == 350.0
    assert pytest.approx(row1["Profit Margin (%)"], abs=0.1) == 43.8


def test_enrich_dataframe_empty():
    assert enrich_dataframe_with_cogs(pd.DataFrame()).empty
    assert enrich_dataframe_with_cogs(None) is None
