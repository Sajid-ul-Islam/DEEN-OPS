"""Order status filtering and slot boundary scoping rules."""

from __future__ import annotations

from datetime import timedelta
import sys

import pandas as pd

from src.config.constants import (
    ACTIVE_STATUSES,
    CANCELLED_STATUSES,
    HOLD_WAITING_STATUSES,
    SHIPPED_STATUSES,
    bd_today,
)
from src.processing.orders.date_utils import (
    get_previous_working_day,
    safe_coerce_datetime_naive,
)
from src.utils.streamlit_runtime import get_session_state


def _get_bd_today():
    """Resolve current BD calendar date, honoring monkeypatching on data_processing."""
    dp = sys.modules.get("src.processing.data_processing")
    if dp is not None and hasattr(dp, "bd_today"):
        return dp.bd_today()
    return bd_today()


def _detect_exchange_mask(df: pd.DataFrame) -> pd.Series:
    """Return a boolean Series marking exchange/return orders.

    An order is an exchange if its Order Status contains "exchange" OR its
    Fee Notes contains "exchange credit".
    """
    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    fee_notes_col = "Fee Notes" if "Fee Notes" in df.columns else None

    status_mask = pd.Series(False, index=df.index)
    if status_col:
        status_mask = (
            df[status_col].astype(str).str.lower().str.contains("exchange", na=False)
        )

    fee_mask = pd.Series(False, index=df.index)
    if fee_notes_col:
        fee_mask = (
            df[fee_notes_col]
            .astype(str)
            .str.lower()
            .str.contains("exchange credit", na=False)
        )

    return status_mask | fee_mask


def filter_shipped_by_slot(
    df: pd.DataFrame, nav_mode: str, is_comparison: bool = False
):
    """Filters a DataFrame to shipped orders for the relevant time window."""
    if df is None or df.empty:
        return df

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return df

    # ── Step 1: Identify shipped orders (strictly by shipped status) ──────────
    status_lower = df[status_col].astype(str).str.lower().str.strip()
    shipped_mask = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])
    shipped_df = df[shipped_mask]

    if shipped_df.empty:
        return shipped_df

    # ── Step 2: Resolve date columns ─────────────────────────────────────────
    def _safe_tz_naive(series):
        return safe_coerce_datetime_naive(series)

    def _safe_dt_naive(val):
        dt_v = pd.to_datetime(val)
        return dt_v.tz_localize(None) if getattr(dt_v, "tz", None) is not None else dt_v

    mod_col = None
    if "mod_dt_parsed" in shipped_df.columns:
        mod_col = "mod_dt_parsed"
    elif "Order Date Modified" in shipped_df.columns:
        mod_col = "Order Date Modified"

    date_col = (
        "dt_parsed"
        if "dt_parsed" in shipped_df.columns
        else "Order Date"
        if "Order Date" in shipped_df.columns
        else None
    )

    dt_mod = (
        _safe_tz_naive(shipped_df[mod_col])
        if mod_col
        else pd.Series(pd.NaT, index=shipped_df.index)
    )
    dt_create = (
        _safe_tz_naive(shipped_df[date_col])
        if date_col
        else pd.Series(pd.NaT, index=shipped_df.index)
    )

    # mod_dt is the authoritative "when was it shipped" signal.
    # Fall back to dt_create only when mod_dt is null.
    dt_effective = dt_mod.fillna(dt_create)

    today_bd = _get_bd_today()

    # ── Step 3: Custom date range (user-selected) ────────────────────────────
    custom_range = get_session_state().get("live_custom_range")
    if (
        not is_comparison
        and custom_range
        and isinstance(custom_range, (tuple, list))
        and len(custom_range) == 2
    ):
        start_d, end_d = custom_range[0], custom_range[1]
        if start_d != today_bd or end_d != today_bd:
            mask = (dt_effective.dt.date >= start_d) & (dt_effective.dt.date <= end_d)
            return shipped_df[mask]

    # ── Step 4: TODAY MODE — strict Bangladesh calendar-day match ────────────
    if nav_mode == "Today" and not is_comparison:
        today_bd = _get_bd_today()
        today_mask = dt_effective.dt.date == today_bd
        return shipped_df[today_mask].copy()

    if nav_mode == "Today" and is_comparison:
        previous_day = get_previous_working_day(_get_bd_today())
        return shipped_df[dt_effective.dt.date == previous_day].copy()

    # ── Step 5: PREV / COMPARISON MODE — use slot boundaries ────────────────
    slot_key = "wc_prev_slot" if nav_mode == "Prev" else None
    if is_comparison:
        slot_key = (
            "wc_prev_slot"
            if nav_mode == "Today"
            else "wc_curr_slot"
            if nav_mode == "Prev"
            else None
        )

    slot = get_session_state().get(slot_key) if slot_key else None

    if slot:
        slot_start, slot_end = _safe_dt_naive(slot[0]), _safe_dt_naive(slot[1])
        filtered = shipped_df[(dt_effective >= slot_start) & (dt_effective <= slot_end)]
        return filtered

    return shipped_df.iloc[0:0]


