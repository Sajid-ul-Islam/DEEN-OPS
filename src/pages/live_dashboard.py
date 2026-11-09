# Live Operational Dashboard - Refactored for Hick's Law Compliance
"""
Phase 2 Refactoring: Breaking down render_live_tab() into focused components.
Follows Hick's Law principles:
1. Single Primary Action per screen
2. Visual Hierarchy with button types
3. Progressive Disclosure for advanced options
4. Contextual Relevance
"""

import pandas as pd
import streamlit as st

from src.components.dashboard.courier_telemetry_card import (
    render_courier_telemetry_card,
)
from src.components.dashboard.dispatch_export_view import (
    render_dispatch_export,
)
from src.components.dashboard.dashboard_metrics import render_operational_metrics
from src.components.dashboard.dashboard_output import render_dashboard_output
from src.components.dashboard.live_components import (
    render_dashboard_banner,
)
from src.components.dashboard.orders_ledger_view import (
    render_orders_ledger_view,
)
from src.components.dashboard.timeline_7d_bar import (
    render_timeline_7d_bar,
)
from src.components.ui.widgets import render_reset_confirm

from src.config.constants import bd_now, bd_today
from src.processing.column_detection import find_columns
from src.processing.completed_analytics import filter_online_orders
from src.processing.data_processing import (
    aggregate_data,
    apply_order_view_comparison,
    filter_live_dashboard_view,
    get_previous_working_day,
    prepare_granular_data,
)
from src.services.woocommerce.client import load_live_source
from src.utils.logging import log_system_event
from src.utils.safe_ops import safe_render


def _get_dashboard_source(fallback=None, online_only: bool = True):
    """Combine dashboard partitions so view rules operate on one source.

    By default, restricts data to online website checkout orders (excluding outlet/POS).
    Supports manual upload override if user uploaded custom data.
    """
    manual = st.session_state.get("live_manual_override_df")
    if manual is not None and not manual.empty:
        if online_only:
            return filter_online_orders(manual)
        return manual

    frames = [
        frame
        for frame in (
            st.session_state.get("wc_curr_df"),
            st.session_state.get("wc_prev_df"),
            st.session_state.get("wc_backlog_df"),
            st.session_state.get("wc_full_df"),
        )
        if frame is not None and not frame.empty
    ]
    if not frames:
        res = fallback
    else:
        combined = pd.concat(frames, ignore_index=True)
        try:
            res = combined.drop_duplicates()
        except TypeError:
            subset = [
                c
                for c in ["Order ID", "Line Item ID", "Line Item Index", "Product Name"]
                if c in combined.columns
            ]
            res = combined.drop_duplicates(subset=subset) if subset else combined

    if res is not None and not res.empty:
        from src.processing.data_processing import safe_coerce_datetime_naive

        if "mod_dt_parsed" not in res.columns or res["mod_dt_parsed"].isna().all():
            comp_col = next(
                (c for c in ["date_completed", "Date Completed"] if c in res.columns),
                None,
            )
            if comp_col:
                res["mod_dt_parsed"] = safe_coerce_datetime_naive(res[comp_col])
            elif "Order Date Modified" in res.columns:
                res["mod_dt_parsed"] = safe_coerce_datetime_naive(
                    res["Order Date Modified"]
                )
        if "dt_parsed" not in res.columns or res["dt_parsed"].isna().all():
            if "Order Date" in res.columns:
                res["dt_parsed"] = safe_coerce_datetime_naive(res["Order Date"])

    if res is not None and not res.empty and online_only:
        return filter_online_orders(res)
    return res


