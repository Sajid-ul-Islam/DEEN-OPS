from datetime import datetime, timedelta

import pandas as pd
import polars as pl
from src.utils.streamlit_runtime import get_session_state

from src.config.constants import (
    ACTIVE_STATUSES,
    CANCELLED_STATUSES,
    HOLD_WAITING_STATUSES,
    SHIPPED_STATUSES,
    bd_now,
    bd_today,
)
from src.processing.categorization import (
    get_category_for_sales,
    get_sub_category_for_sales,
)
from src.processing.column_detection import find_columns, scrub_raw_dataframe
from src.utils.logging import log_system_event
from src.utils.product import get_base_product_name, get_size_from_name


def filter_shipped_by_slot(df, nav_mode, is_comparison=False):
    """Filters a DataFrame to shipped orders for the relevant time window.

    For Today mode (not comparison):
        - An order is "shipped today" if its mod_dt_parsed (date_modified from WooCommerce,
          converted to BD UTC+6) falls on today's calendar date.
        - This is INDEPENDENT of slot boundaries — any order that transitioned from
          hold/waiting/processing to a shipped status today is counted, regardless of when
          it was originally placed.
        - If mod_dt_parsed is null, falls back to dt_parsed (order creation date).

    For Prev/comparison modes:
        - Uses slot boundaries (wc_prev_slot / wc_curr_slot) to scope the date range.

    For custom range:
        - Uses user-selected start/end date range.

    Args:
        df: The order DataFrame to filter.
        nav_mode: Current navigation mode ('Today', 'Prev', 'Backlog').
        is_comparison: If True, applies the comparison slot.

    Returns:
        Filtered DataFrame containing only shipped orders within the relevant window.
    """
    from src.config.constants import SHIPPED_STATUSES

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

    today_bd = bd_today()

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
    # Day-over-day sales comparisons must not blend yesterday's shipments into
    # today's KPI after midnight.
    if nav_mode == "Today" and not is_comparison:
        today_bd = bd_today()
        today_mask = dt_effective.dt.date == today_bd
        return shipped_df[today_mask].copy()

    if nav_mode == "Today" and is_comparison:
        previous_day = get_previous_working_day(bd_today())
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


def filter_all_orders_to_slot(df, nav_mode):
    """Scope the non-cancelled operational workload to the selected window.

    For Today mode, keeps:
      - Every non-cancelled, non-sale status as operational workload
      - Shipped/completed orders whose modification date falls within the slot window

    For other modes (Prev / Backlog), delegates to slot boundaries as defined in session state.

    Returns a filtered DataFrame — never falls back to the full unscoped dataset.
    """
    from src.config.constants import CANCELLED_STATUSES, SHIPPED_STATUSES

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

    # "All Orders" is the operational workload: retain every WooCommerce status
    # except explicit cancellation. Revenue analytics apply the stricter shipped
    # status set separately.
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

            # Open (active) orders are part of the current queue — keep them regardless of
            # placement date, so processing orders placed before the selected range stay visible.
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

        # Active orders are part of the current open queue — keep them regardless of
        # creation date so orders placed before the shift start (but still open, e.g.
        # still in `processing`) stay visible in the Today / All Orders view.
        active_mask = ~is_shipped

        # Shipped orders: scoped by modification date within slot, falling back to creation date
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
        today_bd = bd_today()

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

        # Open (active) orders are part of the current queue — keep them regardless of
        # placement date, so processing orders placed before today stay visible.
        active_mask = ~is_shipped
        shipped_mask = is_shipped & (
            (dt_effective.dt.date == today_bd) | (dt_create.dt.date == today_bd)
        )

        return df[active_mask | shipped_mask]

    # Prev/Backlog with no slot info — return status-filtered only
    return df


def filter_actual_sales(df):
    """Return only revenue-recognized shipped/completed WooCommerce orders."""
    if df is None or df.empty:
        return df

    from src.config.constants import SHIPPED_STATUSES

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


def get_previous_working_day(reference_date=None):
    """Return the operational previous working day for comparisons.

    Skips Friday (the standard weekly off-day / holiday in Bangladesh).
    Specifically:
    - If reference_date is Saturday (weekday 5), returns Thursday (skipping Friday).
    - If the preliminary previous day is Friday (weekday 4), steps back to Thursday.
    """
    d = reference_date or bd_today()
    if hasattr(d, "date") and callable(d.date):
        d = d.date()
    elif isinstance(d, datetime):
        d = d.date()
    candidate = d - timedelta(days=1)
    if candidate.weekday() == 4:  # Friday is weekday 4 in Python
        candidate -= timedelta(days=1)
    return candidate


