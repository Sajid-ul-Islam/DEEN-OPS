from datetime import datetime, time, timedelta

import pandas as pd
from requests.auth import HTTPBasicAuth

from src.config.constants import BD_TZ, SHIPPED_STATUSES, bd_now
from src.config.settings import get_woocommerce_config
from src.processing.column_detection import scrub_raw_dataframe
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event
from src.utils.streamlit_runtime import runtime as st

# ── Data transformation helpers ──────────────────────────────────────────────


def _normalize_iso_gmt(dt_str: str) -> str:
    """Ensure ISO date string from WooCommerce GMT fields has an explicit Z suffix if missing."""
    if not dt_str or not isinstance(dt_str, str):
        return dt_str
    dt_str = dt_str.strip()
    if (
        dt_str
        and not dt_str.endswith("Z")
        and "+" not in dt_str
        and "-" not in dt_str[10:]
    ):
        return dt_str + "Z"
    return dt_str


def _flatten_order(order: dict) -> list[dict]:
    """Flatten a single WooCommerce order JSON into one dict per line item."""
    oid = order.get("id")
    onum = order.get("number")
    if order.get("date_created_gmt"):
        d_val = _normalize_iso_gmt(order.get("date_created_gmt"))
    else:
        d_val = order.get("date_created")

    if order.get("date_modified_gmt"):
        m_val = _normalize_iso_gmt(order.get("date_modified_gmt"))
    else:
        m_val = order.get("date_modified")
    status = order.get("status")
    bill = order.get("billing", {})
    ship = order.get("shipping", {})
    c_name = f"{bill.get('first_name', '')} {bill.get('last_name', '')}".strip()
    pmt = order.get("payment_method_title", "")

    ptc_consignment_id = ""
    for meta in order.get("meta_data", []):
        k = str(meta.get("key", "")).lower()
        if k in [
            "ptc_consignment_id",
            "pathao_consignment_id",
            "consignment_id",
            "tracking_number",
            "tracking_code",
            "_pathao_consignment_id",
            "pathao_tracking",
            "shipment_id",
            "_tracking_number",
            "courier_consignment_id",
        ]:
            v = str(meta.get("value", "")).strip()
            if v and v.lower() not in ["none", "nan", "null", "n/a", "0"]:
                ptc_consignment_id = v
                break

    # Use the actual order status directly from WooCommerce
    if not status or not str(status).strip():
        status = "processing"

    # Extract order level discounts, fee lines, & coupons
    ord_discount_total = float(order.get("discount_total", 0) or 0)
    coupons = [
        c.get("code")
        for c in order.get("coupon_lines", [])
        if isinstance(c, dict) and c.get("code")
    ]
    coupon_str = ", ".join(coupons) if coupons else ""

    # Process fee_lines: Negative fees = discount/cashback, Positive fees = extra fee
    fee_lines = order.get("fee_lines", [])
    fee_discount_total = 0.0
    extra_fee_total = 0.0
    fee_notes = []

    for fee in fee_lines:
        if isinstance(fee, dict):
            f_val = float(fee.get("total", 0) or 0)
            f_name = fee.get("name", "Fee")
            if f_val < 0:
                fee_discount_total += abs(f_val)
                fee_notes.append(f"{f_name}: -TK {abs(f_val):,.0f}")
            elif f_val > 0:
                extra_fee_total += f_val
                fee_notes.append(f"{f_name}: +TK {f_val:,.0f}")

    line_items = order.get("line_items", [])
    num_items = len(line_items) if line_items else 1
    split_ord_discount = ord_discount_total / num_items if num_items > 0 else 0.0
    split_fee_discount = fee_discount_total / num_items if num_items > 0 else 0.0
    split_extra_fee = extra_fee_total / num_items if num_items > 0 else 0.0
    fee_notes_str = ", ".join(fee_notes) if fee_notes else ""

    flattened = []
    for idx, item in enumerate(line_items):
        item_id = item.get("id", idx)
        qty_raw = item.get("quantity", 1)
        qty_num = (
            float(str(qty_raw if qty_raw is not None else "1").replace(",", ""))
            if float(str(qty_raw if qty_raw is not None else "1").replace(",", "")) > 0
            else 1.0
        )

        tot_val = float(item.get("total", 0) or 0)
        sub_val = float(item.get("subtotal", tot_val) or tot_val)

        eff_unit_cost = (
            tot_val / qty_num if tot_val > 0 else float(item.get("price", 0) or 0)
        )
        std_unit_cost = sub_val / qty_num if sub_val > 0 else eff_unit_cost

        item_disc = max(0.0, sub_val - tot_val)
        total_cashback_disc = item_disc + split_ord_discount + split_fee_discount

        flattened.append(
            {
                "Order ID": oid,
                "Line Item ID": item_id,
                "Line Item Index": idx,
                "Order Number": onum,
                "Order Date": d_val,
                "Order Date Modified": m_val,
                "Order Status": status,
                "Created via": str(order.get("created_via", "")).strip(),
                "Full Name (Billing)": c_name,
                "Phone (Billing)": bill.get("phone", ""),
                "Billing Email": bill.get("email", ""),
                "Shipping Address 1": ship.get("address_1", ""),
                "Shipping City": ship.get("city", ""),
                "State Name (Billing)": bill.get("state", ""),
                "Item Name": item.get("name"),
                "SKU": item.get("sku", ""),
                # Effective Unit Price (Net after line item discounts/cashback)
                "Item Cost": eff_unit_cost,
                # Standard Unit Price (Gross before line item discounts/cashback)
                "Subtotal Cost": std_unit_cost,
                "Item Discount": item_disc,
                "Order Discount Total": ord_discount_total,
                "Fee Discount Total": split_fee_discount,
                "Extra Fee": split_extra_fee,
                "Cashback Discount": total_cashback_disc,
                "Fee Notes": fee_notes_str,
                "Coupons": coupon_str,
                "Quantity": qty_num,
                "Order Total Amount": order.get("total"),
                "Payment Method Title": pmt,
                "Pathao Consignment ID": ptc_consignment_id,
            }
        )
    return flattened