def _get_comparison_frame(
    selected_view: str,
    nav_mode: str,
    order_view_mode: str,
    live_mapping: dict | None = None,
):
    """Retrieve and prepare the comparison DataFrame for KPI delta and badge rendering."""
    if selected_view == "Queue":
        return None

    _dash_src = _get_dashboard_source()
    _cmp_f = None

    if selected_view in {"Today Shipped", "Today"}:
        _cmp_f = filter_live_dashboard_view(_dash_src, "Last Day Shipped")
        if _cmp_f is None or _cmp_f.empty:
            _cmp_raw = st.session_state.get("wc_prev_df")
            if _cmp_raw is None or _cmp_raw.empty:
                _cmp_raw = st.session_state.get("wc_full_df")
            if _cmp_raw is not None and not _cmp_raw.empty:
                _cmp_raw = filter_online_orders(_cmp_raw)
                _cmp_f = filter_live_dashboard_view(_cmp_raw, "Last Day Shipped")
    elif selected_view == "All Orders":
        # Always resolve full_raw up front so later references never raise NameError
        full_raw = st.session_state.get("wc_full_df")
        # First try to get previous day's data from dashboard source using date-based filtering
        if _dash_src is not None and not _dash_src.empty:
            prev_work_d = get_previous_working_day(bd_today())
            _cmp_f = filter_live_dashboard_view(
                _dash_src, "All Orders", reference_date=prev_work_d
            )
        # Fallback: use wc_prev_df from session state
        if _cmp_f is None or _cmp_f.empty:
            _cmp_raw = st.session_state.get("wc_prev_df")
            if _cmp_raw is None or _cmp_raw.empty:
                if full_raw is not None and not full_raw.empty:
                    try:
                        from src.services.woocommerce.client import (
                            _partition_operational_data,
                        )

                        _, df_prev_ext, _, _, _ = _partition_operational_data(full_raw)
                        _cmp_raw = df_prev_ext
                    except Exception:
                        pass
            # If still no comparison frame, apply date-based filtering directly to wc_full_df
            if (
                (_cmp_raw is None or _cmp_raw.empty)
                and full_raw is not None
                and not full_raw.empty
            ):
                prev_work_d = get_previous_working_day(bd_today())
                _cmp_f = filter_live_dashboard_view(
                    full_raw, "All Orders", reference_date=prev_work_d
                )
            elif _cmp_raw is not None and not _cmp_raw.empty:
                _cmp_raw = filter_online_orders(_cmp_raw)
                # For All Orders comparison, pass nav_mode="Prev" to include all non-cancelled orders
                # from the previous period, not just processing orders within today's slot
                _cmp_f = apply_order_view_comparison(_cmp_raw, "Prev", order_view_mode)
    elif selected_view in {"Last Day Shipped", "Last Day"}:
        _cmp_f = filter_live_dashboard_view(_dash_src, "Today Shipped")
        if _cmp_f is None or _cmp_f.empty:
            _cmp_raw = st.session_state.get("wc_curr_df")
            if _cmp_raw is not None and not _cmp_raw.empty:
                _cmp_raw = filter_online_orders(_cmp_raw)
                _cmp_f = filter_live_dashboard_view(_cmp_raw, "Today Shipped")
    else:
        _cmp_raw = (
            st.session_state.get("wc_prev_df")
            if nav_mode == "Today"
            else st.session_state.get("wc_curr_df")
            if nav_mode in ["Backlog", "Prev"]
            else None
        )
        if _cmp_raw is not None and not _cmp_raw.empty:
            _cmp_raw = filter_online_orders(_cmp_raw)
            _cmp_f = apply_order_view_comparison(_cmp_raw, nav_mode, order_view_mode)

    if _cmp_f is not None and not _cmp_f.empty:
        mapping = find_columns(_cmp_f) or live_mapping or {}
        _cmp_standard, _ = prepare_granular_data(_cmp_f, mapping)
        return _cmp_standard
    return None


# KPI cards are rendered once per page run. The data-sync fragment triggers a
# page rerun only when the underlying order fingerprint changes.
def _refresh_core_metrics():
    """Render KPI cards from the latest synchronized dashboard frames.

    Reuses the already-filtered, granular ``live_df_standard`` /
    ``live_cmp_standard`` stashed by ``render_live_tab`` so the cards always
    show the exact same data as the charts beneath them (no second, divergent
    filtering pass). Falls back to recomputing only when the stash is missing.
    """
    nav_mode = st.session_state.get("wc_nav_mode", "Today")
    selected_view = st.session_state.get("live_dashboard_view", "All Orders")
    order_view_mode = st.session_state.get("live_order_filter", "All Orders")

    m_df = st.session_state.get("live_df_standard")
    c_df = st.session_state.get("live_cmp_standard")

    if m_df is None:
        # Fallback: nothing stashed yet (e.g. very first render before the
        # main pipeline ran) — recompute from session state via the shared helper.
        raw = _get_dashboard_source()
        if raw is None or raw.empty:
            st.caption("⏳ Waiting for data...")
            return
        m_df = filter_live_dashboard_view(raw, selected_view)
        if m_df is None:
            m_df = pd.DataFrame()
        m_df, _ = prepare_granular_data(
            m_df, find_columns(m_df) if not m_df.empty else {}
        )

    if selected_view == "Queue":
        c_df = None
    elif c_df is None:
        c_df = _get_comparison_frame(selected_view, nav_mode, order_view_mode)

    dummy_mapping = {
        "name": "Product Name",
        "cost": "Item Cost",
        "qty": "Quantity",
        "date": "Date",
        "order_id": "Order ID",
        "phone": "Phone",
        "sku": "SKU",
    }
    wc_raw_mapping = {
        "name": "Item Name",
        "cost": "Item Cost",
        "qty": "Quantity",
        "date": "Order Date",
        "order_id": "Order ID",
        "phone": "Phone (Billing)",
        "sku": "SKU",
    }

    render_operational_metrics(
        m_df,
        c_df,
        nav_mode,
        dummy_mapping,
        wc_raw_mapping,
    )


