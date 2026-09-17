import os
import pandas as pd
import pytest

from src.processing.sip_outlet_processor import (
    compute_sip_stats,
    generate_outlet_product_listing,
    generate_pathao_bulk_consignments,
    get_fulfillment_group,
    is_inside_dhaka,
    normalize_outlet_name,
    normalize_phone_number,
    parse_sip_field,
    process_order_item_outlets,
)


def test_normalize_outlet_name():
    assert normalize_outlet_name("warehouse") == "Warehouse"
    assert normalize_outlet_name("wh") == "Warehouse"
    assert normalize_outlet_name("ecom") == "Warehouse"
    assert normalize_outlet_name("mirpur-12") == "Mirpur"
    assert normalize_outlet_name("mirpur") == "Mirpur"
    assert normalize_outlet_name("mirpur-12", canonical=False) == "Mirpur-12"
    assert normalize_outlet_name("cumilla") == "Cumilla"
    assert normalize_outlet_name("comilla") == "Cumilla"
    assert normalize_outlet_name("wari") == "Wari"
    assert normalize_outlet_name("sylhet") == "Sylhet"
    assert normalize_outlet_name("uttara") == "Uttara"
    assert normalize_outlet_name(None) == "Warehouse"
    assert normalize_outlet_name("") == "Warehouse"
    assert normalize_outlet_name("custom_hub") == "Custom Hub"


def test_parse_sip_field():
    # Valid JSON array
    json_str = '[{"outlet_id":1,"outlet_slug":"warehouse","qty":1},{"outlet_id":2,"outlet_slug":"mirpur-12","qty":1}]'
    parsed = parse_sip_field(json_str)
    assert len(parsed) == 2
    assert parsed[0]["outlet_slug"] == "warehouse"
    assert parsed[1]["outlet_slug"] == "mirpur-12"

    # Single dict JSON
    single_dict = '{"outlet_slug":"cumilla"}'
    parsed_single = parse_sip_field(single_dict)
    assert len(parsed_single) == 1
    assert parsed_single[0]["outlet_slug"] == "cumilla"

    # Empty & None
    assert parse_sip_field("") == []
    assert parse_sip_field(None) == []
    assert parse_sip_field("[]") == []

    # Fallback for plain text
    fallback = parse_sip_field("mirpur")
    assert len(fallback) == 1
    assert fallback[0]["outlet_slug"] == "mirpur"