def filter_all_orders_to_slot(df: pd.DataFrame, nav_mode: str):
    """Scope the non-cancelled operational workload to the selected window."""
    shipped_statuses = {status.lower() for status in SHIPPED_STATUSES}

    if df is None or df.empty:
        return df

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return df

    status_lower = df[status_col].astype(str).str.lower().str.strip()
    df = df[~status_lower.isin(CANCELLED_STATUSES)].copy()
    if df.empty:
        return df

    # Check for custom date range selected by user
    custom_range = get_session_state().get("live_custom_range")
    today_bd = bd_today()

    if (
        custom_range
        and isinstance(custom_range, (tuple, list))
        and len(custom_range) == 2
    ):
        start_d, end_d = custom_range[0], custom_range[1]
        if start_d != today_bd or end_d != today_bd:
            mod_col = (
                "mod_dt_parsed"
                if "mod_dt_parsed" in df.columns
                else (
                    "Order Date Modified"
                    if "Order Date Modified" in df.columns
                    else None
                )
            )
            date_col = (
                "dt_parsed"
                if "dt_parsed" in df.columns
                else "Order Date"
                if "Order Date" in df.columns
                else None
            )

            status_lower = df[status_col].astype(str).str.lower().str.strip()
            is_shipped = status_lower.isin(shipped_statuses)

            dt_mod = (
                safe_coerce_datetime_naive(df[mod_col])
                if mod_col
                else pd.Series(pd.NaT, index=df.index)
            )
            dt_create = (
                safe_coerce_datetime_naive(df[date_col])
                if date_col
                else pd.Series(pd.NaT, index=df.index)
            )

            active_mask = ~is_shipped
            shipped_mask = is_shipped & (
                ((dt_mod.dt.date >= start_d) & (dt_mod.dt.date <= end_d))
                | (
                    dt_mod.isna()
                    & (dt_create.dt.date >= start_d)
                    & (dt_create.dt.date <= end_d)
                )
            )
            return df[active_mask | shipped_mask]

    # 2. Choose the slot boundary key for the current nav mode
    if nav_mode == "Today":
        slot_key = "wc_curr_slot"
    elif nav_mode == "Prev":
        slot_key = "wc_prev_slot"
    else:
        slot_key = None

    slot = get_session_state().get(slot_key) if slot_key else None

    if slot:
        slot_start = pd.to_datetime(slot[0])
        slot_end = pd.to_datetime(slot[1])

        mod_col = (
            "mod_dt_parsed"
            if "mod_dt_parsed" in df.columns
            else "Order Date Modified"
            if "Order Date Modified" in df.columns
            else None
        )
        date_col = (
            "dt_parsed"
            if "dt_parsed" in df.columns
            else "Order Date"
            if "Order Date" in df.columns
            else None
        )

        status_lower = df[status_col].astype(str).str.lower().str.strip()
        is_shipped = status_lower.isin(shipped_statuses)

        active_mask = ~is_shipped

        dt_mod = (
            safe_coerce_datetime_naive(df[mod_col])
            if mod_col
            else pd.Series(pd.NaT, index=df.index)
        )
        dt_create = (
            safe_coerce_datetime_naive(df[date_col])
            if date_col
            else pd.Series(pd.NaT, index=df.index)
        )
        dt_effective = dt_mod.fillna(dt_create)

        shipped_mask = is_shipped & (
            ((dt_effective >= slot_start) & (dt_effective <= slot_end))
            | (dt_create.notna() & (dt_create >= slot_start) & (dt_create <= slot_end))
        )

        combined = df[active_mask | shipped_mask]
        return combined

    # No slot boundaries — fall back to calendar day (BD UTC+6) for Today mode
    if nav_mode == "Today":
        today_bd = _get_bd_today()

        date_col = (
            "dt_parsed"
            if "dt_parsed" in df.columns
            else "Order Date"
            if "Order Date" in df.columns
            else None
        )
        mod_col = (
            "mod_dt_parsed"
            if "mod_dt_parsed" in df.columns
            else "Order Date Modified"
            if "Order Date Modified" in df.columns
            else None
        )

        status_lower = df[status_col].astype(str).str.lower().str.strip()
        is_shipped = status_lower.isin(shipped_statuses)

        dt_create = (
            safe_coerce_datetime_naive(df[date_col])
            if date_col
            else pd.Series(pd.NaT, index=df.index)
        )
        dt_mod = (
            safe_coerce_datetime_naive(df[mod_col])
            if mod_col
            else pd.Series(pd.NaT, index=df.index)
        )
        dt_effective = dt_mod.fillna(dt_create)

        active_mask = ~is_shipped
        shipped_mask = is_shipped & (
            (dt_effective.dt.date == today_bd) | (dt_create.dt.date == today_bd)
        )

        return df[active_mask | shipped_mask]

    return df