def filter_live_dashboard_view(df, view: str, reference_date=None):
    """Apply the four mutually exclusive Live Dashboard visibility rules.

    - "All Orders" (Default): All orders placed today (excluding cancelled, hold, and waiting)
      PLUS unfulfilled processing orders from previous days.
    - "Today Shipped" / "Today": Only orders shipped or completed today (00:00-23:59 BD).
    - "Last Day Shipped" / "Last Day": Only orders shipped or completed on the previous operational working day (skips Friday).
    - "Queue": Orders currently on hold, waiting, or pending across all dates (processing excluded).
    """
    if df is None or df.empty:
        return df

    from src.config.constants import (
        ACTIVE_STATUSES,
        CANCELLED_STATUSES,
        HOLD_WAITING_STATUSES,
        SHIPPED_STATUSES,
    )

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

    today = reference_date or bd_today()
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

    v = str(view).strip()
    is_saturday = today.weekday() == 5
    if is_saturday:
        friday_date = today - timedelta(days=1)
        is_today_shipped_date = (sale_date == today) | (sale_date == friday_date)
        is_today_created_date = (created_date == today) | (created_date == friday_date)
        queue_prior_date = friday_date
    else:
        is_today_shipped_date = (sale_date == today)
        is_today_created_date = (created_date == today)
        queue_prior_date = today

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
            & (is_today_created_date | ((created_date < queue_prior_date) & is_queue))
        )
    else:
        mask = pd.Series(False, index=df.index)

    return df[mask].copy()


def compute_live_filter_counts(df, reference_date=None) -> dict[str, int]:
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

    today = reference_date or bd_today()
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

    is_saturday = today.weekday() == 5
    if is_saturday:
        friday_date = today - timedelta(days=1)
        is_today_shipped_date = (sale_date == today) | (sale_date == friday_date)
        is_today_created_date = (created_date == today) | (created_date == friday_date)
        queue_prior_date = friday_date
    else:
        is_today_shipped_date = (sale_date == today)
        is_today_created_date = (created_date == today)
        queue_prior_date = today

    masks = {
        "Today Shipped": is_sale & is_today_shipped_date,
        "Last Day Shipped": is_sale & (sale_date == previous_day),
        "Queue": is_queue & ~is_processing,
        "All Orders": (
            ~is_cancelled
            & ~is_hold_waiting
            & (is_today_created_date | ((created_date < queue_prior_date) & is_queue))
        ),
    }

    for view_key, mask in masks.items():
        if id_col and id_col in df.columns:
            counts[view_key] = int(df.loc[mask, id_col].nunique())
        else:
            counts[view_key] = int(mask.sum())

    return counts


def apply_order_view(df, nav_mode, order_view):
    """Filter an orders DataFrame to the selected order view within its slot.

    Single source of truth for the Live Dashboard's "All Orders / Shipped /
    Processing" selector. Replaces three previously duplicated implementations
    (main render, the 20s KPI fragment, and dashboard_output).

    - "All Orders" + Today  -> slot-scoped open + shipped-today (GOAL.md invariant 2)
    - "Shipped"             -> shipped-by-slot (today = calendar day, else slot)
    - "Processing"          -> status == processing (case-insensitive)
    - anything else         -> returned unchanged
    """
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


def apply_order_view_comparison(df, nav_mode, order_view):
    """Filter the comparison (other-slot) DataFrame for KPI delta computation.

    Mirrors the historical delta semantics:
    - "All Orders" -> compared against the "Prev" slot window
    - "Shipped"    -> compared with is_comparison=True (flips the slot used)
    - "Processing" -> plain status filter
    """
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


def safe_coerce_datetime_naive(series: pd.Series) -> pd.Series:
    """Safely converts a pandas Series to timezone-naive datetime64[ns].
    If timestamps are timezone-aware or contain explicit UTC ISO indicators (Z or offset),
    converts them to Asia/Dhaka local time (+6).
    Naive timestamps are preserved as local naive datetimes without double shift.
    """
    if series is None or series.empty:
        return pd.to_datetime(series, errors="coerce")

    # If series is already datetime64 dtype
    if pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dt, "tz", None) is not None:
            return series.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
        return series

    # Standard parsing first
    parsed = pd.to_datetime(series, errors="coerce")
    if getattr(parsed.dt, "tz", None) is not None:
        try:
            return parsed.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
        except Exception:
            return parsed.dt.tz_localize(None)

    # If parsed result is naive string series, check if strings contain explicit UTC timezone designators ('Z', '+00:00')
    s_clean = series.dropna()
    if not s_clean.empty and isinstance(s_clean.iloc[0], str):
        first_val = str(s_clean.iloc[0])
        if "Z" in first_val or "+00" in first_val or "UTC" in first_val.upper():
            try:
                parsed_utc = pd.to_datetime(series, errors="coerce", utc=True)
                if getattr(parsed_utc.dt, "tz", None) is not None:
                    return parsed_utc.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
            except Exception:
                pass

    return parsed