# ── API fetch helpers ────────────────────────────────────────────────────────


def _fetch_wc_page(url: str, params: dict, auth: HTTPBasicAuth, page: int):
    """Fetch a single page of WooCommerce orders.

    Returns (rows, total_pages) where rows is the flattened list of order item dicts.
    """
    res = request_with_backoff(
        "GET", url, params={**params, "page": page}, auth=auth, timeout=15
    )
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
    fields = "id,number,date_created,date_created_gmt,date_modified,date_modified_gmt,status,billing,shipping,payment_method_title,line_items,total,discount_total,shipping_total,fee_lines,coupon_lines,meta_data"
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

    with ThreadPoolExecutor(max_workers=min(total_pages, 4)) as executor:
        futures = [
            executor.submit(_fetch_wc_page, url, params, auth, pg)
            for pg in range(2, total_pages + 1)
        ]
        for future in futures:
            try:
                extra_rows, _ = future.result()
                rows.extend(extra_rows)
            except Exception as e:
                log_system_event("WC_FETCH_PAGE_ERROR", str(e))

    return rows


def get_woocommerce_shipped_orders_count(after_iso: str, before_iso: str) -> int:
    """Fetch the total count of shipped orders between two dates using X-WP-Total headers."""
    cfg = get_woocommerce_config()
    if not cfg:
        return 0

    url = f"{cfg.get('store_url', '').rstrip('/')}/wp-json/wc/v3/orders"
    auth = HTTPBasicAuth(cfg.get("consumer_key", ""), cfg.get("consumer_secret", ""))

    params = {
        "per_page": 1,
        "after": after_iso,
        "before": before_iso,
        "status": "shipped,completed",
        "_fields": "id",
    }

    try:
        res = request_with_backoff("GET", url, params=params, auth=auth, timeout=10)
        if res.status_code == 200:
            return int(res.headers.get("X-WP-Total", 0))
    except Exception as e:
        log_system_event("WC_COUNT_FETCH_ERROR", str(e))

    return 0


# ── Sync parameter builders ─────────────────────────────────────────────────


