import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
from requests.auth import HTTPBasicAuth

from src.config.constants import SHIPPED_STATUSES
from src.config.settings import get_woocommerce_config
from src.processing.column_detection import scrub_raw_dataframe
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event


# ── Data transformation helpers ──────────────────────────────────────────────


def _flatten_order(order: dict) -> list[dict]:
    """Flatten a single WooCommerce order JSON into one dict per line item."""
    oid = order.get("id")
    onum = order.get("number")
    d_val = order.get("date_created")
    status = order.get("status")
    m_val = order.get("date_modified")
    bill = order.get("billing", {})
    ship = order.get("shipping", {})
    c_name = f"{bill.get('first_name', '')} {bill.get('last_name', '')}".strip()
    pmt = order.get("payment_method_title", "")

    return [
        {
            "Order ID": oid,
            "Order Number": onum,
            "Order Date": d_val,
            "Order Date Modified": m_val,
            "Order Status": status,
            "Full Name (Billing)": c_name,
            "Phone (Billing)": bill.get("phone", ""),
            "Shipping Address 1": ship.get("address_1", ""),
            "Shipping City": ship.get("city", ""),
            "State Name (Billing)": bill.get("state", ""),
            "Item Name": item.get("name"),
            "SKU": item.get("sku", ""),
            "Item Cost": item.get("price"),
            "Quantity": item.get("quantity"),
            "Order Total Amount": order.get("total"),
            "Payment Method Title": pmt,
        }
        for item in order.get("line_items", [])
    ]


# ── API fetch helpers ────────────────────────────────────────────────────────


def _fetch_wc_page(url: str, params: dict, auth: HTTPBasicAuth, page: int):
    """Fetch a single page of WooCommerce orders.
    
    Returns (rows, total_pages) where rows is the flattened list of order item dicts.
    """
    res = request_with_backoff("GET", url, params={**params, "page": page}, auth=auth, timeout=15)
    res.raise_for_status()
    import json
    data = json.loads(res.content.decode("utf-8-sig"))
    rows = []
    for order in data:
        rows.extend(_flatten_order(order))
    total_pages = int(res.headers.get("X-WP-TotalPages", 1))
    return rows, total_pages


def _fetch_wc_batch(url: str, params: dict, auth: HTTPBasicAuth) -> list:
    """Fetch all pages of WooCommerce orders concurrently and return flattened rows."""
    fields = "id,number,date_created,date_modified,status,billing,shipping,payment_method_title,line_items,total"
    params["_fields"] = fields

    try:
        rows, total_pages = _fetch_wc_page(url, params, auth, page=1)
    except Exception as e:
        log_system_event("WC_FETCH_INITIAL_ERROR", str(e))
        return []

    if total_pages <= 1:
        return rows

    # Fetch remaining pages concurrently
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(total_pages, 8)) as executor:
        futures = [executor.submit(_fetch_wc_page, url, params, auth, pg) for pg in range(2, total_pages + 1)]
        for future in futures:
            try:
                extra_rows, _ = future.result()
                rows.extend(extra_rows)
            except Exception as e:
                log_system_event("WC_FETCH_PAGE_ERROR", str(e))

    return rows


# ── Sync parameter builders ─────────────────────────────────────────────────


def _get_operational_sync_params() -> dict:
    """Build API params for the Operational Cycle sync mode (5-day rolling window)."""
    tz_bd = timezone(timedelta(hours=6))
    now_bd = datetime.now(tz_bd)
    shift_h = st.session_state.get("shift_cutoff_hour", 17)
    shift_m = st.session_state.get("shift_cutoff_minute", 30)
    anchor = now_bd.replace(hour=shift_h, minute=shift_m, second=0, microsecond=0) - timedelta(days=5)

    return {
        "per_page": 100,
        "after": anchor.isoformat(),
        "before": now_bd.replace(hour=23, minute=59, second=59).isoformat(),
        "status": "processing,completed,shipped,on-hold,pending,waiting,confirmed",
        "orderby": "date",
        "order": "desc",
    }