def prepare_granular_data(df, selected_cols):
    """Sanitizes and prepares granular columns with unified internal names."""
    try:
        df = df.copy()
        df = scrub_raw_dataframe(df)

        if df.empty:
            return df, ""

        # Mapping to Standard Names for easier internal logic
        df["Product Name"] = (
            df[selected_cols["name"]].fillna("Unknown Product").astype(str)
        )
        df = df[~df["Product Name"].str.contains("Choose Any", case=False, na=False)]

        df["Item Cost"] = pd.to_numeric(
            df[selected_cols["cost"]]
            .astype(str)
            .str.replace(r"[^\d.]", "", regex=True),
            errors="coerce",
        ).fillna(0)
        df["Quantity"] = pd.to_numeric(
            df[selected_cols["qty"]].astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce",
        ).fillna(0)

        # v10.4 Standardized SKU support
        if "sku" in selected_cols and selected_cols["sku"] in df.columns:
            df["SKU"] = df[selected_cols["sku"]].fillna("N/A").astype(str)
        else:
            df["SKU"] = "N/A"

        timeframe_suffix = ""
        if "date" in selected_cols and selected_cols["date"] in df.columns:
            try:
                df["Date"] = safe_coerce_datetime_naive(df[selected_cols["date"]])
                dates_valid = df["Date"].dropna()
                if not dates_valid.empty:
                    if dates_valid.dt.to_period("M").nunique() == 1:
                        timeframe_suffix = dates_valid.iloc[0].strftime("%B_%Y")
                    else:
                        timeframe_suffix = f"{dates_valid.min().strftime('%d%b')}_to_{dates_valid.max().strftime('%d%b_%y')}"
                else:
                    log_system_event(
                        "DATE_PARSE_WARN",
                        "No valid dates parsed from date column; proceeding without date filtering.",
                    )
            except Exception as date_err:
                log_system_event(
                    "DATE_PARSE_ERROR",
                    f"Date parsing failed: {date_err}; proceeding without date column.",
                )
                non_null = df[selected_cols["date"]].dropna()
                val = str(non_null.iloc[0]) if not non_null.empty else ""
                timeframe_suffix = val.replace("/", "-").replace(" ", "_")[:20]

        if (df["Quantity"] < 0).any():
            log_system_event("DATA_ISSUE", "Found negative quantities, converted to 0.")
            df.loc[df["Quantity"] < 0, "Quantity"] = 0

        # Optimized Categorization & Extraction (Vectorized Maps)
        from src.utils.product import is_bundle_or_combo

        unique_names = df["Product Name"].unique()
        name_cat_map = {}
        name_subcat_map = {}
        name_size_map = {}
        name_clean_map = {}
        name_bundle_map = {}

        for name in unique_names:
            cat = get_category_for_sales(name)
            name_cat_map[name] = cat
            name_subcat_map[name] = get_sub_category_for_sales(name, cat)
            name_size_map[name] = get_size_from_name(name)
            name_clean_map[name] = get_base_product_name(name)
            name_bundle_map[name] = is_bundle_or_combo(name, "", cat)

        df["Category"] = df["Product Name"].map(name_cat_map)
        df["Sub-Category"] = df["Product Name"].map(name_subcat_map)
        df["Size"] = df["Product Name"].map(name_size_map)
        df["Clean_Product"] = df["Product Name"].map(name_clean_map)
        df["Filter_Identity"] = (
            df["Clean_Product"].astype(str) + " [" + df["SKU"].astype(str) + "]"
        )
        df["Is_Bundle_Combo"] = df["Product Name"].map(name_bundle_map)

        if "Subtotal Cost" in df.columns:
            df["Subtotal Cost"] = pd.to_numeric(
                df["Subtotal Cost"].astype(str).str.replace(r"[^\d.]", "", regex=True),
                errors="coerce",
            ).fillna(df["Item Cost"])
        else:
            df["Subtotal Cost"] = df["Item Cost"]

        df["Gross Amount"] = df["Subtotal Cost"] * df["Quantity"]
        df["Total Amount"] = df["Item Cost"] * df["Quantity"]

        if "Cashback Discount" in df.columns:
            df["Cashback Discount"] = pd.to_numeric(
                df["Cashback Discount"]
                .astype(str)
                .str.replace(r"[^\d.]", "", regex=True),
                errors="coerce",
            ).fillna(0)
        else:
            df["Cashback Discount"] = (df["Gross Amount"] - df["Total Amount"]).clip(
                lower=0
            )

        # Handle negative fee lines (if negative sign '-' is present, it is a fee discount/cashback)
        fee_cols = [
            c
            for c in df.columns
            if c.lower() in ["extra fee", "fee", "fees", "fee discount total"]
        ]
        for f_c in fee_cols:
            raw_fees = pd.to_numeric(
                df[f_c].astype(str).str.replace(r"[^\d.-]", "", regex=True),
                errors="coerce",
            ).fillna(0)
            neg_fees = raw_fees < 0
            if neg_fees.any():
                df.loc[neg_fees, "Cashback Discount"] = (
                    df.loc[neg_fees, "Cashback Discount"] + raw_fees[neg_fees].abs()
                )

        df["Net Amount"] = df["Total Amount"]

        # Ensure Order Status and other operational columns are present
        if "Order Status" not in df.columns:
            # Try to map status if not present (useful for manual uploads)
            status_col = find_columns(df).get("status")
            if status_col:
                df["Order Status"] = (
                    df[status_col].fillna("completed").astype(str).str.lower()
                )
            else:
                df["Order Status"] = "completed"

        # Exclude pending payments, cancelled, and failed orders from all analytics
        df = df[
            ~df["Order Status"]
            .astype(str)
            .str.lower()
            .isin(
                [
                    "pending",
                    "pending payment",
                    "cancelled",
                    "failed",
                    "refunded",
                    "trash",
                ]
            )
        ]

        return df, timeframe_suffix
    except Exception as e:
        log_system_event("PREPARE_ERROR", str(e))
        return pd.DataFrame(), ""