# ── Staleness Monitor ────────────────────────────────────────────────────────
# Graphs how often the store's REST API serves cached/older order data by
# charting WC_STALE_DATA detection events (and their retry outcomes) from
# data/feedback/system_logs.json over time.

STALE_EVENT_TYPES = frozenset(
    {
        "WC_STALE_DATA",
        "WC_STALE_RETRY",  # legacy detection event (pre-cache-buster naming)
        "WC_STALE_RETRY_RECOVERED",
        "WC_STALE_RETRY_UNRESOLVED",
        "WC_STALE_RETRY_FAILED",
        "WC_STALE_RENDER",
    }
)


def _load_stale_events():
    """Load staleness events from the system log file into a DataFrame."""
    import json
    import os

    import pandas as pd

    from src.config.constants import FEEDBACK_DIR

    empty_df = pd.DataFrame(columns=["ts", "type", "details"])
    log_path = os.path.join(FEEDBACK_DIR, "system_logs.json")
    if not os.path.exists(log_path):
        return empty_df
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            logs = json.load(f)
        if not isinstance(logs, list):
            return empty_df
    except Exception:
        return empty_df

    rows = [
        {
            "ts": entry.get("timestamp", ""),
            "type": entry.get("type", ""),
            "details": str(entry.get("details", "")),
        }
        for entry in logs
        if isinstance(entry, dict) and entry.get("type") in STALE_EVENT_TYPES
    ]
    if not rows:
        return empty_df

    df = pd.DataFrame(rows)
    from src.processing.data_processing import safe_coerce_datetime_naive

    if "ts" in df.columns:
        df["ts"] = safe_coerce_datetime_naive(df["ts"])
        return df.dropna(subset=["ts"])
    return empty_df


