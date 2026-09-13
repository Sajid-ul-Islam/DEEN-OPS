"""
Date-wise completed order analytics with source filtering (Online/Outlet).
"""

from __future__ import annotations

import pandas as pd
from typing import Optional

from src.config.constants import SHIPPED_STATUSES


def detect_source_column(df: pd.DataFrame) -> Optional[str]:
    """
    Detect which column indicates order source (online vs outlet).
    Checks for common meta keys and column patterns.
    """
    # Direct column matches
    source_candidates = [
        "Order Source",
        "Source",
        "sales_channel",
        "Sales Channel",
        "order_source",
        "OrderSource",
        "fulfillment_source",
        "Fulfillment Source",
    ]
    for col in source_candidates:
        if col in df.columns:
            return col

    # Check for meta_data columns that might contain source
    meta_candidates = [
        "_order_source",
        "_sales_channel",
        "_fulfillment_source",
        "_source",
        "source",
    ]
    for col in meta_candidates:
        if col in df.columns:
            return col

    return None


OUTLET_PAYMENT_METHODS = frozenset(
    {
        "cash",
        "ucb",
        "city bank",
        "ebl",
        "brac",
        "split: bkash + cash",
        "pos",
        "card swipe",
        "counter cash",
        "store cash",
        "retail cash",
    }
)

ONLINE_PAYMENT_KEYWORDS = (
    "cash on delivery",
    "pay online",
    "checkout",
    "ecom",
    "bkash",
    "nagad",
    "rocket",
    "sslcommerz",
    "shurjopay",
    "amaropay",
)


def classify_order_source(
    row: pd.Series,
    source_col: Optional[str] = None,
) -> str:
    """
    Classify an order as 'Online' (website/ecom checkout) or 'Outlet' (physical store/POS).

    Classification priority:
    1. Explicit source column ('Order Source', 'Source', 'sales_channel', 'Created via', etc.)
    2. Order ID / Order Number suffix (e.g. ' c' = Cumilla, ' w' = Wari, ' s' = Sylhet)
    3. Dispatch Suggestion / Warehouse Outlet (e.g. 'Cumilla', 'Wari', 'Sylhet' -> Outlet)
    4. Payment Method Title (e.g. 'Cash', 'UCB', 'City Bank' -> Outlet POS; 'Cash on delivery', 'Pay Online' -> Online checkout)
    """
    # 1. Check explicit source column if passed or present in row
    candidates = [source_col] if source_col else []
    candidates.extend(
        [
            "Created via",
            "created_via",
            "Order Source",
            "Source",
            "sales_channel",
            "Sales Channel",
            "order_source",
            "OrderSource",
            "fulfillment_source",
        ]
    )

    for col in candidates:
        if col and col in row.index and pd.notna(row[col]):
            val = str(row[col]).strip().lower()
            if not val or val in ("nan", "none", "null"):
                continue
            if val in (
                "checkout",
                "store-api",
                "online",
                "web",
                "website",
                "ecom",
                "e-commerce",
                "digital",
            ):
                return "Online"
            if val in (
                "outlet",
                "store",
                "pos",
                "wepos",
                "physical",
                "retail",
                "offline",
                "admin",
                "manual",
            ):
                return "Outlet"
            if "checkout" in val or "online" in val or "web" in val or "ecom" in val:
                return "Online"
            if "pos" in val or "outlet" in val or "store" in val:
                return "Outlet"

    # 2. Check Order ID / Order Number suffix conventions
    for col_key in ("Order ID", "Order Number", "order_id", "order_number"):
        if col_key in row.index and pd.notna(row[col_key]):
            o_val = str(row[col_key]).strip().lower()
            if o_val.endswith((" c", " w", " s", "-c", "-w", "-s", "_c", "_w", "_s")):
                return "Outlet"

    # 3. Check Dispatch Suggestion / Warehouse Outlet
    for col_key in ("Dispatch Suggestion", "Warehouse Outlet", "WarehouseOutlet"):
        if col_key in row.index and pd.notna(row[col_key]):
            dispatch = str(row[col_key]).strip().lower()
            if dispatch and dispatch not in (
                "nan",
                "",
                "none",
                "ecom-mirpur",
                "ecom mirpur",
            ):
                if any(
                    outlet in dispatch
                    for outlet in ("wari", "cumilla", "sylhet", "outlet")
                ):
                    return "Outlet"

    # 4. Check Payment Method Title (critical distinction for POS vs Online checkout)
    for col_key in (
        "Payment Method Title",
        "payment_method_title",
        "Payment Method",
        "payment_method",
    ):
        if col_key in row.index and pd.notna(row[col_key]):
            pm = str(row[col_key]).strip().lower()
            if not pm or pm in ("nan", "none", "null"):
                continue
            # Known outlet / POS payment methods
            if pm in OUTLET_PAYMENT_METHODS or any(
                term in pm for term in ("pos", "counter", "outlet", "store cash")
            ):
                return "Outlet"
            # Known online checkout payment methods
            if any(term in pm for term in ONLINE_PAYMENT_KEYWORDS):
                return "Online"

    return "Online"


