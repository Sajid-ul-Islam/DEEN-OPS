import os
import pandas as pd
import pytest

from src.processing.sip_outlet_processor import (
    compute_sip_stats,
    convert_sip_to_smart_inventory,
    generate_outlet_product_listing,
    generate_pathao_bulk_consignments,
    get_fulfillment_group,
    is_inside_dhaka,
    normalize_outlet_name,
    normalize_phone_number,
    normalize_recipient_address,
    normalize_recipient_name,
    parse_sip_field,
    parse_stock_report,
    pivot_stock_report,
    process_order_item_outlets,
)


# ── Current Stock Report parsing (SIP stock tab uploads) ─────────────────────


def _stock_report_df(rows):
    """Build a raw Current Stock Report frame from (product, size, sku, outlet, qty, updated) tuples."""
    return pd.DataFrame(
        rows,
        columns=[
            "Product",
            "Size",
            "SKU",
            "Outlet",
            "Stock Qty",
            "Price",
            "Last Updated",
        ],
    )


class TestParseStockReport:
    def test_size_prefix_stripped(self):
        df = _stock_report_df(
            [
                (
                    "Polo A",
                    "Size: 3XL",
                    "102-1",
                    "Warehouse",
                    10,
                    "0.00",
                    "2026-09-22 08:11:29",
                ),
                (
                    "Panjabi B",
                    "Size: 44",
                    "106-1",
                    "Wari",
                    3,
                    "0.00",
                    "2026-09-22 07:42:18",
                ),
            ]
        )
        parsed = parse_stock_report(df)
        assert sorted(parsed["Size"]) == ["3XL", "44"]

    def test_size_prefix_case_insensitive_and_spaced(self):
        df = _stock_report_df(
            [
                (
                    "Polo A",
                    " size : M ",
                    "102-1",
                    "Warehouse",
                    1,
                    "0.00",
                    "2026-09-22 08:00:00",
                )
            ]
        )
        parsed = parse_stock_report(df)
        assert parsed["Size"].iloc[0] == "M"

    def test_blank_size_becomes_empty_string_not_nan(self):
        df = _stock_report_df(
            [
                (
                    "Wallet",
                    None,
                    "109-1",
                    "Warehouse",
                    5,
                    "0.00",
                    "2026-09-22 08:00:00",
                ),
                ("Belt", "", "109-2", "Warehouse", 2, "0.00", "2026-09-22 08:00:00"),
            ]
        )
        parsed = parse_stock_report(df)
        assert parsed["Size"].isna().sum() == 0
        assert (parsed["Size"] == "").sum() == 2

    def test_dedupe_keeps_latest_timestamp_per_outlet(self):
        """The export re-emits rows on every sync; latest Last Updated must win,
        not a naive sum (which would inflate stock)."""
        df = _stock_report_df(
            [
                (
                    "Export Shirt",
                    "",
                    "EXPORT-SHIRT-01",
                    "Warehouse",
                    2,
                    "0.00",
                    "2026-09-20 11:49:11",
                ),
                (
                    "Export Shirt",
                    "",
                    "EXPORT-SHIRT-01",
                    "Warehouse",
                    2,
                    "0.00",
                    "2026-09-20 11:49:12",
                ),
                (
                    "Export Shirt",
                    "",
                    "EXPORT-SHIRT-01",
                    "Warehouse",
                    0,
                    "0.00",
                    "2026-09-20 12:01:40",
                ),
            ]
        )
        parsed = parse_stock_report(df)
        assert len(parsed) == 1
        assert int(parsed["Stock Qty"].iloc[0]) == 0

    def test_dedupe_groups_by_size_and_outlet(self):
        """Rows differing in Size or Outlet are distinct keys — no cross-dropping."""
        df = _stock_report_df(
            [
                ("Jeans", "32", "101-1", "Warehouse", 9, "0.00", "2026-09-21 10:00:00"),
                ("Jeans", "34", "101-1", "Warehouse", 4, "0.00", "2026-09-21 10:00:00"),
                ("Jeans", "32", "101-1", "Wari", 1, "0.00", "2026-09-21 10:00:00"),
            ]
        )
        parsed = parse_stock_report(df)
        assert len(parsed) == 3

    def test_dedupe_tie_prefers_higher_qty_row(self):
        """Two rows with identical timestamps: the higher Stock Qty row wins,
        mirroring sort_values([_ts, 'Stock Qty']) + keep='last'."""
        df = _stock_report_df(
            [
                ("Tee", "M", "105-1", "Cumilla", 3, "0.00", "2026-09-22 06:51:10"),
                ("Tee", "M", "105-1", "Cumilla", 5, "0.00", "2026-09-22 06:51:10"),
            ]
        )
        parsed = parse_stock_report(df)
        assert len(parsed) == 1
        assert int(parsed["Stock Qty"].iloc[0]) == 5

    def test_dedupe_without_timestamps_falls_back_to_qty(self):
        """Missing Last Updated -> NaT for all rows; the qty sort key still
        disambiguates instead of picking arbitrarily."""
        df = _stock_report_df(
            [
                ("Tee", "M", "105-1", "Sylhet", 2, "0.00", ""),
                ("Tee", "M", "105-1", "Sylhet", 7, "0.00", ""),
            ]
        )
        parsed = parse_stock_report(df)
        assert len(parsed) == 1
        assert int(parsed["Stock Qty"].iloc[0]) == 7

    def test_mirpur_12_space_spelling_canonicalized(self):
        """CSV exports use 'Mirpur 12' (space) where the canonical map has 'mirpur-12'."""
        df = _stock_report_df(
            [("Tee", "M", "105-1", "Mirpur 12", 2, "0.00", "2026-09-22 07:07:27")]
        )
        parsed = parse_stock_report(df)
        assert (parsed["Outlet"] == "Mirpur").all()

    def test_unknown_outlet_preserved_as_own_name(self):
        df = _stock_report_df(
            [
                (
                    "Tee",
                    "M",
                    "105-1",
                    "Waterfall Outlet",
                    1,
                    "0.00",
                    "2026-09-20 03:40:51",
                )
            ]
        )
        parsed = parse_stock_report(df)
        assert (parsed["Outlet"] == "Waterfall Outlet").all()

    def test_outlet_aliases_and_case_folding(self):
        df = _stock_report_df(
            [
                ("A", "M", "S1", "WAREHOUSE", 1, "0.00", "2026-09-22 08:00:00"),
                ("B", "M", "S2", "comilla", 2, "0.00", "2026-09-22 08:00:00"),
            ]
        )
        parsed = parse_stock_report(df)
        assert sorted(parsed["Outlet"]) == ["Cumilla", "Warehouse"]

    def test_empty_and_missing_sku_dropped(self):
        df = _stock_report_df(
            [
                ("A", "M", "", "Warehouse", 1, "0.00", "2026-09-22 08:00:00"),
                ("B", "M", "nan", "Warehouse", 1, "0.00", "2026-09-22 08:00:00"),
                ("C", "M", "KEEP-1", "Warehouse", 1, "0.00", "2026-09-22 08:00:00"),
            ]
        )
        parsed = parse_stock_report(df)
        assert parsed["SKU"].tolist() == ["KEEP-1"]

    def test_junk_numeric_values_coerced_to_zero(self):
        df = _stock_report_df(
            [
                ("A", "M", "S1", "Warehouse", "3 pcs", "0.00", "2026-09-22 08:00:00"),
                ("B", "M", "S2", "Wari", "abc", "0.00", "2026-09-22 08:00:00"),
            ]
        )
        parsed = parse_stock_report(df)
        qty = parsed.set_index("SKU")["Stock Qty"]
        assert int(qty["S1"]) == 3
        assert int(qty["S2"]) == 0

    def test_price_strips_currency_noise(self):
        df = _stock_report_df(
            [("A", "M", "S1", "Warehouse", 1, "৳ 1,250.50", "2026-09-22 08:00:00")]
        )
        parsed = parse_stock_report(df)
        assert float(parsed["Price"].iloc[0]) == 1250.50

    def test_empty_frame_returns_typed_columns(self):
        parsed = parse_stock_report(pd.DataFrame())
        assert parsed.empty
        assert list(parsed.columns) == [
            "Product",
            "Size",
            "SKU",
            "Outlet",
            "Stock Qty",
            "Price",
            "Last Updated",
        ]

    def test_malformed_frame_raises_valueerror(self):
        with pytest.raises(ValueError, match="Missing required column"):
            parse_stock_report(pd.DataFrame({"Foo": [1]}))

    def test_header_aliases_accepted(self):
        raw = pd.DataFrame(
            {
                "Product Name": ["Polo A"],
                "Size": ["M"],
                "SKU": ["S1"],
                "Outlet Name": ["Warehouse"],
                "Qty": [4],
                "Price": ["0.00"],
                "Updated": ["2026-09-22 08:00:00"],
            }
        )
        parsed = parse_stock_report(raw)
        assert len(parsed) == 1
        assert int(parsed["Stock Qty"].iloc[0]) == 4
        assert parsed["Outlet"].iloc[0] == "Warehouse"