def aggregate_data(df, selected_cols):
    """Generates dashboard aggregates from granular standardized data using Polars."""
    try:
        cols_to_fill = [
            pl.col(c).fill_nan(0).fill_null(0)
            for c in ["Quantity", "Total Amount"]
            if c in df.columns
        ]
        lazy_df = pl.from_pandas(df).lazy()
        if cols_to_fill:
            lazy_df = lazy_df.with_columns(cols_to_fill)

        # 1. Summary
        group_keys = ["Category"]
        if "Sub-Category" in df.columns:
            group_keys.append("Sub-Category")

        summary = (
            lazy_df.group_by(group_keys)
            .agg(
                [
                    pl.col("Quantity").sum().alias("Total Qty"),
                    pl.col("Total Amount").sum().alias("Total Amount"),
                ]
            )
            .collect()
            .to_pandas()
        )

        total_rev = summary["Total Amount"].sum()
        total_qty = summary["Total Qty"].sum()
        if total_rev > 0:
            summary["Revenue Share (%)"] = (
                summary["Total Amount"] / total_rev * 100
            ).round(2)
        if total_qty > 0:
            summary["Quantity Share (%)"] = (
                summary["Total Qty"] / total_qty * 100
            ).round(2)

        # 2. Drilldown
        drill_keys = group_keys + ["Item Cost"]
        drilldown = (
            lazy_df.group_by(drill_keys)
            .agg(
                [
                    pl.col("Quantity").sum().alias("Total Qty"),
                    pl.col("Total Amount").sum().alias("Total Amount"),
                ]
            )
            .collect()
            .to_pandas()
        )
        if "Sub-Category" in drilldown.columns:
            drilldown.columns = [
                "Category",
                "Sub-Category",
                "Price (TK)",
                "Total Qty",
                "Total Amount",
            ]
        else:
            drilldown.columns = ["Category", "Price (TK)", "Total Qty", "Total Amount"]

        # 3. Top Items
        top_aggs = [
            pl.col("Quantity").sum().alias("Total Qty"),
            pl.col("Total Amount").sum().alias("Total Amount"),
            pl.col("Category").first().alias("Category"),
            pl.col("Clean_Product").first().alias("Clean_Product"),
        ]
        if "Sub-Category" in df.columns:
            top_aggs.append(pl.col("Sub-Category").first().alias("Sub-Category"))

        top_items = (
            lazy_df.group_by(["Product Name", "SKU"])
            .agg(top_aggs)
            .collect()
            .to_pandas()
        )
        top_items = top_items.sort_values("Total Amount", ascending=False)

        # 4. Basket Metrics
        basket_metrics = {
            "avg_basket_qty": 0,
            "avg_basket_value": 0,
            "total_orders": 0,
            "attachment_rate": 0,
        }
        group_cols = []
        if "order_id" in selected_cols and selected_cols["order_id"] in df.columns:
            group_cols.append(selected_cols["order_id"])
        elif "Order ID" in df.columns:
            group_cols.append("Order ID")

        # Count unique orders BEFORE adding phone to group_cols
        order_id_col = group_cols[0] if group_cols else None
        unique_orders_count = df[order_id_col].nunique() if order_id_col else len(df)

        if "phone" in selected_cols and selected_cols["phone"] in df.columns:
            group_cols.append(selected_cols["phone"])
        elif "Phone (Billing)" in df.columns:
            group_cols.append("Phone (Billing)")

        if group_cols:
            order_groups = (
                lazy_df.group_by(group_cols)
                .agg(
                    [
                        pl.col("Quantity").sum().alias("Quantity"),
                        pl.col("Total Amount").sum().alias("Total Amount"),
                        pl.when(~pl.col("Is_Bundle_Combo"))
                        .then(1)
                        .otherwise(0)
                        .sum()
                        .alias("Item Count"),
                    ]
                )
                .collect()
                .to_pandas()
            )

            avg_qty = order_groups["Quantity"].mean()
            avg_val = order_groups["Total Amount"].mean()
            basket_metrics["avg_basket_qty"] = (
                float(avg_qty) if pd.notna(avg_qty) else 0
            )
            basket_metrics["avg_basket_value"] = (
                float(avg_val) if pd.notna(avg_val) else 0
            )
            # Use unique order count, not grouped row count
            basket_metrics["total_orders"] = unique_orders_count

            multi_item_orders = len(order_groups[order_groups["Item Count"] > 1])
            basket_metrics["attachment_rate"] = (
                (multi_item_orders / unique_orders_count * 100)
                if unique_orders_count > 0
                else 0
            )

        phone_col = None
        if "phone" in selected_cols and selected_cols["phone"] in df.columns:
            phone_col = selected_cols["phone"]
        elif "Phone (Billing)" in df.columns:
            phone_col = "Phone (Billing)"

        if not phone_col:
            basket_metrics["avg_customer_value"] = basket_metrics["avg_basket_value"]
            basket_metrics["unique_customers"] = unique_orders_count

        basket_metrics["total_gross_revenue"] = (
            float(df["Gross Amount"].sum())
            if "Gross Amount" in df.columns
            else float(df["Total Amount"].sum())
        )
        basket_metrics["total_cashback_discount"] = (
            float(df["Cashback Discount"].sum())
            if "Cashback Discount" in df.columns
            else 0.0
        )

        return drilldown, summary, top_items, basket_metrics
    except Exception as e:
        log_system_event("AGGREGATE_ERROR", str(e))
        return None, None, None, {}


