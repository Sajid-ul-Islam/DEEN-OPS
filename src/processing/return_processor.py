"""Return parcel analytics and reconciliation processor for DEEN-OPS.

Provides pure, testable data transformation functions for 3-way reconciliation:
  WooCommerce Order Status <--> Pathao Courier Status <--> Physical Return Logs
"""

from __future__ import annotations

from typing import Any
import pandas as pd


PREPAID_PAYMENT_KEYWORDS = frozenset(
    {
        "bkash",
        "nagad",
        "rocket",
        "card",
        "online",
        "ssl",
        "amarpay",
        "bank",
        "visa",
        "mastercard",
    }
)

COD_PAYMENT_KEYWORDS = frozenset(
    {
        "cod",
        "cash on delivery",
        "cash",
    }
)


def is_prepaid_payment(payment_method: str | None) -> bool:
    """Determine if a payment method is prepaid (e.g. bKash, Card, SSL) requiring refund auditing."""
    if not payment_method or pd.isna(payment_method):
        return False
    pmt = str(payment_method).lower().strip()
    if not pmt:
        return False
    if any(kw in pmt for kw in PREPAID_PAYMENT_KEYWORDS):
        return True
    return not any(kw in pmt for kw in COD_PAYMENT_KEYWORDS)


def classify_return_row(
    wc_status: str,
    pathao_status: str,
    payment_method: str,
) -> tuple[str, str, str]:
    """Classify a single return order row into:

    (reconciliation_status, payment_type, recommended_action).
    """
    wc_st = str(wc_status or "").lower().strip()
    p_st = str(pathao_status or "").lower().strip()
    pmt = str(payment_method or "").lower().strip()

    # 1. Reconciliation Status
    if wc_st in {
        "refunded",
        "cancelled",
        "failed",
        "returned",
        "wc-refunded",
        "wc-cancelled",
        "wc-returned",
    }:
        rec_status = "✅ Verified (WC Refunded/Cancelled)"
    elif "delivered" in p_st:
        rec_status = "🚨 Courier Discrepancy (Pathao Delivered)"
    elif wc_st in {
        "processing",
        "shipped",
        "completed",
        "confirmed",
        "wc-shipped",
        "wc-completed",
    }:
        rec_status = "⚠️ WC Status Mismatch (Action Needed)"
    else:
        rec_status = "🟡 Pending Verification"

    # 2. Payment Refund Risk
    is_prepaid = is_prepaid_payment(pmt)
    pmt_flag = (
        "💳 Prepaid (Refund Verification Required)"
        if is_prepaid
        else "💵 Cash on Delivery (COD)"
    )

    # 3. Action Recommendation
    if rec_status == "⚠️ WC Status Mismatch (Action Needed)":
        action = "Update WC Order Status to Cancelled / Refunded"
    elif rec_status == "🚨 Courier Discrepancy (Pathao Delivered)":
        action = "Audit physically before issuing refund"
    elif is_prepaid and rec_status != "✅ Verified (WC Refunded/Cancelled)":
        action = "Verify customer bKash/Bank refund transfer"
    else:
        action = "No Action Required"

    return rec_status, pmt_flag, action


def compute_reconciliation_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Classify returned orders against WooCommerce & Pathao live statuses."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    df = df.copy()

    wc_col = "Order Status" if "Order Status" in df.columns else "Status"
    pathao_col = (
        "Live Pathao Status" if "Live Pathao Status" in df.columns else "Pathao Status"
    )
    pmt_col = (
        "Payment Method Title"
        if "Payment Method Title" in df.columns
        else "Payment Method"
    )

    records = []
    for _, row in df.iterrows():
        wc_val = row.get(wc_col, "")
        pathao_val = row.get(pathao_col, "")
        pmt_val = row.get(pmt_col, "")
        rec_st, pmt_type, action = classify_return_row(wc_val, pathao_val, pmt_val)
        records.append((rec_st, pmt_type, action))

    if records:
        classified = pd.DataFrame(
            records,
            index=df.index,
            columns=["Reconciliation Status", "Payment Type", "Recommended Action"],
        )
        df["Reconciliation Status"] = classified["Reconciliation Status"]
        df["Payment Type"] = classified["Payment Type"]
        df["Recommended Action"] = classified["Recommended Action"]

    return df


def compute_return_kpis(df: pd.DataFrame) -> dict[str, Any]:
    """Compute high-level summary KPIs for return reconciliation dashboard."""
    if df is None or df.empty or "Reconciliation Status" not in df.columns:
        return {
            "total_returns": 0,
            "verified_count": 0,
            "mismatch_count": 0,
            "courier_discrepancy_count": 0,
            "prepaid_risk_count": 0,
        }

    total = len(df)
    statuses = df["Reconciliation Status"].astype(str)
    payments = (
        df["Payment Type"].astype(str)
        if "Payment Type" in df.columns
        else pd.Series("", index=df.index)
    )

    verified = statuses.str.contains("Verified", case=False).sum()
    mismatch = statuses.str.contains("Mismatch", case=False).sum()
    discrepancy = statuses.str.contains("Courier Discrepancy", case=False).sum()
    prepaid = payments.str.contains("Prepaid", case=False).sum()

    return {
        "total_returns": int(total),
        "verified_count": int(verified),
        "mismatch_count": int(mismatch),
        "courier_discrepancy_count": int(discrepancy),
        "prepaid_risk_count": int(prepaid),
    }
