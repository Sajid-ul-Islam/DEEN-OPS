"""Unit tests verifying that the Pathao Processor follows the Outlet-Wise Extractor / Pathao Bulk rules."""

import json
import pandas as pd
import pytest

from src.processing.order_processor import (
    clean_dataframe,
    process_orders_dataframe,
    _get_dispatch_group,
    _get_dispatch_warehouse,
)
from src.processing.sip_outlet_processor import get_fulfillment_group


def test_get_fulfillment_group_ecom_mirpur_support():
    """Verify that ecom-mirpur is recognized as primary Warehouse fulfillment."""
    assert get_fulfillment_group("warehouse") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("mirpur") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("mirpur-12") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("ecom-mirpur") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("ecom mirpur") == ("Warehouse", "", "Warehouse")
    assert get_fulfillment_group("cumilla") == ("Cumilla", " c", "Cumilla Outlet")
    assert get_fulfillment_group("sylhet") == ("Sylhet", " s", "Sylhet Outlet")
    assert get_fulfillment_group("wari") == ("Wari", " w", "Wari Outlet")


def test_sip_json_multi_outlet_split_and_cod_allocation():
    """Order with SIP JSON routing split across Warehouse and Cumilla:
    - Primary dispatch (Warehouse) has no suffix and includes delivery charge.
    - Subsequent split dispatch (Cumilla) has ' c' suffix and collects only item cost.
    - Both parcels have Split Part instruction.
    """
    raw_orders = [
        {
            "Order ID": "9001",
            "Order Number": "9001",
            "Phone (Billing)": "01711000111",
            "Full Name (Shipping)": "Md.Kefayoth  Sakib  SAKIB",
            "Address 1&2 (Shipping)": "House 10, Road 4; Dhanmondi",
            "City (Shipping)": "Dhaka",
            "State Code (Shipping)": "Dhaka",
            "Item Name": "Panjabi White",
            "Quantity": 1,
            "Item Cost": 1500,
            "Order Total Amount": 2550,  # 1500 + 1000 items + 50 delivery
            "Payment Method Title": "Cash on delivery",
            "SIP": json.dumps([{"outlet_slug": "warehouse"}, {"outlet_slug": "cumilla"}]),
        },
        {
            "Order ID": "9001",
            "Order Number": "9001",
            "Phone (Billing)": "01711000111",
            "Full Name (Shipping)": "Md.Kefayoth  Sakib  SAKIB",
            "Address 1&2 (Shipping)": "House 10, Road 4; Dhanmondi",
            "City (Shipping)": "Dhaka",
            "State Code (Shipping)": "Dhaka",
            "Item Name": "Pajama Black",
            "Quantity": 1,
            "Item Cost": 1000,
            "Order Total Amount": 2550,
            "Payment Method Title": "Cash on delivery",
            "SIP": json.dumps([{"outlet_slug": "warehouse"}, {"outlet_slug": "cumilla"}]),
        },
    ]

    df = pd.DataFrame(raw_orders)
    result = process_orders_dataframe(df)

    assert len(result) == 2, "Expected 2 split consignments for Warehouse and Cumilla"

    # Primary consignment (Warehouse / Ecom Mirpur)
    p0 = result.iloc[0]
    assert p0["MerchantOrderId"] == "9001", "Primary dispatch should have base Order ID"
    assert p0["WarehouseOutlet"] == "Ecom Mirpur"
    assert p0["AmountToCollect(*)"] == 1550, "Primary parcel collects item cost (1500) + delivery (50)"
    assert p0["RecipientName(*)"] == "Md. Kefayoth Sakib", "Name should be normalized and deduplicated"
    assert "Split Part 1/2 [Warehouse]" in p0["SpecialInstruction"]

    # Secondary consignment (Cumilla)
    p1 = result.iloc[1]
    assert p1["MerchantOrderId"] == "9001 c", "Cumilla dispatch should have ' c' suffix"
    assert p1["WarehouseOutlet"] == "Cumilla Outlet"
    assert p1["AmountToCollect(*)"] == 1000, "Secondary parcel collects only its item cost"
    assert "Split Part 2/2 [Cumilla]" in p1["SpecialInstruction"]

    # Total collected across both consignments matches total
    assert p0["AmountToCollect(*)"] + p1["AmountToCollect(*)"] == 2550