def _get_operational_sync_params(cache_buster: str | None = None) -> dict:
    """Build API params for the Operational Cycle sync mode (3-day rolling window or user-selected custom date range)."""
    now_bd = bd_now()
    shift_h = st.session_state.get("shift_cutoff_hour", 18)
    shift_m = st.session_state.get("shift_cutoff_minute", 0)

    custom_range = st.session_state.get("live_custom_range")
    if (
        custom_range
        and isinstance(custom_range, (tuple, list))
        and len(custom_range) == 2
    ):
        start_d, end_d = custom_range[0], custom_range[1]
        today_bd = now_bd.date()
        if start_d != today_bd or end_d != today_bd:
            start_dt = datetime.combine(start_d, datetime.min.time()) - timedelta(
                hours=6
            )
            end_dt = datetime.combine(end_d, datetime.max.time()) - timedelta(hours=6)
            return _apply_cache_buster(
                {
                    "per_page": 100,
                    "after": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "before": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "status": "any",
                    "orderby": "date",
                    "order": "desc",
                },
                cache_buster,
            )

    anchor_bd = now_bd.replace(
        hour=shift_h, minute=shift_m, second=0, microsecond=0
    ) - timedelta(days=3)
    anchor_utc = anchor_bd - timedelta(hours=6)

    return _apply_cache_buster(
        {
            "per_page": 100,
            "after": f"{anchor_utc.strftime('%Y-%m-%dT%H:%M:%S')}Z",
            "status": "any",
            "orderby": "date",
            "order": "desc",
        },
        cache_buster,
    )


def _get_today_modified_shipped_params(cache_buster: str | None = None) -> dict:
    """Build API params to fetch orders modified during today's operational shift with shipped status.

    This catches old orders (placed before the 3-day window) that were shipped in current shift.
    WooCommerce supports `modified_after` to filter by date_modified regardless of order date.
    Note: Subtract 6 hours from prev_cutoff (BD Time UTC+6) so WooCommerce API receives UTC ISO time.
    """
    _, prev_cutoff, _, _ = _compute_cutoff_times(BD_TZ)
    prev_cutoff_utc = prev_cutoff - timedelta(hours=6)
    return _apply_cache_buster(
        {
            "per_page": 100,
            "modified_after": f"{prev_cutoff_utc.strftime('%Y-%m-%dT%H:%M:%S')}Z",
            "status": "any",
            "orderby": "modified",
            "order": "desc",
        },
        cache_buster,
    )


def _get_global_open_params(cache_buster: str | None = None) -> dict:
    """Build API params for fetching all open/hold/processing orders."""
    return _apply_cache_buster(
        {
            "per_page": 100,
            "status": "on-hold,pending,processing",
            "orderby": "date",
            "order": "desc",
        },
        cache_buster,
    )


def _get_custom_range_params(cache_buster: str | None = None) -> dict:
    """Build API params for the Custom Range sync mode."""
    now_bd = bd_now()
    start_date = st.session_state.get("wc_sync_start_date", now_bd.date())
    start_time = st.session_state.get(
        "wc_sync_start_time", (now_bd - timedelta(hours=12)).time()
    )
    end_date = st.session_state.get("wc_sync_end_date", now_bd.date())
    end_time = st.session_state.get("wc_sync_end_time", now_bd.time())

    return _apply_cache_buster(
        {
            "per_page": 100,
            "after": f"{start_date}T{start_time.strftime('%H:%M:%S')}",
            "before": f"{end_date}T{end_time.strftime('%H:%M:%S')}",
            "status": "any",
            "orderby": "date",
            "order": "desc",
        },
        cache_buster,
    )


# ── Order merging ────────────────────────────────────────────────────────────


def _merge_deduplicated_orders(main_rows: list, extra_rows: list) -> list:
    """Merge two order lists, deduplicating by unique line item, preferring the latest date_modified / latest status."""
    order_map = {}
    for r in main_rows + extra_rows:
        line_key = (
            r.get("Line Item ID")
            if r.get("Line Item ID") is not None
            else r.get("Line Item Index", 0)
        )
        key = (r.get("Order ID"), r.get("Item Name", ""), r.get("SKU", ""), line_key)
        if key not in order_map:
            order_map[key] = r
        else:
            existing = order_map[key]
            new_mod = str(r.get("Order Date Modified", ""))
            old_mod = str(existing.get("Order Date Modified", ""))
            if new_mod >= old_mod:
                order_map[key] = r

    return list(order_map.values())