def _get_global_open_params() -> dict:
    """Build API params for fetching all open/hold orders."""
    return {
        "per_page": 100,
        "status": "on-hold,pending,waiting,confirmed",
        "orderby": "date",
        "order": "desc",
    }


def _get_custom_range_params() -> dict:
    """Build API params for the Custom Range sync mode."""
    start_date = st.session_state.get("wc_sync_start_date", datetime.now().date())
    start_time = st.session_state.get("wc_sync_start_time", (datetime.now() - timedelta(hours=12)).time())
    end_date = st.session_state.get("wc_sync_end_date", datetime.now().date())
    end_time = st.session_state.get("wc_sync_end_time", datetime.now().time())

    return {
        "per_page": 100,
        "after": f"{start_date}T{start_time.strftime('%H:%M:%S')}",
        "before": f"{end_date}T{end_time.strftime('%H:%M:%S')}",
        "status": "processing,completed,shipped,on-hold,pending,waiting,confirmed",
        "orderby": "date",
        "order": "desc",
    }


# ── Order merging ────────────────────────────────────────────────────────────


def _merge_deduplicated_orders(main_rows: list, extra_rows: list) -> list:
    """Merge two order lists, deduplicating by (Order ID, Item Name)."""
    seen = set()
    merged = []
    for r in main_rows + extra_rows:
        key = (r["Order ID"], r["Item Name"])
        if key not in seen:
            seen.add(key)
            merged.append(r)
    return merged


# ── Operational partitioning ─────────────────────────────────────────────────


def _compute_cutoff_times(tz_bd):
    """Compute cutoff boundaries for operational cycle partitioning.
    
    Returns (cutoff_today, prev_cutoff, day_before_prev, shipped_limit).
    """
    now_bd = datetime.now(tz_bd)
    ref_now = now_bd.replace(tzinfo=None)
    shift_h = st.session_state.get("shift_cutoff_hour", 17)
    shift_m = st.session_state.get("shift_cutoff_minute", 30)
    cutoff_today = ref_now.replace(hour=shift_h, minute=shift_m, second=0, microsecond=0)

    holiday_list = st.session_state.get("operational_holidays", [])

    def _is_holiday(d):
        return d.weekday() == 4 or d.strftime("%Y-%m-%d") in holiday_list

    prev_cutoff = cutoff_today - timedelta(days=1)
    day_ending_today = (cutoff_today - timedelta(days=1)).date()
    if st.session_state.get("override_merge_current") or (_is_holiday(day_ending_today) and not st.session_state.get("override_24h_current")):
        prev_cutoff = cutoff_today - timedelta(days=2)

    day_before_prev = prev_cutoff - timedelta(days=1)
    day_ending_prev = (prev_cutoff - timedelta(days=1)).date()
    if st.session_state.get("override_merge_previous") or (_is_holiday(day_ending_prev) and not st.session_state.get("override_24h_previous")):
        day_before_prev = prev_cutoff - timedelta(days=2)

    shipped_limit = cutoff_today + timedelta(minutes=30)
    return cutoff_today, prev_cutoff, day_before_prev, shipped_limit