def render_staleness_monitor():
    """Diagnostic panel: how often WooCommerce serves stale order data over time."""
    import pandas as pd
    import plotly.express as px

    df = _load_stale_events()
    # Promoted from a collapsed expander: staleness is the app's primary defense
    # against silently bad WooCommerce data, so it renders as a first-class
    # section with a compact summary header.
    recent = (
        df[df["ts"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=1)]
        if not df.empty
        else df
    )
    stale_24h = (
        int(recent[recent["type"].isin(["WC_STALE_DATA", "WC_STALE_RETRY"])].shape[0])
        if not recent.empty
        else 0
    )

    st.markdown("#### 🩺 Data Staleness Monitor")
    if stale_24h > 0:
        st.warning(
            f"⚠️ **{stale_24h} stale sync(es) in the last 24h** — order data may have been served "
            "from cache. Check the site's cache/CDN."
        )
    else:
        st.caption("✅ No stale syncs in the last 24 hours.")
    with st.expander("Staleness details & history", expanded=stale_24h > 0):
        st.caption(
            "Tracks when the store's REST API serves cached/stale order data — syncs whose newest order "
            "modification was older than 45 minutes at fetch time. Clear the site's cache/CDN to stop "
            "these windows."
        )
        if df.empty:
            st.info(
                "No staleness events recorded yet. Events appear automatically when a sync returns stale "
                "data (see the 'Possibly stale WooCommerce data' banner)."
            )
            return

        now = pd.Timestamp.now().normalize()
        last7 = df[df["ts"] >= now - pd.Timedelta(days=6)]
        detections = last7[last7["type"].isin(["WC_STALE_DATA", "WC_STALE_RETRY"])]
        recovered = last7[last7["type"] == "WC_STALE_RETRY_RECOVERED"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Stale syncs (7d)", len(detections))
        c2.metric("Recovered via retry (7d)", len(recovered))
        c3.metric(
            "Recovery rate (7d)",
            (
                f"{100 * len(recovered) / len(detections):.0f}%"
                if len(detections)
                else "—"
            ),
        )

        last14 = df[df["ts"] >= now - pd.Timedelta(days=13)]
        detect14 = last14[
            last14["type"].isin(["WC_STALE_DATA", "WC_STALE_RETRY"])
        ].copy()
        if not detect14.empty:
            detect14["date"] = detect14["ts"].dt.date
            daily = detect14.groupby("date").size().reset_index(name="Stale syncs")
            fig = px.bar(
                daily,
                x="date",
                y="Stale syncs",
                title="Stale-data detections per day (last 14 days)",
                labels={"date": "Date", "Stale syncs": "Syncs"},
            )
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )

        outcomes = last14[
            last14["type"].isin(
                [
                    "WC_STALE_RETRY_RECOVERED",
                    "WC_STALE_RETRY_UNRESOLVED",
                    "WC_STALE_RETRY_FAILED",
                ]
            )
        ].copy()
        if not outcomes.empty:
            outcomes["date"] = outcomes["ts"].dt.date
            outcomes["Outcome"] = outcomes["type"].map(
                {
                    "WC_STALE_RETRY_RECOVERED": "Recovered (cache-buster)",
                    "WC_STALE_RETRY_UNRESOLVED": "Still stale",
                    "WC_STALE_RETRY_FAILED": "Retry failed",
                }
            )
            out_daily = (
                outcomes.groupby(["date", "Outcome"]).size().reset_index(name="Count")
            )
            fig2 = px.bar(
                out_daily,
                x="date",
                y="Count",
                color="Outcome",
                title="Retry outcomes per day (last 14 days)",
                labels={"date": "Date", "Count": "Events"},
                barmode="stack",
            )
            fig2.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(
                fig2, use_container_width=True, config={"displayModeBar": False}
            )

        st.caption(
            f"Latest event: {df.iloc[-1]['ts']:%Y-%m-%d %H:%M} · {df.iloc[-1]['type']}"
        )


def _render_order_pipeline_summary(df):
    """Show the non-cancelled workload without mixing it into sales KPIs."""
    if df is None or df.empty:
        return

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if status_col is None:
        return

    order_col = "Order ID" if "Order ID" in df.columns else None
    statuses = df[status_col].astype(str).str.lower().str.strip()

    def count_orders(mask):
        subset = df[mask]
        return int(subset[order_col].nunique()) if order_col else len(subset)

    sales_mask = statuses.isin({"shipped", "completed", "wc-shipped", "wc-completed"})
    # Exclude exchange orders from sales count - they are replacements, not new sales
    # Detect exchange from status OR from fee notes containing "Exchange credit"
    exchange_status_mask = statuses.str.contains("exchange", na=False)
    fee_notes_col = "Fee Notes" if "Fee Notes" in df.columns else None
    exchange_fee_mask = pd.Series(False, index=df.index)
    if fee_notes_col:
        exchange_fee_mask = (
            df[fee_notes_col]
            .astype(str)
            .str.lower()
            .str.contains("exchange credit", na=False)
        )
    exchange_mask = exchange_status_mask | exchange_fee_mask
    sales_mask = sales_mask & ~exchange_mask
    processing_mask = statuses.isin({"processing", "process", "wc-processing"})
    held_mask = statuses.isin(
        {
            "on-hold",
            "hold",
            "pending",
            "waiting",
            "wc-on-hold",
            "wc-hold",
            "wc-pending",
            "wc-waiting",
        }
    )
    other_mask = ~(sales_mask | processing_mask | held_mask | exchange_mask)

    exchange_count = count_orders(exchange_mask)
    summary_parts = [
        f"🚚 Actual sales **{count_orders(sales_mask)}**",
        f"🔄 Exchange **{exchange_count}**",
    ]
    held_count = count_orders(held_mask)
    if held_count > 0:
        summary_parts.append(f"⏸ Hold / waiting **{held_count}**")
    other_count = count_orders(other_mask)
    if other_count > 0:
        summary_parts.append(f"Other **{other_count}**")

    st.caption("Operational workload · " + " · ".join(summary_parts))

    with st.expander("View operational orders", expanded=False):
        visible_columns = [
            column
            for column in (
                "Order ID",
                status_col,
                "Full Name (Billing)",
                "Order Date",
                "Order Date Modified",
                "Order Total Amount",
            )
            if column in df.columns
        ]
        workload = df[visible_columns]
        if order_col and order_col in workload.columns:
            workload = workload.drop_duplicates(subset=[order_col])
        st.dataframe(workload, width="stretch", hide_index=True)