def filter_online_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to only include online website checkout orders (exclude physical outlet/POS orders)."""
    if df is None or df.empty:
        return df
    source_col = detect_source_column(df)
    sources = df.apply(lambda r: classify_order_source(r, source_col), axis=1)
    return df[sources == "Online"].copy()


def filter_completed_orders_by_date(
    df: pd.DataFrame,
    target_date: pd.Timestamp,
    source_filter: str = "Both",  # "Both", "Online", "Outlet"
) -> pd.DataFrame:
    """
    Filter DataFrame to completed/shipped orders on a specific date,
    optionally filtered by source (Online/Outlet).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return pd.DataFrame()

    # Filter to shipped/completed statuses
    status_lower = df[status_col].astype(str).str.lower().str.strip()
    shipped_mask = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])
    shipped_df = df[shipped_mask].copy()

    if shipped_df.empty:
        return shipped_df

    # Resolve date column
    mod_col = None
    if "mod_dt_parsed" in shipped_df.columns:
        mod_col = "mod_dt_parsed"
    elif "Order Date Modified" in shipped_df.columns:
        mod_col = "Order Date Modified"

    date_col = None
    if "dt_parsed" in shipped_df.columns:
        date_col = "dt_parsed"
    elif "Order Date" in shipped_df.columns:
        date_col = "Order Date"

    # Parse dates
    if mod_col:
        dt_mod = pd.to_datetime(shipped_df[mod_col], errors="coerce")
        if dt_mod.dt.tz is not None:
            dt_mod = dt_mod.dt.tz_localize(None)
    else:
        dt_mod = pd.Series(pd.NaT, index=shipped_df.index)

    if date_col:
        dt_create = pd.to_datetime(shipped_df[date_col], errors="coerce")
        if dt_create.dt.tz is not None:
            dt_create = dt_create.dt.tz_localize(None)
    else:
        dt_create = pd.Series(pd.NaT, index=shipped_df.index)

    dt_effective = dt_mod.fillna(dt_create)

    # Filter by target date
    target_date_only = (
        target_date.date() if hasattr(target_date, "date") else target_date
    )
    date_mask = dt_effective.dt.date == target_date_only
    result = shipped_df[date_mask].copy()

    if result.empty:
        return result

    # Apply source filter
    source_col = detect_source_column(result)
    if source_filter != "Both":
        result["_order_source"] = result.apply(
            lambda row: classify_order_source(row, source_col), axis=1
        )
        result = result[result["_order_source"] == source_filter]

    return result