def _partition_operational_data(df_full):
    """Split a full DataFrame into Today, Prev, and Backlog partitions.
    
    Returns (df_live, df_prev, df_backlog, slot_label, slot_boundaries).
    slot_boundaries: (curr_slot, prev_slot, backlog_slot).
    """
    df_full = df_full.copy()
    df_full["dt_parsed"] = pd.to_datetime(df_full["Order Date"], errors="coerce").dt.tz_localize(None)
    df_full["mod_dt_parsed"] = pd.to_datetime(df_full["Order Date Modified"], errors="coerce").dt.tz_localize(None)

    tz_bd = timezone(timedelta(hours=6))
    cutoff_today, prev_cutoff, day_before_prev, shipped_limit = _compute_cutoff_times(tz_bd)

    is_shipped = df_full["Order Status"].isin(SHIPPED_STATUSES)
    is_confirmed = df_full["Order Status"] == "confirmed"
    is_processing = df_full["Order Status"] == "processing"
    is_hold = df_full["Order Status"] == "on-hold"
    is_waiting = df_full["Order Status"].isin(["pending", "waiting"])

    df_live = df_full[
        ((df_full["dt_parsed"] >= prev_cutoff) & (df_full["dt_parsed"] <= shipped_limit))
        | ((df_full["mod_dt_parsed"] >= prev_cutoff) & (df_full["mod_dt_parsed"] <= shipped_limit) & is_shipped)
        | is_confirmed | is_processing
    ].copy()

    df_prev = df_full[
        (
            ((df_full["dt_parsed"] >= day_before_prev) & (df_full["dt_parsed"] < (prev_cutoff + timedelta(minutes=30))))
            | ((df_full["mod_dt_parsed"] >= day_before_prev) & (df_full["mod_dt_parsed"] < (prev_cutoff + timedelta(minutes=30))))
        ) & is_shipped
    ].copy()

    df_backlog = df_full[is_hold | is_waiting].copy()

    now_bd = datetime.now(tz_bd)
    slot_label = "Backlog" if 0 <= now_bd.hour < 6 else "Today"

    slot_boundaries = {
        "wc_curr_slot": (prev_cutoff, cutoff_today),
        "wc_prev_slot": (day_before_prev, prev_cutoff),
        "wc_backlog_slot": (cutoff_today, cutoff_today + timedelta(days=1)),
    }

    return df_live, df_prev, df_backlog, slot_label, slot_boundaries


def _build_result_payload(df_to_return, slot_label, modified_at, partitions, slots):
    """Build the standard results dictionary returned by load_from_woocommerce."""
    return {
        "df_to_return": df_to_return,
        "sync_desc": f"WooCommerce_{slot_label}_API_{len(df_to_return)}_Orders" if not df_to_return.empty else "woocommerce_api_empty",
        "modified_at": modified_at,
        "partitions": partitions,
        "slots": slots,
    }


# ── Main public functions ────────────────────────────────────────────────────


@st.cache_data(ttl=60, show_spinner=False)
def load_from_woocommerce():
    """Loads live data from WooCommerce REST API orders."""
    wc_info = get_woocommerce_config(required=False)
    wc_url = wc_info.get("store_url")
    wc_key = wc_info.get("consumer_key")
    wc_secret = wc_info.get("consumer_secret")

    if not wc_url or not wc_key or not wc_secret:
        raise ValueError(
            "WooCommerce integration requires WC_URL, WC_KEY, and WC_SECRET (or [woocommerce] table in secrets.toml)."
        )

    endpoint = f"{wc_url.rstrip('/')}/wp-json/wc/v3/orders"
    auth = HTTPBasicAuth(wc_key, wc_secret)
    tz_bd = timezone(timedelta(hours=6))

    try:
        sync_mode = st.session_state.get("wc_sync_mode", "Operational Cycle")

        if sync_mode == "Operational Cycle":
            params = _get_operational_sync_params()
            rows = _fetch_wc_batch(endpoint, params, auth)
            global_params = _get_global_open_params()
            global_rows = _fetch_wc_batch(endpoint, global_params, auth)
            rows = _merge_deduplicated_orders(rows, global_rows)
        else:
            params = _get_custom_range_params()
            rows = _fetch_wc_batch(endpoint, params, auth)

        df_full = pd.DataFrame(rows)
        if df_full.empty:
            return _build_result_payload(
                pd.DataFrame(), "", "N/A", {}, {}
            )

        now_str = datetime.now(tz_bd).strftime("%Y-%m-%d %H:%M:%S")

        if sync_mode == "Operational Cycle":
            df_live, df_prev, df_backlog, slot_label, slots = _partition_operational_data(df_full)
            df_to_return = df_backlog if slot_label == "Backlog" else df_live
            partitions = {
                "wc_curr_df": scrub_raw_dataframe(df_live),
                "wc_prev_df": scrub_raw_dataframe(df_prev),
                "wc_backlog_df": scrub_raw_dataframe(df_backlog),
            }
        else:
            df_to_return = df_full
            slot_label = "Custom"
            partitions = {}
            slots = {}

        return _build_result_payload(
            scrub_raw_dataframe(df_to_return),
            slot_label,
            now_str,
            partitions,
            slots,
        )

    except Exception as e:
        log_system_event("WC_API_ERROR", str(e))
        raise RuntimeError(f"Failed to fetch data from WooCommerce: {e}")