def test_item_outlet_column_split_and_suffixes():
    """Order with direct 'Item Outlet' column across Wari and Sylhet:
    - Suffixes ' w' and ' s'.
    - Delivery fee allocated to parcel 0.
    """
    raw_orders = [
        {
            "Order Number": "9002",
            "Phone (Billing)": "01822000222",
            "Full Name (Shipping)": "Karim Ullah",
            "Address 1&2 (Shipping)": "GEC Circle, Chittagong",
            "City (Shipping)": "Chittagong",
            "State Code (Shipping)": "Chittagong",
            "Item Name": "Casual Shirt",
            "Quantity": 1,
            "Item Cost": 800,
            "Order Total Amount": 1690,  # 800 + 800 items + 90 outside Dhaka delivery
            "Payment Method Title": "Cash on delivery",
            "Item Outlet": "Wari",
        },
        {
            "Order Number": "9002",
            "Phone (Billing)": "01822000222",
            "Full Name (Shipping)": "Karim Ullah",
            "Address 1&2 (Shipping)": "GEC Circle, Chittagong",
            "City (Shipping)": "Chittagong",
            "State Code (Shipping)": "Chittagong",
            "Item Name": "Formal Pant",
            "Quantity": 1,
            "Item Cost": 800,
            "Order Total Amount": 1690,
            "Payment Method Title": "Cash on delivery",
            "Item Outlet": "Sylhet",
        },
    ]

    df = pd.DataFrame(raw_orders)
    result = process_orders_dataframe(df)

    assert len(result) == 2
    order_ids = set(result["MerchantOrderId"])
    assert "9002 w" in order_ids
    assert "9002 s" in order_ids
    assert sum(result["AmountToCollect(*)"]) == 1690


def test_prepaid_orders_collect_zero_across_splits():
    """Prepaid split orders collect 0 on all consignments."""
    raw_orders = [
        {
            "Order Number": "9003",
            "Phone (Billing)": "01933000333",
            "Full Name (Shipping)": "Sumi Akter",
            "Address 1&2 (Shipping)": "Banani Road 11, Dhaka",
            "City (Shipping)": "Dhaka",
            "State Code (Shipping)": "Dhaka",
            "Item Name": "Silk Scarf",
            "Quantity": 1,
            "Item Cost": 1200,
            "Order Total Amount": 1250,
            "Payment Method Title": "bKash Online Payment",
            "Item Outlet": "Mirpur",
        },
        {
            "Order Number": "9003",
            "Phone (Billing)": "01933000333",
            "Full Name (Shipping)": "Sumi Akter",
            "Address 1&2 (Shipping)": "Banani Road 11, Dhaka",
            "City (Shipping)": "Dhaka",
            "State Code (Shipping)": "Dhaka",
            "Item Name": "Earrings",
            "Quantity": 1,
            "Item Cost": 500,
            "Order Total Amount": 1250,
            "Payment Method Title": "bKash Online Payment",
            "Item Outlet": "Cumilla",
        },
    ]

    df = pd.DataFrame(raw_orders)
    result = process_orders_dataframe(df)

    assert len(result) == 2
    assert all(row["AmountToCollect(*)"] == 0 for _, row in result.iterrows())
    assert any("Paid by Bkash" in str(row["SpecialInstruction"]) for _, row in result.iterrows())


def test_recipient_address_normalization():
    """Verify address normalizer handles delimiters, Bangla danda, and spacing."""
    raw_orders = [
        {
            "Order Number": "9004",
            "Phone (Billing)": "01744000444",
            "Full Name (Shipping)": "Zahid Hassan",
            "Address 1&2 (Shipping)": "Flat 4A | House 12 ; Road 3 । Sector 4",
            "City (Shipping)": "Uttara",
            "State Code (Shipping)": "Dhaka",
            "Item Name": "T-Shirt",
            "Quantity": 1,
            "Item Cost": 400,
            "Order Total Amount": 450,
            "Payment Method Title": "Cash on delivery",
            "Item Outlet": "Warehouse",
        }
    ]

    df = pd.DataFrame(raw_orders)
    result = process_orders_dataframe(df)

    addr = result.iloc[0]["RecipientAddress(*)"]
    assert "|" not in addr
    assert ";" not in addr
    assert "।" not in addr
    assert "Flat 4A, House 12, Road 3, Sector 4" in addr