def filter_shipped_order_items(
    df: pd.DataFrame,
    start_date,
    end_date=None,
    source_filter: str = "Both",
) -> pd.DataFrame:
    """
    Filter DataFrame to shipped/completed line items within a date range (inclusive),
    preserving product-level granularity (one row per item/SKU).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return pd.DataFrame()

    # Filter to shipped/completed statuses
    status_lower = df[status_col].astype(str).str.lower().str.strip()
    shipped_mask = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])
    shipped_df = df[shipped_mask].copy()

    if shipped_df.empty:
        return shipped_df

    # Resolve date column (completion/modification timestamp prioritized)
    mod_col = None
    if "mod_dt_parsed" in shipped_df.columns:
        mod_col = "mod_dt_parsed"
    elif "Order Date Modified" in shipped_df.columns:
        mod_col = "Order Date Modified"

    date_col = None
    if "dt_parsed" in shipped_df.columns:
        date_col = "dt_parsed"
    elif "Order Date" in shipped_df.columns:
        date_col = "Order Date"

    if mod_col:
        dt_mod = pd.to_datetime(shipped_df[mod_col], errors="coerce")
        if dt_mod.dt.tz is not None:
            dt_mod = dt_mod.dt.tz_localize(None)
    else:
        dt_mod = pd.Series(pd.NaT, index=shipped_df.index)

    if date_col:
        dt_create = pd.to_datetime(shipped_df[date_col], errors="coerce")
        if dt_create.dt.tz is not None:
            dt_create = dt_create.dt.tz_localize(None)
    else:
        dt_create = pd.Series(pd.NaT, index=shipped_df.index)

    dt_effective = dt_mod.fillna(dt_create)

    # Normalize start_date and end_date
    start_d = start_date.date() if hasattr(start_date, "date") else start_date
    if end_date is None:
        end_d = start_d
    else:
        end_d = end_date.date() if hasattr(end_date, "date") else end_date

    eff_dates = dt_effective.dt.date
    date_mask = (eff_dates >= start_d) & (eff_dates <= end_d)
    result = shipped_df[date_mask].copy()

    if result.empty:
        return result

    # Apply source filter if specified
    source_col = detect_source_column(result)
    if source_filter != "Both":
        result["_order_source"] = result.apply(
            lambda row: classify_order_source(row, source_col), axis=1
        )
        result = result[result["_order_source"] == source_filter]

    return result


def compute_completed_kpis(df: pd.DataFrame) -> dict:
    """
    Compute KPI metrics for completed orders DataFrame.
    Returns dict with: orders, items, gross_revenue, cashback, net_revenue, basket_size
    """
    if df is None or df.empty:
        return {
            "orders": 0,
            "items": 0,
            "gross_revenue": 0.0,
            "cashback": 0.0,
            "net_revenue": 0.0,
            "basket_size": 0.0,
        }

    # Unique orders
    order_col = "Order ID" if "Order ID" in df.columns else "Order Number"
    if order_col in df.columns:
        orders = df[order_col].nunique()
    else:
        orders = len(df)

    # Items
    qty_col = "Quantity" if "Quantity" in df.columns else None
    items = int(df[qty_col].sum()) if qty_col else orders

    # Revenue
    if "Gross Amount" in df.columns:
        gross_revenue = float(df["Gross Amount"].sum())
    elif "Item Cost" in df.columns and qty_col:
        gross_revenue = float((df[qty_col] * df["Item Cost"]).sum())
    elif "Order Total Amount" in df.columns:
        gross_revenue = float(df["Order Total Amount"].sum())
    else:
        gross_revenue = 0.0

    # Cashback
    cashback = (
        float(df["Cashback Discount"].sum())
        if "Cashback Discount" in df.columns
        else 0.0
    )

    # Net revenue
    net_revenue = max(0.0, gross_revenue - cashback)

    # Basket size
    basket_size = net_revenue / orders if orders > 0 else 0.0

    return {
        "orders": orders,
        "items": items,
        "gross_revenue": gross_revenue,
        "cashback": cashback,
        "net_revenue": net_revenue,
        "basket_size": basket_size,
    }
