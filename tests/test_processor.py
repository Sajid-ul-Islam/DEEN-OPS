import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import pytest

fake_streamlit = types.ModuleType("streamlit")


def _identity_decorator(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


fake_streamlit.cache_data = _identity_decorator
fake_streamlit.cache_resource = _identity_decorator
fake_streamlit.session_state = {}
fake_streamlit.secrets = {}
sys.modules["streamlit"] = fake_streamlit

from src.processing import order_processor as processor


def test_process_orders_dataframe_basic():
    df = pd.DataFrame(
        {
            "Order Number": ["O1", "O2"],
            "Recipient Name": ["John Doe", "Jane Smith"],
            "Address": ["House 10, Mirpur 12, Dhaka", "Sector 4, Uttara, Dhaka 1230"],
            "Phone (Billing)": ["01711223344", "+88 01811-223344"],
            "Quantity": [1, 2],
        }
    )

    res = processor.process_orders_dataframe(df)

    # Check cleaning
    assert "RecipientZone(*)" in res.columns

    # After processing, it creates a clean Phone column usually. Or preserves it if it maps it.
    assert len(res) >= 1


def test_empty_dataframe():
    df = pd.DataFrame(columns=["Recipient Name", "Address", "Phone (Billing)"])
    res = processor.process_orders_dataframe(df)
    assert len(res) == 0


def test_missing_address_column():
    df = pd.DataFrame(
        {
            "Order Number": ["O1"],
            "Recipient Name": ["John Doe"],
            "Phone (Billing)": ["01700000000"],
            "Quantity": [1],
        }
    )
    res = processor.process_orders_dataframe(df)
    assert len(res) == 1
    assert "RecipientName(*)" in res.columns


def test_recipient_address_includes_normalized_zone_and_district():
    df = pd.DataFrame(
        {
            "Order Number": ["O1"],
            "Recipient Name": ["John Doe"],
            "Shipping Address 1": ["House 10, Road 4"],
            "Shipping City": ["Mirpur 12"],
            "State Name (Billing)": ["BD-13"],
            "Phone (Billing)": ["01711223344"],
            "Item Name": ["Shirt"],
            "SKU": ["SKU-1"],
            "Quantity": [1],
            "Order Total Amount": [500],
            "Payment Method Title": ["Cash on delivery"],
        }
    )

    res = processor.process_orders_dataframe(df)

    assert res.loc[0, "RecipientAddress(*)"] == "House 10, Road 4, Mirpur 12, Dhaka"
    assert res.loc[0, "RecipientCity(*)"] == "Dhaka"
    assert res.loc[0, "RecipientZone(*)"] == "Mirpur 12"


def test_manual_item_input_is_normalized_sorted_and_aggregated():
    normalized_items, description = processor.normalize_manual_item_input(
        "Polo Shirt x1\n2x Oxford Shirt | SKU-2\nOxford Shirt | SKU-2"
    )

    assert normalized_items == [
        {"category": "FS Shirt", "label": "Oxford Shirt - SKU-2", "qty": 3},
        {"category": "Polo Shirt", "label": "Polo Shirt", "qty": 1},
    ]
    assert description == (
        "3 FS Shirt = Oxford Shirt - SKU-2 (3 pcs); "
        "1 Polo Shirt = Polo Shirt; (4 items)"
    )