def filter_actual_sales(df: pd.DataFrame):
    """Return only revenue-recognized shipped/completed WooCommerce orders."""
    if df is None or df.empty:
        return df

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return df.iloc[0:0]

    actual_statuses = {status.lower() for status in SHIPPED_STATUSES}
    status_lower = df[status_col].astype(str).str.lower().str.strip()
    return df[status_lower.isin(actual_statuses)].copy()


def count_by_status(
    df: pd.DataFrame,
    *,
    status_col: str | None = None,
    order_id_col: str | None = None,
) -> dict[str, int]:
    """Count unique operational statuses in *df*."""
    if df is None or df.empty:
        return {"shipped": 0, "processing": 0, "held": 0, "exchange": 0, "other": 0}

    if status_col is None:
        status_col = (
            "Order Status"
            if "Order Status" in df.columns
            else "Status"
            if "Status" in df.columns
            else None
        )
    if status_col is None:
        return {"shipped": 0, "processing": 0, "held": 0, "exchange": 0, "other": 0}

    statuses = df[status_col].astype(str).str.lower().str.strip()

    shipped_mask = statuses.isin([s.lower() for s in SHIPPED_STATUSES])
    processing_mask = statuses.isin([s.lower() for s in ACTIVE_STATUSES])
    held_mask = statuses.isin([s.lower() for s in HOLD_WAITING_STATUSES])
    exchange_mask = _detect_exchange_mask(df)

    sales_mask = shipped_mask & ~exchange_mask
    other_mask = ~(sales_mask | processing_mask | held_mask | exchange_mask)

    def _count(mask: pd.Series) -> int:
        subset = df[mask]
        if order_id_col and order_id_col in subset.columns:
            return int(subset[order_id_col].nunique())
        return len(subset)

    return {
        "shipped": _count(sales_mask),
        "processing": _count(processing_mask),
        "held": _count(held_mask),
        "exchange": _count(exchange_mask),
        "other": _count(other_mask),
    }


def robust_order_count(
    df: pd.DataFrame,
    basket_total_orders: int = 0,
    *,
    order_id_candidates: tuple[str, ...] = ("Order ID", "Order Number"),
) -> int:
    """Return the unique-order count for *df*, resolving the best available key."""
    if basket_total_orders > 0:
        return basket_total_orders

    if df is None or df.empty:
        return 0

    for candidate in order_id_candidates:
        if candidate in df.columns:
            return int(df[candidate].nunique())

    return len(df)