def render_live_tab():
    def _reset_live_state():
        st.session_state.wc_curr_df = None
        st.session_state.wc_prev_df = None
        st.session_state.live_sync_time = None
        st.session_state.wc_view_historical = False
        st.session_state.wc_sync_mode = "Operational Cycle"
        st.session_state.live_dashboard_view = "All Orders"
        st.session_state.wc_nav_mode = "Today"
        st.session_state.live_order_filter = "All Orders"
        st.session_state.live_cmp_standard = None

    render_reset_confirm("Live Dashboard", "live", _reset_live_state)
    st.session_state.manual_tab_active = False

    if "live_dashboard_view" not in st.session_state:
        st.session_state.live_dashboard_view = "All Orders"

    view_state = {
        "All Orders": ("Today", "All Orders"),
        "Today Shipped": ("Today", "Shipped"),
        "Last Day Shipped": ("Prev", "Shipped"),
        "Queue": ("Backlog", "Queue"),
        # Backward-compatible aliases:
        "Today": ("Today", "Shipped"),
        "Last Day": ("Prev", "Shipped"),
    }
    selected_view = st.session_state.get("live_dashboard_view", "All Orders")
    nav_state, order_state = view_state.get(selected_view, view_state["All Orders"])
    st.session_state.wc_nav_mode = nav_state
    st.session_state.live_order_filter = order_state
    today = bd_today()
    st.session_state["live_custom_range"] = (today, today)

    if "wc_nav_mode" not in st.session_state:
        st.session_state.wc_nav_mode = "Today"

    if "live_order_filter" not in st.session_state:
        st.session_state.live_order_filter = "Shipped"

    # Force Operational Cycle in live dashboard
    st.session_state["wc_sync_mode"] = "Operational Cycle"

    # Initialize session state for controls if they don't exist
    if "perf_outlook_view" not in st.session_state:
        st.session_state.perf_outlook_view = "Sub-Category"

    # ── Data Loading & Preparation (Moved to top for early access) ───────────
    try:
        live_res = load_live_source()
        if isinstance(live_res, dict):
            df_live = live_res.get("df_to_return")
            source_name = live_res.get("sync_desc", "WooCommerce_API")
            modified_at = live_res.get("modified_at", "")
        elif isinstance(live_res, (list, tuple)) and len(live_res) == 3:
            df_live, source_name, modified_at = live_res
        else:
            df_live = live_res
            source_name = "WooCommerce_API"
            modified_at = ""

        if source_name == "LOCAL_SNAPSHOT_FALLBACK" or modified_at == "API_OFFLINE":
            st.warning(
                "⚠️ **WooCommerce REST API is currently offline or not responding.** Displaying the last saved sales snapshot. Live updates will resume once connection is restored."
            )

        # ── Stale Data Warning ──────────────────────────────────────────────
        # The store's REST API has been observed serving cached/older order data
        # intermittently (the same query returns different states minutes apart).
        # When the newest order modification in a live sync is much older than
        # now, the dashboard is likely showing a stale snapshot — e.g. missing
        # today's shipped orders — so surface it instead of silently hiding data.
        try:
            import pandas as _pd

            mod_col = None
            if df_live is not None and not df_live.empty:
                if "mod_dt_parsed" in df_live.columns:
                    mod_col = "mod_dt_parsed"
                elif "Order Date Modified" in df_live.columns:
                    mod_col = "Order Date Modified"

            if df_live is not None and not df_live.empty and mod_col:
                mods = _pd.to_datetime(
                    df_live[mod_col].astype(str).str.replace("Z", "", regex=False),
                    errors="coerce",
                )
                newest = mods.max()
                if _pd.notnull(newest):
                    now_bd = bd_now().replace(tzinfo=None)
                    age_min = (now_bd - newest).total_seconds() / 60
                    # Only alert during active daytime business hours (> 120m without any order modification)
                    if age_min > 120 and 11 <= now_bd.hour <= 22:
                        st.info(
                            f"ℹ️ **WooCommerce REST API Active:** Last store modification was at **{newest:%Y-%m-%d %H:%M}** ({age_min:.0f} min ago)."
                        )
                        log_system_event(
                            "WC_MOD_INFO",
                            f"newest_mod={newest} age_min={age_min:.0f}",
                        )
        except Exception:
            pass

        # ── New Order Notification Toast ──────────────────────────────────────
        new_cnt = st.session_state.pop("wc_new_order_count", 0)
        if new_cnt > 0:
            tot_today = (
                len(df_live["Order ID"].unique())
                if df_live is not None and "Order ID" in df_live.columns
                else (len(df_live) if df_live is not None else 0)
            )
            st.toast(
                f"⚡ **{new_cnt} new WooCommerce order{'s' if new_cnt > 1 else ''} synced** from REST API (Total: {tot_today} orders)",
                icon="🔔",
            )
    except Exception as api_err:
        log_system_event(
            "LIVE_API_ERROR", f"Live sync failed, attempting fallback: {api_err}"
        )
        from src.utils.snapshots import load_sales_snapshot

        df_snap = load_sales_snapshot()

        if df_snap is not None and not df_snap.empty:
            st.warning(
                "⚠️ **WooCommerce REST API is currently offline or not responding.** Displaying the last saved sales snapshot. Live updates will resume once connection is restored."
            )
            df_live = df_snap
            source_name = "LOCAL_SNAPSHOT_FALLBACK"
            modified_at = "OFFLINE_MODE"
            st.session_state.wc_nav_mode = "Offline"
        else:
            log_system_event("LIVE_FILE_ERROR", str(api_err))
            err_str = str(api_err).lower()
            if any(
                kw in err_str
                for kw in ["connection", "timeout", "502", "503", "500", "resolve"]
            ):
                st.error(
                    "🌐 **Connection Error:** Cannot reach WooCommerce. Check your network or server status."
                )
            else:
                st.error(f"⚠️ **Sync Error:** {api_err}")
            st.info(
                "💡 Use **Sales Data Ingestion** to upload a local CSV/Excel export as a fallback."
            )
            return

    # ── Multi-Mode Shift Navigation & Filtering ───────────────────────────────
    nav_mode = st.session_state.get("wc_nav_mode", "Today")
    if nav_mode == "Offline":
        pass
    elif nav_mode == "Prev" and "wc_prev_df" in st.session_state:
        df_live = st.session_state.wc_prev_df
    elif nav_mode == "Backlog" and "wc_backlog_df" in st.session_state:
        df_live = st.session_state.wc_backlog_df
    elif nav_mode == "Today" and "wc_curr_df" in st.session_state:
        df_live = st.session_state.wc_curr_df

    # ── Header: Refactored with Hick's Law Compliance ───────────────────────
    # Single responsibility: delegate to component module
    render_dashboard_banner(load_live_source)

    st.markdown("---")

    # ── 7-Day Rolling Dispatch Timeline Bar ────────────────────────────────
    full_timeline_src = st.session_state.get("wc_full_df")
    if full_timeline_src is None or full_timeline_src.empty:
        full_timeline_src = _get_dashboard_source(online_only=False)
    if full_timeline_src is not None and not full_timeline_src.empty:
        safe_render(
            lambda: render_timeline_7d_bar(full_timeline_src),
            fallback_msg="7-day dispatch timeline unavailable.",
        )

    selected_view = st.session_state.get("live_dashboard_view", "All Orders")
    nav_mode, order_view_mode = view_state.get(selected_view, view_state["All Orders"])
    df_live = _get_dashboard_source(fallback=df_live)

    # For shipped views, ensure ONLY online checkout orders are shown (exclude outlet/POS)
    if selected_view in {"Today Shipped", "Today", "Last Day Shipped", "Last Day"}:
        if df_live is not None and not df_live.empty:
            from src.processing.completed_analytics import filter_online_orders

            df_live = filter_online_orders(df_live)

    df_live = filter_live_dashboard_view(df_live, selected_view)
    if df_live is None:
        df_live = pd.DataFrame()

    # ── Column Detection ──────────────────────────────────────────────────────
    auto_cols = find_columns(df_live) if not df_live.empty else {}
    live_mapping = {
        "name": auto_cols.get("name", "Product Name"),
        "cost": auto_cols.get("cost", "Item Cost"),
        "qty": auto_cols.get("qty", "Quantity"),
        "date": auto_cols.get("date", "Order Date"),
        "order_id": auto_cols.get("order_id", "Order ID"),
        "phone": auto_cols.get("phone", "Phone"),
        "sku": auto_cols.get("sku", "SKU"),
    }
    # Standardize data for current view
    df_standard, timeframe = prepare_granular_data(df_live, live_mapping)
    cmp_standard = _get_comparison_frame(
        selected_view, nav_mode, order_view_mode, live_mapping
    )

    # Stash the granular frames so the KPI cards and downstream charts share
    # the exact same synchronized dataset.
    st.session_state["live_df_standard"] = df_standard
    st.session_state["live_cmp_standard"] = cmp_standard
    st.session_state["live_df_unfiltered"] = df_standard

    # ── KPI Cards (5 core metric cards + comparison deltas) ────────────────────
    safe_render(
        _refresh_core_metrics, fallback_msg="Operational KPI Metrics unavailable."
    )

    # ── Courier Logistics Telemetry & Discrepancy Auditing ───────────────────
    safe_render(
        lambda: render_courier_telemetry_card(
            df_live if not df_live.empty else df_standard
        ),
        fallback_msg="Courier telemetry unavailable.",
    )

    # ── Detail & Performance Charts ─────────────────────────────────────────
    # Single source of truth: the full standardized dataset (collection filter
    # removed — All Products is the only collection). No filtering needed.
    df_filtered = df_standard
    chosen_col = "🌐 All Products"

    if df_filtered.empty:
        if selected_view in {"Today Shipped", "Today"}:
            st.info(
                f"🚚 **No {chosen_col} orders shipped yet today.** Today's dispatches will appear here once fulfilled."
            )
        elif selected_view in {"Last Day Shipped", "Last Day"}:
            st.info(
                f"🕘 **No {chosen_col} shipped orders recorded** for the previous calendar day."
            )
        elif selected_view == "Queue":
            st.info(
                f"📋 **Queue is clear.** There are currently no {chosen_col} orders on hold or waiting."
            )
        else:
            st.info(
                f"📦 **No active {chosen_col} orders found** for the **{selected_view}** view."
            )
        render_staleness_monitor()
        return

    drill, summ, top, basket = aggregate_data(df_filtered, live_mapping)
    if drill is None or summ is None:
        st.info(
            "ℹ️ Insufficient category data available to display charts for this view."
        )
        render_staleness_monitor()
        return

    # ── Unified Dashboard Output (Performance views, charts, tables, briefing) ───
    safe_render(
        lambda: render_dashboard_output(
            drill,
            summ,
            top,
            str(timeframe) if timeframe is not None else None,
            basket,
            str(source_name) if source_name is not None else None,
            str(modified_at) if modified_at is not None else None,
            granular_df=df_filtered,
            show_core_metrics=False,
            raw_df=df_live,
        ),
        fallback_msg="Dashboard rendering encountered an error.",
    )

    # ── Operational Pipeline Summary (for All Orders view) ────────────────────
    if selected_view == "All Orders" and not df_live.empty:
        _render_order_pipeline_summary(df_live)

    # ── Product-Wise Shipped & Completed Orders Export ───────────────────
    _render_dispatch_export(selected_view)

    # ── Interactive Orders Ledger & Parcel Audit ─────────────────────────
    st.divider()
    safe_render(
        lambda: render_orders_ledger_view(
            df_live if not df_live.empty else df_standard
        ),
        fallback_msg="Orders ledger unavailable.",
    )

    # ── Staleness monitor stays visible below ────────────────────────────
    render_staleness_monitor()


def _render_dispatch_export(
    selected_view: str | None = None, raw_df: pd.DataFrame | None = None
):
    """Backwards-compatible wrapper delegating to dispatch_export_view component."""
    if raw_df is None:
        raw_df = _get_dashboard_source(online_only=False)
    render_dispatch_export(selected_view=selected_view, raw_df=raw_df)