def get_dispatch_metrics(active_df, total_orders=0):
    """Calculates dispatch, exchange, and freebie metrics from active shift data."""
    from src.config.constants import SHIPPED_STATUSES

    metrics = {
        "outlet_dispatch": 0,
        "exchange_dispatch": 0,
        "last_shipped_order": "N/A",
        "last_pathao_print": "N/A",
        "ecom_dispatch": 0,
        "pathao_count": 0,
        "other_count": 0,
        "pending": 0,
        "dispatched": 0,
        "dispatch_rate": 0.0,
    }

    if active_df is not None and not active_df.empty:
        status_col = (
            "Order Status"
            if "Order Status" in active_df.columns
            else "Status"
            if "Status" in active_df.columns
            else None
        )
        order_col = (
            "Order ID"
            if "Order ID" in active_df.columns
            else "Order Number"
            if "Order Number" in active_df.columns
            else None
        )

        # Use modification date for sorting, as this reflects when an order was shipped.
        # Fall back to creation date if modification date is not available.
        mod_date_col = (
            "mod_dt_parsed"
            if "mod_dt_parsed" in active_df.columns
            else (
                "Order Date Modified"
                if "Order Date Modified" in active_df.columns
                else None
            )
        )
        date_col = (
            mod_date_col
            if mod_date_col
            else (
                "Date"
                if "Date" in active_df.columns
                else "Order Date"
                if "Order Date" in active_df.columns
                else None
            )
        )
        pmt_col = (
            "Payment Method Title"
            if "Payment Method Title" in active_df.columns
            else None
        )

        if order_col:
            if status_col:
                metrics["exchange_dispatch"] = active_df[
                    active_df[status_col]
                    .astype(str)
                    .str.lower()
                    .str.contains("exchange", na=False)
                ][order_col].nunique()

                outlet_mask = (
                    active_df[status_col]
                    .astype(str)
                    .str.lower()
                    .str.contains("outlet", na=False)
                )
                if pmt_col:
                    outlet_mask = outlet_mask | active_df[pmt_col].astype(
                        str
                    ).str.lower().str.contains("outlet", na=False)
                metrics["outlet_dispatch"] = active_df[outlet_mask][order_col].nunique()

                from src.config.constants import ACTIVE_STATUSES, SHIPPED_STATUSES

                status_lower = active_df[status_col].astype(str).str.lower().str.strip()
                # Pending orders
                pending_mask = status_lower.isin([s.lower() for s in ACTIVE_STATUSES])
                metrics["pending"] = active_df[pending_mask][order_col].nunique()

                # Dispatched orders: ONLY orders with status in SHIPPED_STATUSES
                shipped_mask = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])
                shipped_df = active_df[shipped_mask]
                metrics["dispatched"] = (
                    shipped_df[order_col].nunique() if not shipped_df.empty else 0
                )
            else:
                metrics["dispatched"] = active_df[order_col].nunique()
                shipped_df = active_df

            # Pathao Consignment ID check on shipped dataframe
            if not shipped_df.empty:
                if "Pathao Consignment ID" in shipped_df.columns:
                    p_col = (
                        shipped_df["Pathao Consignment ID"]
                        .astype(str)
                        .str.strip()
                        .str.lower()
                    )
                    pathao_mask = (
                        (p_col != "")
                        & (p_col != "nan")
                        & (p_col != "none")
                        & (p_col != "n/a")
                    )
                    metrics["pathao_count"] = shipped_df[pathao_mask][
                        order_col
                    ].nunique()
                elif "Shipping Method Title" in shipped_df.columns:
                    p_col = shipped_df["Shipping Method Title"].astype(str).str.lower()
                    pathao_mask = p_col.str.contains("pathao", na=False)
                    metrics["pathao_count"] = shipped_df[pathao_mask][
                        order_col
                    ].nunique()
                else:
                    metrics["pathao_count"] = metrics["dispatched"]
            else:
                metrics["pathao_count"] = 0

            metrics["other_count"] = max(
                0, metrics["dispatched"] - metrics["pathao_count"]
            )

            if not shipped_df.empty:
                latest_shipped = (
                    shipped_df.sort_values(date_col, ascending=False).iloc[0]
                    if date_col and date_col in shipped_df.columns
                    else shipped_df.iloc[0]
                )
                metrics["last_shipped_order"] = str(latest_shipped[order_col])

                if "Pathao Consignment ID" in shipped_df.columns:
                    p_col_s = (
                        shipped_df["Pathao Consignment ID"]
                        .astype(str)
                        .str.strip()
                        .str.lower()
                    )
                    p_shipped = shipped_df[
                        (p_col_s != "")
                        & (p_col_s != "nan")
                        & (p_col_s != "none")
                        & (p_col_s != "n/a")
                    ]
                    if not p_shipped.empty:
                        latest_pathao = (
                            p_shipped.sort_values(date_col, ascending=False).iloc[0]
                            if date_col and date_col in p_shipped.columns
                            else p_shipped.iloc[0]
                        )
                        metrics["last_pathao_print"] = str(latest_pathao[order_col])
                    else:
                        metrics["last_pathao_print"] = str(latest_shipped[order_col])
                else:
                    metrics["last_pathao_print"] = str(latest_shipped[order_col])

    if total_orders > 0:
        metrics["dispatch_rate"] = (metrics["dispatched"] / total_orders) * 100.0
    metrics["ecom_dispatch"] = max(
        0, total_orders - metrics["outlet_dispatch"] - metrics["exchange_dispatch"]
    )
    return metrics