def pick_order_id_column(
    df: pd.DataFrame,
    candidates: tuple[str, ...] = ("Order ID", "Order Number"),
    fallback: str | None = None,
) -> str | None:
    """Return the first candidate column present on *df*, or *fallback*."""
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return fallback


def filter_live_dashboard_view(df: pd.DataFrame, view: str, reference_date=None):
    """Apply the four mutually exclusive Live Dashboard visibility rules."""
    if df is None or df.empty:
        return df

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return df.iloc[0:0]

    created_col = (
        "dt_parsed"
        if "dt_parsed" in df.columns
        else "Order Date"
        if "Order Date" in df.columns
        else None
    )
    modified_col = (
        "mod_dt_parsed"
        if "mod_dt_parsed" in df.columns
        else "Order Date Modified"
        if "Order Date Modified" in df.columns
        else None
    )
    created = (
        safe_coerce_datetime_naive(df[created_col])
        if created_col
        else pd.Series(pd.NaT, index=df.index)
    )
    modified = (
        safe_coerce_datetime_naive(df[modified_col])
        if modified_col
        else pd.Series(pd.NaT, index=df.index)
    )

    today = reference_date or _get_bd_today()
    if hasattr(today, "date") and callable(today.date):
        today = today.date()
    previous_day = get_previous_working_day(today)
    statuses = df[status_col].astype(str).str.lower().str.strip()
    sale_statuses = {status.lower() for status in SHIPPED_STATUSES}
    queue_statuses = {status.lower() for status in ACTIVE_STATUSES}
    hold_waiting_statuses = {status.lower() for status in HOLD_WAITING_STATUSES}
    is_sale = statuses.isin(sale_statuses)
    is_queue = statuses.isin(queue_statuses)
    is_cancelled = statuses.isin(CANCELLED_STATUSES)
    is_hold_waiting = statuses.isin(hold_waiting_statuses) | statuses.str.contains(
        r"hold|waiting", case=False, na=False
    )
    sale_date = modified.fillna(created).dt.date
    created_date = created.dt.date

    processing_statuses = {
        "processing",
        "process",
        "wc-processing",
        "wc-process",
    }
    is_processing = statuses.isin(processing_statuses) | statuses.str.contains(
        r"process", case=False, na=False
    )

    exchange_mask = _detect_exchange_mask(df)
    is_sale = is_sale & ~exchange_mask

    v = str(view).strip()
    is_saturday = today.weekday() == 5
    if is_saturday:
        friday_date = today - timedelta(days=1)
        is_today_shipped_date = (sale_date == today) | (sale_date == friday_date)
        is_today_created_date = (created_date == today) | (created_date == friday_date)
        queue_prior_date = friday_date
    else:
        is_today_shipped_date = sale_date == today
        is_today_created_date = created_date == today
        queue_prior_date = today

    queue_cutoff_ts = pd.Timestamp(queue_prior_date).normalize()
    is_prior_queue = (created.dt.normalize() < queue_cutoff_ts) & is_queue

    if v in {"Today Shipped", "Today"}:
        mask = is_sale & is_today_shipped_date
    elif v in {"Last Day Shipped", "Last Day"}:
        mask = is_sale & (sale_date == previous_day)
    elif v == "Queue":
        mask = is_queue & ~is_processing
    elif v == "All Orders":
        mask = (
            ~is_cancelled
            & ~is_hold_waiting
            & (
                is_today_created_date
                | is_prior_queue
                | (is_sale & is_today_shipped_date)
            )
        )
    else:
        mask = pd.Series(False, index=df.index)

    return df[mask].copy()


