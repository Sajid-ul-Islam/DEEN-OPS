"""Unit tests for return reconciliation processor (P4)."""

import pandas as pd

from src.processing.return_processor import (
    classify_return_row,
    compute_reconciliation_fields,
    compute_return_kpis,
    is_prepaid_payment,
)


def test_is_prepaid_payment():
    """Verify prepaid payment method identification."""
    assert is_prepaid_payment("bKash Online Payment") is True
    assert is_prepaid_payment("Credit/Debit Card via SSLCommerz") is True
    assert is_prepaid_payment("Nagad Gateway") is True
    assert is_prepaid_payment("Cash on delivery (COD)") is False
    assert is_prepaid_payment("COD") is False
    assert is_prepaid_payment(None) is False
    assert is_prepaid_payment("") is False


def test_classify_return_row_verified():
    """Cancelled or refunded in WC is classified as verified."""
    rec, pmt, act = classify_return_row("refunded", "Returned", "COD")
    assert "Verified" in rec
    assert "Cash on Delivery" in pmt
    assert act == "No Action Required"


def test_classify_return_row_courier_discrepancy():
    """Delivered in Pathao but flagged return is classified as discrepancy."""
    rec, pmt, act = classify_return_row("processing", "Delivered", "bKash")
    assert "Courier Discrepancy" in rec
    assert "Prepaid" in pmt
    assert "Audit physically" in act


def test_classify_return_row_status_mismatch():
    """Still active in WC but returned in courier requires WC status update."""
    rec, pmt, act = classify_return_row("completed", "Return in Progress", "COD")
    assert "WC Status Mismatch" in rec
    assert "Update WC Order Status" in act


def test_compute_reconciliation_fields_and_kpis():
    """Test batch classification on a DataFrame and KPI calculation."""
    df = pd.DataFrame(
        [
            {
                "Order ID": 101,
                "Order Status": "refunded",
                "Live Pathao Status": "Returned",
                "Payment Method Title": "COD",
            },
            {
                "Order ID": 102,
                "Order Status": "completed",
                "Live Pathao Status": "Returned",
                "Payment Method Title": "bKash",
            },
            {
                "Order ID": 103,
                "Order Status": "processing",
                "Live Pathao Status": "Delivered",
                "Payment Method Title": "Card",
            },
        ]
    )

    result = compute_reconciliation_fields(df)
    assert "Reconciliation Status" in result.columns
    assert "Payment Type" in result.columns
    assert "Recommended Action" in result.columns

    kpis = compute_return_kpis(result)
    assert kpis["total_returns"] == 3
    assert kpis["verified_count"] == 1
    assert kpis["mismatch_count"] == 1
    assert kpis["courier_discrepancy_count"] == 1
    assert kpis["prepaid_risk_count"] == 2