def generate_executive_briefing(
    today_rev,
    today_qty,
    today_orders,
    today_aov,
    dm,
    top,
    prev_rev=None,
    prev_orders=None,
    forecast_str="",
    gross_rev=None,
    cashback_disc=None,
    new_customers=None,
    returning_customers=None,
):
    """Generates the single source of truth narrative for the Executive Briefing."""

    dm = dm or {}

    g_rev = gross_rev if gross_rev is not None else today_rev
    gross_aov = (g_rev / today_orders) if today_orders > 0 else today_aov

    report_lines = [
        "📊 *DEEN-OPS Executive Briefing*",
        f"📅 {bd_now().strftime('%A, %d %B %Y')}",
        "",
        f"💵 *Gross Revenue:* ৳{g_rev:,.0f}",
        "",
        f"📦 *Shipped Items:* {today_qty:,.0f}",
        f"🛍️ *Avg Basket Value:* ৳{gross_aov:,.0f}",
    ]

    report_lines.extend(
        [
            "",
            "",
            f"📋 *Last Shipped Order:* {dm.get('last_shipped_order', 'N/A')}",
            f"🖨️ *Last Pathao Print:* {dm.get('last_pathao_print', 'N/A')}",
            "",
            f"🛒 *Total Orders:* {today_orders:,.0f}",
            f"🔄 *Exchange:* {dm.get('exchange_dispatch', 0):,.0f}",
            f"🚀 *Ecom:* {dm.get('ecom_dispatch', 0):,.0f}",
            f"🏪 *Outlet:* {dm.get('outlet_dispatch', 0):,.0f}",
            "",
            "🔥 *Top Performing Products:*",
        ]
    )

    if top is not None and not top.empty:
        if "Clean_Product" in top.columns:
            group_cols = (
                ["Clean_Product", "SKU"] if "SKU" in top.columns else ["Clean_Product"]
            )
            top_summary = top.groupby(group_cols, as_index=False).agg(
                {"Total Qty": "sum", "Total Amount": "sum"}
            )
            top_summary = top_summary.sort_values("Total Amount", ascending=False)
            top_3 = top_summary.head(3)
            for _, row in top_3.iterrows():
                sku_str = (
                    f" [{row['SKU']}]"
                    if "SKU" in top.columns
                    and str(row["SKU"]) not in ["N/A", "", "None", "nan"]
                    else ""
                )
                report_lines.append(
                    f"• {row['Clean_Product']}{sku_str} ({row['Total Qty']} pcs)"
                )
        else:
            top_3 = top.head(3)
            for _, row in top_3.iterrows():
                report_lines.append(f"• {row['Product Name']} ({row['Total Qty']} pcs)")
    else:
        report_lines.append("No product data available.")

    report_lines.extend(
        [
            "",
            "💻 _Access the full dashboard at your DEEN-OPS Terminal: https://deen-ops.streamlit.app/_",
        ]
    )

    return "\n".join(report_lines)