# ── Operational partitioning ─────────────────────────────────────────────────


def _is_off_day(d, holiday_list: list[str]) -> bool:
    """Return True if the given date is an off day (Friday or manual holiday)."""
    return d.weekday() == 4 or d.strftime("%Y-%m-%d") in holiday_list


def _prev_working_day_cutoff(
    from_cutoff: datetime, holiday_list: list[str], shift_h: int, shift_m: int
) -> datetime:
    """Walk backwards from `from_cutoff` skipping all consecutive off days.

    Each step goes back one calendar day and skips it if it is a Friday or
    listed in the manual holiday list.  Stops at the first working day.

    Example:
        If today is Saturday and yesterday (Friday) is off, this returns the
        cutoff for the THURSDAY operational shift (i.e., Thursday at shift_h:shift_m).
    """
    candidate = from_cutoff - timedelta(days=1)
    while True:
        # The operational "day" for this cutoff is the calendar date immediately
        # before the cutoff hour (e.g. cutoff Thu 18:00 → operational day = Thu)
        op_date = candidate.date()
        if not _is_off_day(op_date, holiday_list):
            break
        candidate -= timedelta(days=1)
    return candidate


def _compute_cutoff_times(tz_bd):
    """Compute cutoff boundaries for operational cycle partitioning.

    Logic:
        - cutoff_today   : next shift-end boundary (today or tomorrow at shift_h:shift_m)
        - prev_cutoff    : shift-end of the most recent WORKING day before today
        - day_before_prev: shift-end of the working day before prev_cutoff

    Off days (Fridays + manual holidays) are completely skipped so the "previous
    shift" always refers to the last actual operational day, regardless of how
    many consecutive holidays are in between.

    Returns (cutoff_today, prev_cutoff, day_before_prev, shipped_limit).
    """
    now_bd = datetime.now(tz_bd)
    ref_now = now_bd.replace(tzinfo=None)
    shift_h = st.session_state.get("shift_cutoff_hour", 18)
    shift_m = st.session_state.get("shift_cutoff_minute", 0)
    holiday_list = st.session_state.get("operational_holidays", [])

    rollover_h = 8

    # Determine target operational working day:
    # Before 08:00 AM, the active shift belongs to the previous working day.
    # After 08:00 AM (including evening after 18:00), the active shift belongs to today.
    if ref_now.hour < rollover_h:
        target_d = ref_now.date() - timedelta(days=1)
        while _is_off_day(target_d, holiday_list):
            target_d -= timedelta(days=1)
    else:
        target_d = ref_now.date()
        if _is_off_day(target_d, holiday_list):
            while _is_off_day(target_d, holiday_list):
                target_d -= timedelta(days=1)

    cutoff_today = datetime.combine(target_d, time(shift_h, shift_m))
    prev_cutoff = _prev_working_day_cutoff(cutoff_today, holiday_list, shift_h, shift_m)
    day_before_prev = _prev_working_day_cutoff(
        prev_cutoff, holiday_list, shift_h, shift_m
    )

    # Shipped orders remain visible until next day 08:00 AM
    next_rollover = datetime.combine(target_d + timedelta(days=1), time(rollover_h, 0))
    while _is_off_day(next_rollover.date(), holiday_list):
        next_rollover += timedelta(days=1)

    shipped_limit = max(cutoff_today, next_rollover, ref_now + timedelta(hours=1))
    return cutoff_today, prev_cutoff, day_before_prev, shipped_limit