def test_process_order_item_outlets_synthetic():
    df = pd.DataFrame(
        [
            # Order 1: Single item
            {
                "Order Number": 101,
                "Item Name": "Shirt A",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            # Order 2: Multi item (2 items)
            {
                "Order Number": 102,
                "Item Name": "Jeans 1",
                "SIP": '[{"outlet_slug":"warehouse"},{"outlet_slug":"mirpur-12"}]',
            },
            {
                "Order Number": 102,
                "Item Name": "Jeans 2",
                "SIP": '[{"outlet_slug":"warehouse"},{"outlet_slug":"mirpur-12"}]',
            },
            # Order 3: Multi item (3 items with split outlets)
            {
                "Order Number": 103,
                "Item Name": "Panjabi 1",
                "SIP": '[{"outlet_slug":"warehouse"},{"outlet_slug":"cumilla"},{"outlet_slug":"sylhet"}]',
            },
            {
                "Order Number": 103,
                "Item Name": "Panjabi 2",
                "SIP": '[{"outlet_slug":"warehouse"},{"outlet_slug":"cumilla"},{"outlet_slug":"sylhet"}]',
            },
            {
                "Order Number": 103,
                "Item Name": "Panjabi 3",
                "SIP": '[{"outlet_slug":"warehouse"},{"outlet_slug":"cumilla"},{"outlet_slug":"sylhet"}]',
            },
        ]
    )

    result = process_order_item_outlets(df)

    # Verify new column exists and is right next to SIP
    assert "Item Outlet" in result.columns
    sip_idx = result.columns.get_loc("SIP")
    assert result.columns.get_loc("Item Outlet") == sip_idx + 1

    # Verify values
    outlets = result["Item Outlet"].tolist()
    # Order 101 item 1 -> Warehouse
    assert outlets[0] == "Warehouse"
    # Order 102 item 1 -> Warehouse, item 2 -> Mirpur
    assert outlets[1] == "Warehouse"
    assert outlets[2] == "Mirpur"
    # Order 103 item 1 -> Warehouse, item 2 -> Cumilla, item 3 -> Sylhet
    assert outlets[3] == "Warehouse"
    assert outlets[4] == "Cumilla"
    assert outlets[5] == "Sylhet"


def test_process_order_item_outlets_edge_cases():
    # Empty DataFrame
    empty_df = pd.DataFrame(columns=["Order Number", "SIP"])
    res_empty = process_order_item_outlets(empty_df)
    assert "Item Outlet" in res_empty.columns
    assert len(res_empty) == 0

    # Missing column
    df_missing = pd.DataFrame({"Other": [1, 2]})
    res_missing = process_order_item_outlets(df_missing)
    assert "Item Outlet" in res_missing.columns
    assert (res_missing["Item Outlet"] == "Warehouse").all()

    # More rows than JSON items
    df_more_rows = pd.DataFrame(
        [
            {"Order Number": 201, "SIP": '[{"outlet_slug":"cumilla"}]'},
            {"Order Number": 201, "SIP": '[{"outlet_slug":"cumilla"}]'},
        ]
    )
    res_more = process_order_item_outlets(df_more_rows)
    assert res_more["Item Outlet"].iloc[0] == "Cumilla"
    assert res_more["Item Outlet"].iloc[1] == "Cumilla"


def test_compute_sip_stats():
    df = pd.DataFrame(
        [
            {"Order Number": 1, "Item Outlet": "Warehouse"},
            {"Order Number": 2, "Item Outlet": "Warehouse"},
            {"Order Number": 2, "Item Outlet": "Cumilla"},
            {"Order Number": 3, "Item Outlet": "Mirpur"},
            {"Order Number": 3, "Item Outlet": "Mirpur"},
        ]
    )
    stats = compute_sip_stats(df)
    assert stats["total_items"] == 5
    assert stats["total_orders"] == 3
    assert stats["multi_item_orders"] == 2
    assert stats["split_orders_count"] == 1  # Only Order 2 has multiple different outlets
    assert stats["split_orders"][0]["order_id"] == 2
    assert stats["outlet_counts"]["Warehouse"] == 2
    assert stats["outlet_counts"]["Cumilla"] == 1
    assert stats["outlet_counts"]["Mirpur"] == 2


def test_real_sample_file_processing():
    sample_file = "Product listing Sample input.xlsx"
    if not os.path.exists(sample_file):
        pytest.skip("Sample file not present in workspace")

    df = pd.read_excel(sample_file)
    processed = process_order_item_outlets(df)

    assert len(processed) == 48
    assert "Item Outlet" in processed.columns

    # Order 14948 (4 items: warehouse, warehouse, cumilla, warehouse)
    order_14948 = processed[processed["Order Number"] == 14948]["Item Outlet"].tolist()
    assert order_14948 == ["Warehouse", "Warehouse", "Cumilla", "Warehouse"]

    # Order 14967 (4 items: warehouse, mirpur-12, mirpur-12, mirpur-12)
    order_14967 = processed[processed["Order Number"] == 14967]["Item Outlet"].tolist()
    assert order_14967 == ["Warehouse", "Mirpur", "Mirpur", "Mirpur"]

    # Single item orders
    assert (
        processed[processed["Order Number"] == 14944]["Item Outlet"].iloc[0]
        == "Sylhet"
    )
    assert (
        processed[processed["Order Number"] == 14957]["Item Outlet"].iloc[0]
        == "Mirpur"
    )
    assert (
        processed[processed["Order Number"] == 14964]["Item Outlet"].iloc[0]
        == "Cumilla"
    )

    # Check stats
    stats = compute_sip_stats(processed)
    assert stats["total_items"] == 48
    assert stats["total_orders"] == 31
    assert stats["split_orders_count"] == 2  # 14948 and 14967 are split orders

    # Check Warehouse Product Listing
    wh_listing = generate_outlet_product_listing(
        processed,
        outlet="Warehouse",
        item_col="Item Name",
        qty_col="Quantity",
        sku_col="SKU",
        outlet_col="Item Outlet",
    )
    assert not wh_listing.empty
    assert wh_listing["Quantity"].sum() == 39  # Exactly 39 units from Warehouse
    assert len(wh_listing) == 31  # 31 unique SKUs

    # Check Cumilla Product Listing
    cumilla_listing = generate_outlet_product_listing(
        processed,
        outlet="Cumilla",
        item_col="Item Name",
        qty_col="Quantity",
        sku_col="SKU",
        outlet_col="Item Outlet",
    )
    assert cumilla_listing["Quantity"].sum() == 4  # Exactly 4 units from Cumilla


def test_get_fulfillment_group():
    assert get_fulfillment_group("warehouse") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("mirpur") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("mirpur-12") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("cumilla") == ("Cumilla", " c", "Cumilla Outlet")
    assert get_fulfillment_group("sylhet") == ("Sylhet", " s", "Sylhet Outlet")
    assert get_fulfillment_group("wari") == ("Wari", " w", "Wari Outlet")


def test_is_inside_dhaka():
    assert is_inside_dhaka("Dhaka", "Mirpur 10") is True
    assert is_inside_dhaka("Ashulia", "Savar") is True
    assert is_inside_dhaka("Chittagong", "Agrabad") is False
    assert is_inside_dhaka("", "", order_total_diff=50) is True
    assert is_inside_dhaka("", "", order_total_diff=90) is False


def test_normalize_phone_number():
    assert normalize_phone_number("01712345678") == "01712345678"
    assert normalize_phone_number("8801712345678") == "01712345678"
    assert normalize_phone_number("+8801712345678") == "01712345678"
    assert normalize_phone_number("1712345678") == "01712345678"
    assert normalize_phone_number("1712345678.0") == "01712345678"


def test_generate_pathao_bulk_sample_file():
    sample_file = "Product listing Sample input.xlsx"
    if not os.path.exists(sample_file):
        pytest.skip("Sample file not present in workspace")

    df = pd.read_excel(sample_file)
    pathao_df = generate_pathao_bulk_consignments(df)

    assert len(pathao_df) == 32  # 31 orders, 1 order split into 2
    assert "MerchantOrderId" in pathao_df.columns
    assert "AmountToCollect(*)" in pathao_df.columns
    assert "WarehouseOutlet" in pathao_df.columns

    # Check split order 14948
    order_14948 = pathao_df[pathao_df["MerchantOrderId"].astype(str).str.startswith("14948")]
    assert len(order_14948) == 2

    wh_part = order_14948[order_14948["MerchantOrderId"] == "14948"].iloc[0]
    assert wh_part["WarehouseOutlet"] == "Warehouse"
    assert wh_part["AmountToCollect(*)"] == 3102  # 3012 item cost + 90 delivery fee
    assert wh_part["ItemQuantity"] == 3

    cu_part = order_14948[order_14948["MerchantOrderId"] == "14948 c"].iloc[0]
    assert cu_part["WarehouseOutlet"] == "Cumilla Outlet"
    assert cu_part["AmountToCollect(*)"] == 364  # 364 item cost (0 delivery fee)
    assert cu_part["ItemQuantity"] == 1

    # Check combined warehouse + mirpur order 14967 (treated as one)
    order_14967 = pathao_df[pathao_df["MerchantOrderId"].astype(str).str.startswith("14967")]
    assert len(order_14967) == 1
    assert order_14967.iloc[0]["MerchantOrderId"] == "14967"
    assert order_14967.iloc[0]["WarehouseOutlet"] == "Warehouse"
    assert order_14967.iloc[0]["ItemQuantity"] == 4