def detect_active_campaign(df: pd.DataFrame | None) -> dict:
    """Dynamically inspects live orders to identify active campaigns, discounts, flat sales, or cashback.

    Returns a dict with campaign metadata:
      - is_active: bool
      - campaign_name: str (e.g. "Flat 50% Sale", "Cashback Offer", "Coupon Promo")
      - campaign_type: str ("flat_sale", "cashback", "coupon", "item_discount", "none")
      - total_discount: float
      - gross_revenue: float
      - net_revenue: float
      - discount_rate_pct: float
      - affected_orders_pct: float
      - badge_label: str
    """
    default_res = {
        "is_active": False,
        "campaign_name": "No Active Campaign",
        "campaign_type": "none",
        "total_discount": 0.0,
        "gross_revenue": 0.0,
        "net_revenue": 0.0,
        "discount_rate_pct": 0.0,
        "affected_orders_pct": 0.0,
        "badge_label": "",
    }
    if df is None or df.empty:
        return default_res

    # 1. Total discounts & Revenue
    fee_disc = 0.0
    if "Fee Discount Total" in df.columns:
        fee_disc = float(
            pd.to_numeric(df["Fee Discount Total"], errors="coerce").fillna(0).sum()
        )

    item_disc = 0.0
    if "Item Discount" in df.columns:
        item_disc = float(
            pd.to_numeric(df["Item Discount"], errors="coerce").fillna(0).sum()
        )
    elif (
        "Subtotal Cost" in df.columns
        and "Item Cost" in df.columns
        and "Quantity" in df.columns
    ):
        sub = pd.to_numeric(df["Subtotal Cost"], errors="coerce").fillna(0)
        cost = pd.to_numeric(df["Item Cost"], errors="coerce").fillna(0)
        qty = pd.to_numeric(df["Quantity"], errors="coerce").fillna(1)
        item_disc = float(((sub - cost) * qty).clip(lower=0).sum())

    order_disc = 0.0
    if "Order Discount Total" in df.columns and item_disc == 0.0:
        order_disc = float(
            pd.to_numeric(df["Order Discount Total"], errors="coerce").fillna(0).sum()
        )

    total_discount = fee_disc + item_disc + order_disc

    net_rev = 0.0
    if "Total Amount" in df.columns:
        net_rev = float(
            pd.to_numeric(df["Total Amount"], errors="coerce").fillna(0).sum()
        )
    elif "Order Total Amount" in df.columns:
        ord_col = "Order ID" if "Order ID" in df.columns else None
        if ord_col:
            net_rev = float(
                pd.to_numeric(
                    df.groupby(ord_col)["Order Total Amount"].first(), errors="coerce"
                )
                .fillna(0)
                .sum()
            )
        else:
            net_rev = float(
                pd.to_numeric(df["Order Total Amount"], errors="coerce").fillna(0).sum()
            )

    gross_rev = net_rev + total_discount
    discount_rate_pct = (total_discount / gross_rev * 100) if gross_rev > 0 else 0.0

    # 2. Check affected orders
    ord_col = (
        "Order ID"
        if "Order ID" in df.columns
        else "Order Number"
        if "Order Number" in df.columns
        else None
    )
    tot_orders = (
        len(df[ord_col].dropna().unique())
        if ord_col and ord_col in df.columns
        else len(df)
    )

    disc_orders = 0
    if ord_col and ord_col in df.columns:
        disc_mask = pd.Series(False, index=df.index)
        if "Cashback Discount" in df.columns:
            disc_mask |= (
                pd.to_numeric(df["Cashback Discount"], errors="coerce").fillna(0) > 0
            )
        if "Item Discount" in df.columns:
            disc_mask |= (
                pd.to_numeric(df["Item Discount"], errors="coerce").fillna(0) > 0
            )
        if "Fee Discount Total" in df.columns:
            disc_mask |= (
                pd.to_numeric(df["Fee Discount Total"], errors="coerce").fillna(0) > 0
            )
        disc_orders = len(df.loc[disc_mask, ord_col].dropna().unique())
    affected_pct = (disc_orders / tot_orders * 100) if tot_orders > 0 else 0.0

    # 3. Campaign Type & Name Detection from WooCommerce Signals
    if total_discount < 50.0 or discount_rate_pct < 0.5:
        return default_res

    # Check fee notes for explicit cashback
    has_cashback_fee = False
    if "Fee Notes" in df.columns:
        notes_concat = " ".join(df["Fee Notes"].dropna().astype(str).tolist()).lower()
        if "cashback" in notes_concat or "cash back" in notes_concat:
            has_cashback_fee = True

    # Check coupons
    coupon_names = []
    if "Coupons" in df.columns:
        raw_coupons = df["Coupons"].dropna().astype(str).tolist()
        for c in raw_coupons:
            for piece in c.split(","):
                clean_c = piece.strip().upper()
                if clean_c and clean_c not in ("NONE", "NAN", "", "N/A"):
                    coupon_names.append(clean_c)
        coupon_names = list(dict.fromkeys(coupon_names))

    if has_cashback_fee:
        c_type = "cashback"
        c_name = "Cashback Offer"
    elif coupon_names:
        c_type = "coupon"
        c_name = f"Coupon Promo ({', '.join(coupon_names[:2])})"
    elif discount_rate_pct >= 25.0:
        c_type = "flat_sale"
        rounded_rate = int(round(discount_rate_pct / 5.0) * 5)
        c_name = f"Flat {rounded_rate}% Sale"
    else:
        c_type = "item_discount"
        c_name = f"Sale Campaign ({discount_rate_pct:.0f}% Off)"

    badge_label = f"🎯 {c_name} −৳{int(total_discount):,} ({affected_pct:.0f}% orders)"

    return {
        "is_active": True,
        "campaign_name": c_name,
        "campaign_type": c_type,
        "total_discount": total_discount,
        "gross_revenue": gross_rev,
        "net_revenue": net_rev,
        "discount_rate_pct": discount_rate_pct,
        "affected_orders_pct": affected_pct,
        "badge_label": badge_label,
    }