class TestPivotStockReport:
    def test_pivot_one_row_per_sku_with_outlet_columns(self):
        report = parse_stock_report(
            _stock_report_df(
                [
                    (
                        "Polo A",
                        "M",
                        "101-M",
                        "Warehouse",
                        5,
                        "0.00",
                        "2026-09-22 08:00:00",
                    ),
                    (
                        "Polo A",
                        "M",
                        "101-M",
                        "Mirpur 12",
                        2,
                        "0.00",
                        "2026-09-22 08:00:00",
                    ),
                    (
                        "Polo A",
                        "L",
                        "101-L",
                        "Cumilla",
                        3,
                        "0.00",
                        "2026-09-22 08:00:00",
                    ),
                ]
            )
        )
        pivot = pivot_stock_report(report)
        assert len(pivot) == 2
        # All canonical outlets are guaranteed as columns (0-filled), then extras
        assert list(pivot.columns) == [
            "Product",
            "Size",
            "SKU",
            "Warehouse",
            "Mirpur",
            "Wari",
            "Cumilla",
            "Sylhet",
            "Total",
        ]
        m_row = pivot[pivot["SKU"] == "101-M"].iloc[0]
        assert int(m_row["Warehouse"]) == 5
        assert int(m_row["Mirpur"]) == 2
        assert int(m_row["Total"]) == 7

    def test_pivot_orders_canonical_outlets_before_extras(self):
        report = parse_stock_report(
            _stock_report_df(
                [
                    ("A", "M", "S1", "Wari", 1, "0.00", "2026-09-22 08:00:00"),
                    ("A", "M", "S1", "Zeta Outlet", 2, "0.00", "2026-09-22 08:00:00"),
                    ("A", "M", "S1", "Warehouse", 3, "0.00", "2026-09-22 08:00:00"),
                ]
            )
        )
        pivot = pivot_stock_report(report)
        # Canonical outlets come first (0-filled when absent), extras after
        assert list(pivot.columns) == [
            "Product",
            "Size",
            "SKU",
            "Warehouse",
            "Mirpur",
            "Wari",
            "Cumilla",
            "Sylhet",
            "Zeta Outlet",
            "Total",
        ]

    def test_pivot_missing_outlets_filled_with_zero(self):
        report = parse_stock_report(
            _stock_report_df(
                [("A", "M", "S1", "Sylhet", 4, "0.00", "2026-09-22 08:00:00")]
            )
        )
        pivot = pivot_stock_report(report)
        assert int(pivot["Warehouse"].iloc[0]) == 0
        assert int(pivot["Total"].iloc[0]) == 4

    def test_pivot_empty_report_returns_empty_frame(self):
        pivot = pivot_stock_report(
            pd.DataFrame(columns=["Product", "Size", "SKU", "Outlet", "Stock Qty"])
        )
        assert pivot.empty
        assert list(pivot.columns) == ["Product", "Size", "SKU"]