def _apply_shipped_history(df_full):
    if df_full.empty:
        return df_full
    df_full = df_full.copy()
    from src.processing.data_processing import safe_coerce_datetime_naive

    df_full["dt_parsed"] = safe_coerce_datetime_naive(df_full["Order Date"])
    df_full["mod_dt_parsed"] = safe_coerce_datetime_naive(
        df_full["Order Date Modified"]
    )

    import json
    import os

    from src.config.constants import RESOURCES_DIR

    os.makedirs(RESOURCES_DIR, exist_ok=True)
    history_file = os.path.join(RESOURCES_DIR, "shipped_history.json")

    # Use session-state cache to avoid repeated disk reads within the same Streamlit run
    shipped_history = st.session_state.get("_shipped_history_cache")
    if shipped_history is None:
        shipped_history = {}
        if os.path.exists(history_file):
            try:
                with open(history_file, "r") as f:
                    shipped_history = json.load(f)
            except Exception:
                pass

    history_updated = False
    status_lower = df_full["Order Status"].astype(str).str.lower().str.strip()
    is_shipped_mask = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])

    for idx, row in df_full[is_shipped_mask].iterrows():
        oid = str(row.get("Order ID", row.get("Order Number", "")))
        if not oid:
            continue
        actual_mod_dt = row["mod_dt_parsed"]
        if pd.notnull(actual_mod_dt):
            if oid in shipped_history:
                stored_dt = safe_coerce_datetime_naive(
                    pd.Series([shipped_history[oid]])
                ).iloc[0]
                if pd.isnull(stored_dt) or actual_mod_dt > stored_dt:
                    shipped_history[oid] = str(actual_mod_dt)
                    history_updated = True
            else:
                shipped_history[oid] = str(actual_mod_dt)
                history_updated = True
        elif oid in shipped_history:
            stored_dt = safe_coerce_datetime_naive(
                pd.Series([shipped_history[oid]])
            ).iloc[0]
            if pd.notnull(stored_dt):
                df_full.at[idx, "mod_dt_parsed"] = stored_dt

    # If an order's status is NOT in SHIPPED_STATUSES, remove it from shipped_history
    for idx, row in df_full[~is_shipped_mask].iterrows():
        oid = str(row.get("Order ID", row.get("Order Number", "")))
        if oid and oid in shipped_history:
            del shipped_history[oid]
            history_updated = True

    if history_updated:
        # Cache in session state for subsequent calls within the same run
        st.session_state["_shipped_history_cache"] = shipped_history
        try:
            with open(history_file, "w") as f:
                json.dump(shipped_history, f)
        except Exception:
            pass

    return df_full


def _partition_operational_data(df_full):
    """Split a full DataFrame into Today, Prev, and Backlog partitions.

    Returns (df_live, df_prev, df_backlog, slot_label, slot_boundaries).
    slot_boundaries: (curr_slot, prev_slot, backlog_slot).
    """
    df_full = _apply_shipped_history(df_full)

    cutoff_today, prev_cutoff, day_before_prev, shipped_limit = _compute_cutoff_times(
        BD_TZ
    )

    status_lower = df_full["Order Status"].astype(str).str.lower().str.strip()
    is_shipped = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])
    is_processing = status_lower.isin(["processing", "wc-processing", "process"])
    is_hold = status_lower.isin(["on-hold", "wc-on-hold", "hold", "wc-hold"])
    is_waiting = status_lower.isin(["pending", "waiting", "wc-pending", "wc-waiting"])

    modified_recent = df_full["mod_dt_parsed"] >= prev_cutoff
    created_recent = df_full["dt_parsed"] >= prev_cutoff
    df_live = df_full[created_recent | modified_recent | is_processing].copy()
    df_prev = df_full[
        (df_full["mod_dt_parsed"] >= day_before_prev)
        & (df_full["mod_dt_parsed"] < prev_cutoff)
        & is_shipped
    ].copy()

    # Queue is date-independent and includes all unresolved workflow states.
    df_backlog = df_full[is_processing | is_hold | is_waiting].copy()

    slot_label = "Today"

    # curr_slot: from start of today's shift (prev_cutoff) to end of today's shift (cutoff_today)
    # e.g. yesterday 6 PM → today 6 PM (the full operational day window)
    slot_boundaries = {
        "wc_curr_slot": (prev_cutoff, shipped_limit),
        "wc_prev_slot": (day_before_prev, prev_cutoff),
        "wc_backlog_slot": (cutoff_today, cutoff_today + timedelta(days=1)),
    }

    return df_live, df_prev, df_backlog, slot_label, slot_boundaries


def _build_result_payload(df_to_return, slot_label, modified_at, partitions, slots):
    """Build the standard results dictionary returned by load_from_woocommerce."""
    return {
        "df_to_return": df_to_return,
        "sync_desc": (
            f"WooCommerce_{slot_label}_API_{len(df_to_return)}_Orders"
            if not df_to_return.empty
            else "woocommerce_api_empty"
        ),
        "modified_at": modified_at,
        "partitions": partitions,
        "slots": slots,
    }