def aggregate_product_listing(
    df: pd.DataFrame,
    item_col: str,
    qty_col: str,
    sku_col: str | None = None,
) -> pd.DataFrame:
    """Aggregate orders by item name and optionally SKU for product listing export.

    Sorts products first item-wise (case-insensitive alphabetical ascending),
    then SKU-wise (case-insensitive alphabetical ascending) so that variants of
    each product stay strictly grouped together in the export file.
    """
    if df is None or df.empty or item_col not in df.columns:
        return pd.DataFrame()

    group_cols = [item_col]
    use_sku = bool(sku_col and sku_col != "None" and sku_col in df.columns)
    if use_sku:
        group_cols.append(sku_col)

    df_copy = df.copy()
    df_copy[qty_col] = pd.to_numeric(
        df_copy[qty_col].astype(str).str.replace(r"[^\d.-]", "", regex=True),
        errors="coerce",
    ).fillna(1)

    merged = df_copy.groupby(group_cols, as_index=False)[qty_col].sum()

    sort_cols = [item_col]
    if use_sku:
        sort_cols.append(sku_col)

    merged = merged.sort_values(
        by=sort_cols,
        ascending=True,
        key=lambda col: col.astype(str).str.lower(),
        na_position="last",
    ).reset_index(drop=True)

    return merged