def fetch_specific_woocommerce_orders(order_ids: list):
    """Fetches exact orders by their WooCommerce ID."""
    if not order_ids:
        return []

    wc_info = get_woocommerce_config(required=False)
    wc_url = wc_info.get("store_url")
    wc_key = wc_info.get("consumer_key")
    wc_secret = wc_info.get("consumer_secret")

    if not wc_url or not wc_key or not wc_secret:
        raise ValueError("WooCommerce integration missing.")

    endpoint = f"{wc_url.rstrip('/')}/wp-json/wc/v3/orders"
    auth = HTTPBasicAuth(wc_key, wc_secret)

    # Split order_ids into batches of 100 because WC REST API limits 'include'
    batches = [order_ids[i:i + 100] for i in range(0, len(order_ids), 100)]
    all_processed = []

    try:
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_batch(batch_ids):
            include_str = ",".join(map(str, batch_ids))
            params = {"include": include_str, "_fields": "id,number,date_created,date_modified,status,billing,shipping,payment_method_title,line_items,total", "per_page": 100}
            res = request_with_backoff("GET", endpoint, params=params, auth=auth, timeout=15)
            if res.status_code != 200:
                return []
            import json
            data = json.loads(res.content.decode("utf-8-sig"))
            rows = []
            for order in data:
                rows.extend(_flatten_order(order))
            return rows

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_fetch_batch, b) for b in batches]
            for future in futures:
                all_processed.extend(future.result())

    except Exception as e:
        log_system_event("WC_SPECIFIC_FETCH_ERROR", str(e))

    return all_processed


def load_live_source():
    """Stateless fetch with stateful session update."""
    results = load_from_woocommerce()
    if results and isinstance(results, dict):
        # 1. Update Partitioned State
        partitions = results.get("partitions", {})
        for key, df in partitions.items():
            if df is not None:
                st.session_state[key] = df

        # 2. Update Slot Metadata
        slots = results.get("slots", {})
        for key, val in slots.items():
            if val is not None:
                st.session_state[key] = val

        # 3. Update Sync Metadata
        st.session_state.live_sync_time = datetime.now()

        # 4. Update Full Context for Forecasting
        st.session_state["wc_full_df"] = results.get("df_to_return")

        # 4. Silent Autosave for Offline Mode Fallback
        try:
            from src.utils.snapshots import save_sales_snapshot
            if not results["df_to_return"].empty:
                save_sales_snapshot(results["df_to_return"])
        except Exception:
            pass

        # 5. Return tuple for legacy unpacking
        return results["df_to_return"], results["sync_desc"], results["modified_at"]

    # Handle legacy return if any (for safety)
    if results:
        st.session_state.live_sync_time = datetime.now()
        return results

    raise ValueError("Failed to load WooCommerce live data.")


def get_items_sold_label(last_updated):
    from datetime import datetime, timedelta, timezone

    tz_bd = timezone(timedelta(hours=6))
    try:
        if (
            isinstance(last_updated, str)
            and last_updated != "N/A"
            and "snapshot" not in last_updated.lower()
        ):
            dt = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
            # Assume last updated time string is already in local tz
            if dt.hour < 16:
                return "Items to be sold"
    except Exception:
        pass

    if datetime.now(tz_bd).hour < 16:
        return "Items to be sold"
    return "Item sold"