# ── Main public functions ────────────────────────────────────────────────────


@st.cache_data(show_spinner=False)
def load_from_woocommerce(cache_buster: str | None = None):
    """Loads live data from WooCommerce REST API orders.

    cache_buster: optional unique string appended as a query param (nocache=...)
    so the request bypasses URL-keyed server caches (the store has been observed
    serving stale cached order data intermittently).
    """
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

    try:
        sync_mode = st.session_state.get("wc_sync_mode", "Operational Cycle")

        if sync_mode == "Operational Cycle":
            params = _get_operational_sync_params(cache_buster)
            global_params = _get_global_open_params(cache_buster)
            today_shipped_params = _get_today_modified_shipped_params(cache_buster)

            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=3) as executor:
                f_op = executor.submit(_fetch_wc_batch, endpoint, params, auth)
                f_global = executor.submit(
                    _fetch_wc_batch, endpoint, global_params, auth
                )
                f_shipped = executor.submit(
                    _fetch_wc_batch, endpoint, today_shipped_params, auth
                )

                rows = f_op.result()
                global_rows = f_global.result()
                today_shipped_rows = f_shipped.result()

            rows = _merge_deduplicated_orders(rows, global_rows)
            rows = _merge_deduplicated_orders(rows, today_shipped_rows)
        else:
            params = _get_custom_range_params(cache_buster)
            rows = _fetch_wc_batch(endpoint, params, auth)

        df_full = pd.DataFrame(rows)
        if df_full.empty:
            return _build_result_payload(pd.DataFrame(), "", "N/A", {}, {})

        if sync_mode != "Operational Cycle":
            df_full = _apply_shipped_history(df_full)

        now_str = bd_now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state["live_sync_time"] = bd_now().replace(tzinfo=None)

        if sync_mode == "Operational Cycle":
            df_live, df_prev, df_backlog, slot_label, slots = (
                _partition_operational_data(df_full)
            )
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
        raise RuntimeError(f"Failed to fetch data from WooCommerce: {e}") from e


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
    batches = [order_ids[i : i + 100] for i in range(0, len(order_ids), 100)]
    all_processed = []

    try:
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_batch(batch_ids):
            include_str = ",".join(map(str, batch_ids))
            params = {
                "include": include_str,
                "_fields": "id,number,date_created,date_modified,status,billing,shipping,payment_method_title,line_items,total,meta_data",
                "per_page": 100,
            }

            res = request_with_backoff(
                "GET", endpoint, params=params, auth=auth, timeout=15
            )
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


# Threshold (minutes): if the newest order modification in a sync is older than
# this, the response is treated as possibly stale (cached) and retried once.
WC_STALE_MAX_AGE_MIN = 45


def _apply_cache_buster(params: dict, cache_buster: str | None) -> dict:
    """Append a unique query param so the request bypasses URL-keyed server caches."""
    if cache_buster:
        params["nocache"] = cache_buster
    return params


def _staleness_info(df):
    """Return (newest_mod, age_min) for the data, or (None, None) if unknown.

    mod_dt_parsed (when present) is BD-local naive; the raw 'Order Date Modified'
    column holds UTC/GMT values, so shift it +6h before comparing.
    """
    if df is None or df.empty:
        return None, None
    mod_col = (
        "mod_dt_parsed"
        if "mod_dt_parsed" in df.columns
        else "Order Date Modified"
        if "Order Date Modified" in df.columns
        else None
    )
    if not mod_col:
        return None, None
    mods = pd.to_datetime(
        df[mod_col].astype(str).str.replace("Z", "", regex=False), errors="coerce"
    )
    if "mod_dt_parsed" not in df.columns:
        # Raw column is UTC/GMT — convert to BD local for comparison.
        mods = mods + pd.Timedelta(hours=6)
    newest = mods.max()
    if pd.isnull(newest):
        return None, None
    now_bd = bd_now().replace(tzinfo=None)
    return newest, (now_bd - newest).total_seconds() / 60