def test_normalize_outlet_name():
    assert normalize_outlet_name("warehouse") == "Warehouse"
    assert normalize_outlet_name("wh") == "Warehouse"
    assert normalize_outlet_name("ecom") == "Warehouse"
    assert normalize_outlet_name("mirpur-12") == "Mirpur"
    assert normalize_outlet_name("mirpur") == "Mirpur"
    assert normalize_outlet_name("mirpur 12") == "Mirpur"
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
    assert (
        stats["split_orders_count"] == 1
    )  # Only Order 2 has multiple different outlets
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
        processed[processed["Order Number"] == 14944]["Item Outlet"].iloc[0] == "Sylhet"
    )
    assert (
        processed[processed["Order Number"] == 14957]["Item Outlet"].iloc[0] == "Mirpur"
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


def test_normalize_recipient_name():
    assert normalize_recipient_name("  mD.   rAKIB hassan ") == "Md. Rakib Hassan"
    assert normalize_recipient_name(None) == ""
    assert normalize_recipient_name(float("nan")) == ""
    assert normalize_recipient_name("") == ""
    assert normalize_recipient_name("nan") == ""
    assert normalize_recipient_name("N/A") == ""
    assert normalize_recipient_name(123) == "123"


def test_normalize_recipient_name_dedupes_redundant_words():
    """Duplicate/redundant words are filtered from recipient names."""
    assert normalize_recipient_name("Sakib SAKIB") == "Sakib"
    assert normalize_recipient_name("Rakib Rakib") == "Rakib"
    assert normalize_recipient_name("Md. Rakib Md. Rakib") == "Md. Rakib"
    assert normalize_recipient_name("Jahid Hasan Jahid") == "Jahid Hasan"
    # Distinct words are preserved in order
    assert normalize_recipient_name("Rakib Hassan") == "Rakib Hassan"


def test_normalize_recipient_name_dot_spacing_and_bangla():
    """Missing space after '.' is inserted; Bangla names pass through safely."""
    assert normalize_recipient_name("Md.Kefayoth Ullah Mustakin") == (
        "Md. Kefayoth Ullah Mustakin"
    )
    assert normalize_recipient_name("N.M Shakil") == "N. M Shakil"
    # Decimals and ellipses stay untouched
    assert normalize_recipient_name("Version 3.5 Test") == "Version 3.5 Test"
    assert normalize_recipient_name("Wait... What") == "Wait... What"
    # Bangla: title-casing is a no-op, duplicate words still filtered
    assert normalize_recipient_name("রুবেল রুবেল") == "রুবেল"
    assert normalize_recipient_name("রুবেল খান") == "রুবেল খান"
    assert normalize_recipient_name("মো. রাকিব হাসান") == "মো. রাকিব হাসান"
    # Bangla with missing space after dot (including combining vowel sign)
    assert normalize_recipient_name("মো.রাকিব") == "মো. রাকিব"
    assert normalize_recipient_name("কি.খা") == "কি. খা"


def test_normalize_recipient_address():
    assert (
        normalize_recipient_address("  house 12 ,  , road 3;   block b ")
        == "House 12, Road 3, Block B"
    )
    assert normalize_recipient_address("Mirpur-10, Dhaka,,") == "Mirpur-10, Dhaka"
    assert normalize_recipient_address(",,  ,Dhaka") == "Dhaka"
    assert normalize_recipient_address(None) == ""
    assert normalize_recipient_address("nan") == ""
    assert normalize_recipient_address("") == ""
    # Mixed separators all normalize to comma-separated parts
    assert (
        normalize_recipient_address("Road 5|Dhanmondi;Dhaka")
        == "Road 5, Dhanmondi, Dhaka"
    )
    # Missing space after '.' between letters is inserted
    assert (
        normalize_recipient_address("Shah-Mostofa Rh.Dorga Moulvibazar")
        == "Shah-Mostofa Rh. Dorga Moulvibazar"
    )
    # Decimals stay untouched
    assert normalize_recipient_address("Plot 3.5, Road 2") == "Plot 3.5, Road 2"
    # Bangla danda acts as a separator
    assert (
        normalize_recipient_address("গ্রাম। উত্তর নবীনগর। নারায়ণগঞ্জ")
        == "গ্রাম, উত্তর নবীনগর, নারায়ণগঞ্জ"
    )
    # Bangla with missing space after dot
    assert normalize_recipient_address("পো.এনায়েতনগর") == "পো. এনায়েতনগর"


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
    order_14948 = pathao_df[
        pathao_df["MerchantOrderId"].astype(str).str.startswith("14948")
    ]
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
    order_14967 = pathao_df[
        pathao_df["MerchantOrderId"].astype(str).str.startswith("14967")
    ]
    assert len(order_14967) == 1
    assert order_14967.iloc[0]["MerchantOrderId"] == "14967"
    assert order_14967.iloc[0]["WarehouseOutlet"] == "Warehouse"
    assert order_14967.iloc[0]["ItemQuantity"] == 4


def test_generate_pathao_bulk_name_address_sku():
    """Recipient name/address are normalized and ItemDesc carries per-item SKU."""
    df = pd.DataFrame(
        [
            {
                "Order Number": 301,
                "Item Name": "Oxford Shirt",
                "SKU": "OX-001",
                "Quantity": 2,
                "Item Cost": 1500,
                "Full Name (Shipping)": "  mD.   rAKIB hassan ",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "  house 12 , , road 3;  block b ",
                "City (Shipping)": "dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 302,
                "Item Name": "Polo Shirt",
                "SKU": "0",  # junk SKU must be omitted
                "Quantity": 1,
                "Item Cost": 800,
                "Full Name (Shipping)": "N/A",
                "Phone (Shipping)": "01712345679",
                "Address 1&2 (Shipping)": "nan",
                "City (Shipping)": None,
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
        ]
    )

    pathao_df = generate_pathao_bulk_consignments(df)
    assert len(pathao_df) == 2

    row_301 = pathao_df[pathao_df["MerchantOrderId"] == "301"].iloc[0]
    assert row_301["RecipientName(*)"] == "Md. Rakib Hassan"
    assert row_301["RecipientAddress(*)"] == "House 12, Road 3, Block B"
    assert row_301["RecipientCity(*)"] == "Dhaka"
    assert row_301["ItemDesc"] == "Oxford Shirt x2 - OX-001;"

    row_302 = pathao_df[pathao_df["MerchantOrderId"] == "302"].iloc[0]
    assert row_302["RecipientName(*)"] == ""
    assert row_302["RecipientAddress(*)"] == ""
    assert row_302["ItemDesc"] == "Polo Shirt x1;"  # junk '0' SKU omitted


def test_generate_pathao_bulk_item_desc_merge_and_count_tag():
    """Duplicate line items merge into one entry; >2 distinct items get '(n items)'."""
    df = pd.DataFrame(
        [
            # 2 lines, same item+SKU -> merged into one entry, no tag
            {
                "Order Number": 601,
                "Item Name": "Oxford Shirt",
                "SKU": "OX-001",
                "Quantity": 2,
                "Full Name (Shipping)": "Test Customer",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "Road 1, Dhaka",
                "City (Shipping)": "Dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 601,
                "Item Name": "Oxford Shirt",
                "SKU": "OX-001",
                "Quantity": 1,
                "Full Name (Shipping)": "Test Customer",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "Road 1, Dhaka",
                "City (Shipping)": "Dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            # 3 distinct items -> '(3 items)' tag
            {
                "Order Number": 602,
                "Item Name": "Polo Shirt",
                "SKU": "PL-002",
                "Quantity": 1,
                "Full Name (Shipping)": "Test Customer",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "Road 1, Dhaka",
                "City (Shipping)": "Dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 602,
                "Item Name": "Polo Shirt",
                "SKU": "PL-002",
                "Quantity": 2,
                "Full Name (Shipping)": "Test Customer",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "Road 1, Dhaka",
                "City (Shipping)": "Dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 602,
                "Item Name": "Denim Jeans",
                "SKU": "DJ-003",
                "Quantity": 1,
                "Full Name (Shipping)": "Test Customer",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "Road 1, Dhaka",
                "City (Shipping)": "Dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 602,
                "Item Name": "Panjabi",
                "SKU": "PJ-004",
                "Quantity": 1,
                "Full Name (Shipping)": "Test Customer",
                "Phone (Shipping)": "01712345678",
                "Address 1&2 (Shipping)": "Road 1, Dhaka",
                "City (Shipping)": "Dhaka",
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
        ]
    )

    pathao_df = generate_pathao_bulk_consignments(df)
    assert len(pathao_df) == 2

    row_601 = pathao_df[pathao_df["MerchantOrderId"] == "601"].iloc[0]
    assert row_601["ItemDesc"] == "Oxford Shirt x3 - OX-001;"  # merged, no tag
    assert row_601["ItemQuantity"] == 3

    row_602 = pathao_df[pathao_df["MerchantOrderId"] == "602"].iloc[0]
    assert (
        row_602["ItemDesc"]
        == "Polo Shirt x3 - PL-002; Denim Jeans x1 - DJ-003; Panjabi x1 - PJ-004; (3 items)"
    )
    assert row_602["ItemQuantity"] == 5


def test_generate_pathao_bulk_sku_column_fallback_detection():
    """Without explicit sku_col, a known SKU-named column is still picked up."""
    df = pd.DataFrame(
        [
            {
                "Order Number": 401,
                "Item Name": "Panjabi",
                "Item SKU": "PJ-777",
                "Quantity": 1,
                "SIP": '[{"outlet_slug":"warehouse"}]',
                "Name": "test customer",
                "Phone": "01712345678",
                "Address": "uttara sector 4",
                "City": "Dhaka",
            }
        ]
    )

    pathao_df = generate_pathao_bulk_consignments(df, sku_col=None)
    assert len(pathao_df) == 1
    row = pathao_df.iloc[0]
    assert row["RecipientName(*)"] == "Test Customer"
    assert row["RecipientAddress(*)"] == "Uttara Sector 4"
    assert row["ItemDesc"] == "Panjabi x1 - PJ-777;"


def test_convert_sip_to_smart_inventory_basic():
    """Line items aggregate per Product/Size/SKU/Outlet with sizes parsed from names."""
    df = pd.DataFrame(
        [
            {
                "Order Number": 501,
                "Item Name": "Oxford Shirt - L",
                "SKU": "OX-001",
                "Quantity": 2,
                "Item Cost": 1500,
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 502,
                "Item Name": "Oxford Shirt - L",
                "SKU": "OX-001",
                "Quantity": 1,
                "Item Cost": 1500,
                "SIP": '[{"outlet_slug":"warehouse"}]',
            },
            {
                "Order Number": 503,
                "Item Name": "Panjabi - XL",
                "SKU": "PJ-777",
                "Quantity": 1,
                "Item Cost": 2200,
                "SIP": '[{"outlet_slug":"cumilla"}]',
            },
        ]
    )

    result = convert_sip_to_smart_inventory(df)

    assert list(result.columns) == [
        "Product",
        "Size",
        "SKU",
        "Outlet",
        "Stock Qty",
        "Price",
        "Last Updated",
    ]

    # Aggregation: same product/size/sku/outlet merges
    wh = result[
        (result["Product"] == "Oxford Shirt - L") & (result["Outlet"] == "Warehouse")
    ]
    assert len(wh) == 1
    assert wh.iloc[0]["Stock Qty"] == 3  # 2 + 1
    assert wh.iloc[0]["Size"] == "L"
    assert wh.iloc[0]["SKU"] == "OX-001"
    assert wh.iloc[0]["Price"] == 1500

    cu = result[result["Outlet"] == "Cumilla"]
    assert len(cu) == 1
    assert cu.iloc[0]["Stock Qty"] == 1
    assert cu.iloc[0]["Size"] == "XL"


def test_convert_sip_to_smart_inventory_size_column_wins():
    """An explicit size column overrides the name-parsed size."""
    df = pd.DataFrame(
        [
            {
                "Order Number": 601,
                "Item Name": "Polo Shirt",
                "Size": "2XL",
                "SKU": "PL-9",
                "Quantity": 1,
                "SIP": '[{"outlet_slug":"sylhet"}]',
            }
        ]
    )

    result = convert_sip_to_smart_inventory(df, size_col="Size")
    assert result.iloc[0]["Size"] == "2XL"


def test_convert_sip_to_smart_inventory_no_sku_and_junk():
    """Missing SKU column reports '-' and junk SKU values are dropped."""
    df = pd.DataFrame(
        [
            {
                "Order Number": 701,
                "Item Name": "Jeans - 38",
                "Quantity": 1,
                "SIP": '[{"outlet_slug":"wari"}]',
            },
            {
                "Order Number": 702,
                "Item Name": "Belt",
                "SKU": "0",  # junk — must not appear
                "Quantity": 2,
                "SIP": '[{"outlet_slug":"wari"}]',
            },
        ]
    )

    result = convert_sip_to_smart_inventory(df)
    jeans = result[result["Product"] == "Jeans - 38"].iloc[0]
    assert jeans["SKU"] == "—"

    belt = result[result["Product"] == "Belt"].iloc[0]
    assert belt["SKU"] == "—"
    assert belt["Stock Qty"] == 2


def test_convert_sip_to_smart_inventory_empty_and_missing_cols():
    """Empty input and missing item column both yield the empty standard frame."""
    expected_cols = [
        "Product",
        "Size",
        "SKU",
        "Outlet",
        "Stock Qty",
        "Price",
        "Last Updated",
    ]

    empty = convert_sip_to_smart_inventory(pd.DataFrame())
    assert list(empty.columns) == expected_cols
    assert len(empty) == 0

    missing = convert_sip_to_smart_inventory(pd.DataFrame({"Other": [1, 2]}))
    assert list(missing.columns) == expected_cols
    assert len(missing) == 0