def compute_live_filter_counts(df: pd.DataFrame, reference_date=None) -> dict[str, int]:
    """Compute distinct order counts for each of the 4 live dashboard filter views."""
    counts = {
        "All Orders": 0,
        "Today Shipped": 0,
        "Last Day Shipped": 0,
        "Queue": 0,
    }
    if df is None or df.empty:
        return counts

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return counts

    created_col = (
        "dt_parsed"
        if "dt_parsed" in df.columns
        else "Order Date"
        if "Order Date" in df.columns
        else None
    )
    modified_col = (
        "mod_dt_parsed"
        if "mod_dt_parsed" in df.columns
        else "Order Date Modified"
        if "Order Date Modified" in df.columns
        else None
    )
    id_col = next(
        (c for c in ["Order ID", "order_id", "ID", "id"] if c in df.columns),
        None,
    )

    created = (
        safe_coerce_datetime_naive(df[created_col])
        if created_col
        else pd.Series(pd.NaT, index=df.index)
    )
    modified = (
        safe_coerce_datetime_naive(df[modified_col])
        if modified_col
        else pd.Series(pd.NaT, index=df.index)
    )

    today = reference_date or _get_bd_today()
    if hasattr(today, "date") and callable(today.date):
        today = today.date()
    previous_day = get_previous_working_day(today)
    statuses = df[status_col].astype(str).str.lower().str.strip()
    sale_statuses = {status.lower() for status in SHIPPED_STATUSES}
    queue_statuses = {status.lower() for status in ACTIVE_STATUSES}
    hold_waiting_statuses = {status.lower() for status in HOLD_WAITING_STATUSES}
    is_sale = statuses.isin(sale_statuses)
    is_queue = statuses.isin(queue_statuses)
    is_cancelled = statuses.isin(CANCELLED_STATUSES)
    is_hold_waiting = statuses.isin(hold_waiting_statuses) | statuses.str.contains(
        r"hold|waiting", case=False, na=False
    )
    sale_date = modified.fillna(created).dt.date
    created_date = created.dt.date

    processing_statuses = {
        "processing",
        "process",
        "wc-processing",
        "wc-process",
    }
    is_processing = statuses.isin(processing_statuses) | statuses.str.contains(
        r"process", case=False, na=False
    )

    exchange_mask = _detect_exchange_mask(df)
    is_sale = is_sale & ~exchange_mask

    is_saturday = today.weekday() == 5
    if is_saturday:
        friday_date = today - timedelta(days=1)
        is_today_shipped_date = (sale_date == today) | (sale_date == friday_date)
        is_today_created_date = (created_date == today) | (created_date == friday_date)
        queue_prior_date = friday_date
    else:
        is_today_shipped_date = sale_date == today
        is_today_created_date = created_date == today
        queue_prior_date = today

    queue_cutoff_ts = pd.Timestamp(queue_prior_date).normalize()
    is_prior_queue = (created.dt.normalize() < queue_cutoff_ts) & is_queue

    masks = {
        "Today Shipped": is_sale & is_today_shipped_date,
        "Last Day Shipped": is_sale & (sale_date == previous_day),
        "Queue": is_queue & ~is_processing,
        "All Orders": (
            ~is_cancelled
            & ~is_hold_waiting
            & (
                is_today_created_date
                | is_prior_queue
                | (is_sale & is_today_shipped_date)
            )
        ),
    }

    for view_key, mask in masks.items():
        if id_col and id_col in df.columns:
            counts[view_key] = int(df.loc[mask, id_col].nunique())
        else:
            counts[view_key] = int(mask.sum())

    return counts


def apply_order_view(df: pd.DataFrame, nav_mode: str, order_view: str):
    """Filter an orders DataFrame to the selected order view within its slot."""
    if df is None or df.empty:
        return df

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return df

    if order_view == "All Orders" and nav_mode == "Today":
        return filter_all_orders_to_slot(df, nav_mode)
    if order_view == "Shipped":
        return filter_shipped_by_slot(df, nav_mode, is_comparison=False)
    if order_view == "Processing":
        return df[df[status_col].astype(str).str.lower() == "processing"]
    return df


def apply_order_view_comparison(df: pd.DataFrame, nav_mode: str, order_view: str):
    """Filter the comparison (other-slot) DataFrame for KPI delta computation."""
    if df is None or df.empty:
        return df

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return df

    if order_view == "All Orders":
        return filter_all_orders_to_slot(df, "Prev")
    if order_view == "Shipped":
        return filter_shipped_by_slot(df, nav_mode, is_comparison=True)
    if order_view == "Processing":
        return df[df[status_col].astype(str).str.lower() == "processing"]
    return df