def _data_looks_stale(df, max_age_min: float = WC_STALE_MAX_AGE_MIN) -> bool:
    """Heuristic staleness check: newest order modification is much older than now."""
    _, age_min = _staleness_info(df)
    return age_min is not None and age_min > max_age_min


def _response_regressed(df) -> bool:
    """Detect an older API snapshot without treating a quiet store as stale."""
    newest, _ = _staleness_info(df)
    if newest is None:
        return False

    previous = st.session_state.get("_wc_latest_mod_seen")
    if previous is None or newest >= previous:
        st.session_state["_wc_latest_mod_seen"] = newest
        return False
    return True


def _should_autorefresh() -> bool:
    """Check if the refresh interval has elapsed since last sync."""
    if st.session_state.get("_needs_background_sync"):
        return True
    interval = st.session_state.get("wc_refresh_interval", 30)
    if interval <= 0:
        return False  # Manual mode
    last_sync = st.session_state.get("live_sync_time")
    if last_sync is None:
        return True
    elapsed = (bd_now().replace(tzinfo=None) - last_sync).total_seconds()
    return elapsed >= interval


def load_live_source(force_refresh=False):
    """Stateless fetch with stateful session update and offline snapshot fallback.

    Every sync triggers the WooCommerce REST API with a unique cache-buster
    query param, so Cloudflare's URL-keyed cache is bypassed and the API
    returns the latest events (new orders, status changes, shipments). Within
    the refresh interval, the last fetched data is reused without an extra
    REST call — and never via an un-busted URL that could be served stale.
    """
    # Cold-start instant bootstrap: if not force_refresh and no cached operational data in session state,
    # load local sales snapshot immediately so UI renders in <0.3s without waiting for network.
    if not force_refresh and st.session_state.get("wc_curr_df") is None:
        try:
            from src.utils.snapshots import load_sales_snapshot

            df_snap = load_sales_snapshot()
            if df_snap is not None and not df_snap.empty:
                df_live, df_prev, df_backlog, slot_label, slots = (
                    _partition_operational_data(df_snap)
                )
                st.session_state["wc_curr_df"] = scrub_raw_dataframe(df_live)
                st.session_state["wc_prev_df"] = scrub_raw_dataframe(df_prev)
                st.session_state["wc_backlog_df"] = scrub_raw_dataframe(df_backlog)
                for key, val in slots.items():
                    if val is not None:
                        st.session_state[key] = val
                st.session_state["wc_full_df"] = df_snap
                desc = f"Instant_Snapshot_{len(df_snap)}_Orders"
                st.session_state["_wc_last_sync_desc"] = desc
                st.session_state["_wc_last_modified_at"] = "Loaded from snapshot"
                st.session_state["_needs_background_sync"] = True
                df_to_return = df_backlog if slot_label == "Backlog" else df_live
                return scrub_raw_dataframe(df_to_return), desc, "Loaded from snapshot"
        except Exception as snap_err:
            log_system_event("WC_COLD_START_SNAPSHOT_ERROR", str(snap_err))

    should_fetch = force_refresh or _should_autorefresh()
    if should_fetch:
        load_from_woocommerce.clear()

    results = None
    if should_fetch:
        try:
            # Unique cache-buster per sync → the REST API always answers from origin.
            results = load_from_woocommerce(
                cache_buster=str(int(bd_now().timestamp() * 1000))
            )
        except Exception as api_err:
            log_system_event(
                "WC_API_DOWN_ERROR", f"WooCommerce REST API failed: {api_err}"
            )
            results = None
        # Unique-keyed entries would accumulate in st.cache_data — drop them.
        load_from_woocommerce.clear()

        # Retry only when the API moves backwards relative to data already seen.
        # Order inactivity is normal and must not trigger a second full fetch.
        if (
            results
            and isinstance(results, dict)
            and _response_regressed(results.get("df_to_return"))
        ):
            newest, age_min = _staleness_info(results.get("df_to_return"))
            log_system_event(
                "WC_STALE_DATA",
                (
                    f"newest_mod={newest} age_min={age_min:.0f}"
                    if newest is not None
                    else "stale-detected"
                ),
            )
            try:
                retried = load_from_woocommerce(
                    cache_buster=str(int(bd_now().timestamp() * 1000))
                )
                load_from_woocommerce.clear()
                if (
                    retried
                    and isinstance(retried, dict)
                    and not _response_regressed(retried.get("df_to_return"))
                ):
                    results = retried
                    log_system_event(
                        "WC_STALE_RETRY_RECOVERED", "cache-buster returned fresh data"
                    )
                else:
                    log_system_event(
                        "WC_STALE_RETRY_UNRESOLVED",
                        "data still stale after cache-buster retry",
                    )
            except Exception as retry_err:
                log_system_event("WC_STALE_RETRY_FAILED", str(retry_err))
    else:
        # Within the refresh interval: reuse the last fetched data without
        # another REST call (an un-busted URL could be served stale by Cloudflare).
        df_cached = st.session_state.get("wc_full_df")
        if df_cached is not None and not df_cached.empty:
            results = {
                "df_to_return": df_cached,
                "sync_desc": st.session_state.get(
                    "_wc_last_sync_desc", f"WooCommerce_cached_{len(df_cached)}_Orders"
                ),
                "modified_at": st.session_state.get("_wc_last_modified_at", ""),
            }

    if results and isinstance(results, dict):
        df_new = results.get("df_to_return")

        # ── New-Order Detection: compare Order IDs vs last sync ──────────────
        new_order_count = 0
        if df_new is not None and not df_new.empty:
            id_col = next(
                (
                    c
                    for c in ["Order ID", "order_id", "ID", "id"]
                    if c in df_new.columns
                ),
                None,
            )
            if id_col:
                current_ids = set(df_new[id_col].dropna().astype(str).unique())
                prev_ids = st.session_state.get("wc_last_order_ids", set())
                new_ids = current_ids - prev_ids
                new_order_count = len(new_ids)
                st.session_state["wc_last_order_ids"] = current_ids
                if (
                    new_order_count > 0 and prev_ids
                ):  # only notify on subsequent syncs, not first load
                    st.session_state["wc_new_order_count"] = new_order_count
                else:
                    st.session_state["wc_new_order_count"] = 0

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
        st.session_state["live_sync_time"] = bd_now().replace(tzinfo=None)
        if should_fetch:
            st.session_state.pop("_needs_background_sync", None)

        # 4. Update Full Context for Forecasting
        st.session_state["wc_full_df"] = df_new
        st.session_state["_wc_last_sync_desc"] = results.get("sync_desc", "")
        st.session_state["_wc_last_modified_at"] = results.get("modified_at", "")

        # 5. Silent Autosave for Offline Mode Fallback (only on fresh network fetch)
        if should_fetch:
            try:
                from src.utils.snapshots import save_sales_snapshot

                if df_new is not None and not df_new.empty:
                    save_sales_snapshot(df_new)
            except Exception:
                pass

        # 6. Return tuple for legacy unpacking
        return df_new, results["sync_desc"], results["modified_at"]

    # Handle legacy return if any
    if results:
        st.session_state["live_sync_time"] = bd_now().replace(tzinfo=None)
        return results

    # Automatic Fallback: Load last saved snapshot when API is not working
    from src.utils.snapshots import load_sales_snapshot

    df_snap = load_sales_snapshot()
    if df_snap is not None and not df_snap.empty:
        df_live, df_prev, df_backlog, slot_label, slots = _partition_operational_data(
            df_snap
        )
        st.session_state["wc_curr_df"] = scrub_raw_dataframe(df_live)
        st.session_state["wc_prev_df"] = scrub_raw_dataframe(df_prev)
        st.session_state["wc_backlog_df"] = scrub_raw_dataframe(df_backlog)
        for key, val in slots.items():
            if val is not None:
                st.session_state[key] = val
        st.session_state["live_sync_time"] = bd_now().replace(tzinfo=None)
        st.session_state["wc_full_df"] = df_snap
        df_to_return = df_backlog if slot_label == "Backlog" else df_live
        return (
            scrub_raw_dataframe(df_to_return),
            "LOCAL_SNAPSHOT_FALLBACK",
            "API_OFFLINE",
        )

    raise ValueError(
        "WooCommerce REST API is offline and no local saved snapshot is available."
    )
