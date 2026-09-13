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

from src.components.dashboard.dashboard_metrics import render_operational_metrics
from src.components.dashboard.dashboard_output import render_dashboard_output
from src.components.dashboard.live_components import (
    render_dashboard_banner,
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
            st.session_state.get("wc_full_df"),
            st.session_state.get("wc_curr_df"),
            st.session_state.get("wc_prev_df"),
            st.session_state.get("wc_backlog_df"),
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
    elif selected_view == "All Orders":
        if _dash_src is not None and not _dash_src.empty:
            prev_work_d = get_previous_working_day(bd_today())
            _cmp_f = filter_live_dashboard_view(
                _dash_src, "All Orders", reference_date=prev_work_d
            )
        if _cmp_f is None or _cmp_f.empty:
            _cmp_raw = st.session_state.get("wc_prev_df")
            if _cmp_raw is None or _cmp_raw.empty:
                full_raw = st.session_state.get("wc_full_df")
                if full_raw is not None and not full_raw.empty:
                    try:
                        from src.services.woocommerce.client import (
                            _partition_operational_data,
                        )

                        _, df_prev_ext, _, _, _ = _partition_operational_data(full_raw)
                        _cmp_raw = df_prev_ext
                    except Exception:
                        pass
            if _cmp_raw is not None and not _cmp_raw.empty:
                _cmp_raw = filter_online_orders(_cmp_raw)
                _cmp_f = apply_order_view_comparison(
                    _cmp_raw, nav_mode, order_view_mode
                )
    elif selected_view in {"Last Day Shipped", "Last Day"}:
        if _dash_src is not None and not _dash_src.empty:
            prev_work_d = get_previous_working_day(bd_today())
            _cmp_f = filter_live_dashboard_view(
                _dash_src,
                "Last Day Shipped",
                reference_date=prev_work_d,
            )
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
        forecast_val=0,
        avg_proc_time=0,
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
    other_mask = ~(sales_mask | processing_mask | held_mask)

    summary_parts = [
        f"🚚 Actual sales **{count_orders(sales_mask)}**",
        f"⚙️ Processing **{count_orders(processing_mask)}**",
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

            mod_col = (
                "mod_dt_parsed"
                if "mod_dt_parsed" in df_live.columns
                else (
                    "Order Date Modified"
                    if "Order Date Modified" in df_live.columns
                    else None
                )
            )
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
                if "Order ID" in df_live.columns
                else len(df_live)
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

    selected_view = st.session_state.get("live_dashboard_view", "All Orders")
    nav_mode, order_view_mode = view_state.get(selected_view, view_state["All Orders"])
    df_live = filter_live_dashboard_view(
        _get_dashboard_source(fallback=df_live), selected_view
    )
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
    }
    # Standardize data for current view
    df_standard, timeframe = prepare_granular_data(df_live, live_mapping)

    # Stash the granular frames so the KPI cards and downstream charts share
    # the exact same synchronized dataset.
    st.session_state["live_df_standard"] = df_standard
    st.session_state["live_cmp_standard"] = _get_comparison_frame(
        selected_view, nav_mode, order_view_mode, live_mapping
    )

    # ── KPI Cards (5 core metric cards + comparison deltas) ────────────────────
    _refresh_core_metrics()

    # ── Operational Pipeline Summary (for All Orders view) ────────────────────
    if selected_view == "All Orders" and not df_live.empty:
        _render_order_pipeline_summary(df_live)

    # ── Detail & Performance Charts ─────────────────────────────────────────
    if df_standard.empty:
        if selected_view in {"Today Shipped", "Today"}:
            st.info(
                "🚚 **No orders shipped yet today.** Today's dispatches will appear here once fulfilled."
            )
        elif selected_view in {"Last Day Shipped", "Last Day"}:
            st.info("🕘 **No shipped orders recorded** for the previous calendar day.")
        elif selected_view == "Queue":
            st.info(
                "📋 **Queue is clear.** There are currently no orders on hold or waiting."
            )
        else:
            st.info(f"📦 **No active orders found** for the **{selected_view}** view.")
        render_staleness_monitor()
        return

    drill, summ, top, basket = aggregate_data(df_standard, live_mapping)
    if drill is None or summ is None:
        st.info(
            "ℹ️ Insufficient category data available to display charts for this view."
        )
        render_staleness_monitor()
        return

    # A conditional view selector avoids executing hidden tab content on every
    # Streamlit rerun.
    if hasattr(st, "segmented_control"):
        dashboard_view = st.segmented_control(
            "Dashboard detail",
            ["📋 Today", "🔍 Analysis"],
            default="📋 Today",
            key="live_dashboard_detail_view",
            label_visibility="collapsed",
        )
    else:
        dashboard_view = st.radio(
            "Dashboard detail",
            ["📋 Today", "🔍 Analysis"],
            horizontal=True,
            key="live_dashboard_detail_view_radio",
            label_visibility="collapsed",
        )

    if dashboard_view == "📋 Today":
        # ── Dashboard Output (charts, tables, AI briefing, export) ───────────
        safe_render(
            lambda: render_dashboard_output(
                drill,
                summ,
                top,
                str(timeframe) if timeframe is not None else None,
                basket,
                str(source_name) if source_name is not None else None,
                str(modified_at) if modified_at is not None else None,
                granular_df=df_standard,
                show_core_metrics=False,
            ),
            fallback_msg="Dashboard rendering encountered an error.",
        )

        # ── Product-Wise Shipped & Completed Orders Export ───────────────────
        _render_dispatch_export(selected_view)
    else:
        # ── Market Basket & Cross-Selling Intelligence ───────────────────────
        from src.components.dashboard.market_basket_view import (
            render_market_basket_analysis_section,
        )

        render_market_basket_analysis_section(df_standard, raw_df=df_live)

    # ── Staleness monitor stays visible below both tabs ──────────────────────
    render_staleness_monitor()


def _render_dispatch_export(selected_view: str | None = None):
    """Render product-wise everyday shipped and completed orders export with date picker, XLSX and CSV."""
    from src.processing.completed_analytics import (
        filter_shipped_order_items,
    )
    from src.services.exports.excel_exporter import export_to_styled_excel
    from src.processing.data_processing import safe_coerce_datetime_naive

    raw_df = _get_dashboard_source(online_only=False)
    if raw_df is None or raw_df.empty:
        raw_df = st.session_state.get("wc_curr_df")
    if raw_df is None or raw_df.empty:
        return

    today_bd = bd_today()
    prev_work_bd = get_previous_working_day(today_bd)
    prev_day_name = prev_work_bd.strftime("%A")
    prev_label = (
        f"Previous Working Day ({prev_day_name[:3]})"
        if today_bd.weekday() == 5
        else "Yesterday"
    )

    # Determine default date based on selected_view
    if selected_view in {"Last Day Shipped", "Last Day"}:
        default_preset = prev_label
    else:
        default_preset = "Today"

    st.divider()
    with st.expander(
        "📦 Daily Shipped & Completed Orders (Product-Wise Export)",
        expanded=(
            selected_view in {"Today Shipped", "Today", "Last Day Shipped", "Last Day"}
        ),
    ):
        st.caption(
            "Export product line items for orders shipped or completed on any selected date. "
            "Includes SKU, Quantity, Item Price, and Customer details in styled Excel (.xlsx) and CSV."
        )

        col_preset, col_date, col_source = st.columns([1.5, 2, 1.5])
        with col_preset:
            date_preset = st.radio(
                "Date Selection",
                ["Today", prev_label, "Custom Date"],
                index=0 if default_preset == "Today" else 1,
                horizontal=True,
                key="shipped_export_date_preset",
            )

        with col_date:
            if date_preset == "Today":
                start_date = today_bd
                end_date = today_bd
                st.caption(f"🗓️ Active Day: **{today_bd.strftime('%Y-%m-%d (%A)')}**")
            elif date_preset == prev_label:
                start_date = prev_work_bd
                end_date = prev_work_bd
                st.caption(
                    f"🗓️ Active Day: **{prev_work_bd.strftime('%Y-%m-%d (%A)')}** (Skipping Friday off-day)"
                )
            else:
                custom_range = st.date_input(
                    "Select Date or Range",
                    value=(prev_work_bd, today_bd),
                    max_value=today_bd,
                    key="shipped_export_custom_range",
                )
                if isinstance(custom_range, (list, tuple)):
                    start_date = custom_range[0]
                    end_date = (
                        custom_range[-1] if len(custom_range) > 1 else custom_range[0]
                    )
                else:
                    start_date = custom_range
                    end_date = custom_range

        with col_source:
            source_filter = st.radio(
                "Order Source",
                ["Online", "Both", "Outlet"],
                index=0,
                horizontal=True,
                key="shipped_export_source_filter",
            )

        # Filter items using completed_analytics
        filtered_items = filter_shipped_order_items(
            raw_df,
            start_date=start_date,
            end_date=end_date,
            source_filter=source_filter,
        )

        date_label = (
            start_date.strftime("%Y-%m-%d")
            if start_date == end_date
            else f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )

        if filtered_items.empty:
            st.info(
                f"ℹ️ No shipped or completed items found for **{date_label}** ({source_filter} orders)."
            )
            return

        export_df = filtered_items.copy()

        # Identify columns defensively
        status_col = (
            "Order Status"
            if "Order Status" in export_df.columns
            else "Status"
            if "Status" in export_df.columns
            else None
        )
        prod_col = (
            "Item Name"
            if "Item Name" in export_df.columns
            else "Product Name"
            if "Product Name" in export_df.columns
            else None
        )
        sku_col = "SKU" if "SKU" in export_df.columns else None
        qty_col = "Quantity" if "Quantity" in export_df.columns else None
        cost_col = (
            "Item Cost"
            if "Item Cost" in export_df.columns
            else "Price"
            if "Price" in export_df.columns
            else None
        )

        # Ensure numeric Quantity and Cost
        if qty_col:
            export_df[qty_col] = (
                pd.to_numeric(export_df[qty_col], errors="coerce").fillna(1).astype(int)
            )
        else:
            export_df["Quantity"] = 1
            qty_col = "Quantity"

        if cost_col:
            export_df[cost_col] = pd.to_numeric(
                export_df[cost_col], errors="coerce"
            ).fillna(0.0)
        else:
            export_df["Item Cost"] = 0.0
            cost_col = "Item Cost"

        export_df["Line Total"] = (export_df[qty_col] * export_df[cost_col]).round(2)

        # Format dates
        if "mod_dt_parsed" in export_df.columns:
            export_df["Shipped Date"] = safe_coerce_datetime_naive(
                export_df["mod_dt_parsed"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        elif "Order Date Modified" in export_df.columns:
            export_df["Shipped Date"] = safe_coerce_datetime_naive(
                export_df["Order Date Modified"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        else:
            export_df["Shipped Date"] = ""

        if "dt_parsed" in export_df.columns:
            export_df["Order Placed"] = safe_coerce_datetime_naive(
                export_df["dt_parsed"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        elif "Order Date" in export_df.columns:
            export_df["Order Placed"] = safe_coerce_datetime_naive(
                export_df["Order Date"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        else:
            export_df["Order Placed"] = ""

        if "_order_source" in export_df.columns:
            export_df["Order Source"] = export_df["_order_source"]

        # Map customer and order fields
        field_mapping = {
            "Order ID": "Order ID",
            prod_col: "Product Name",
            sku_col: "SKU",
            qty_col: "Quantity",
            cost_col: "Item Cost",
            "Line Total": "Line Total",
            status_col: "Status",
            "Order Source": "Source",
            "Shipped Date": "Shipped Date",
            "Order Placed": "Order Placed",
            "Full Name (Billing)": "Customer",
            "Phone (Billing)": "Phone",
            "Shipping City": "City",
            "Shipping Address 1": "Address",
            "Pathao Consignment ID": "Consignment ID",
        }

        # Build column ordering
        export_cols = [
            field_mapping[k] for k in field_mapping if k and k in export_df.columns
        ]

        # Rename to clean target headers
        clean_df = export_df.rename(
            columns={
                k: v for k, v in field_mapping.items() if k and k in export_df.columns
            }
        )

        # Sort chronologically by Order ID / Shipped Date
        sort_candidates = [
            c
            for c in ["Shipped Date", "Order Placed", "Order ID"]
            if c in clean_df.columns
        ]
        if sort_candidates:
            clean_df = clean_df.sort_values(
                by=sort_candidates, ascending=False, na_position="last"
            ).reset_index(drop=True)

        final_cols = [c for c in export_cols if c in clean_df.columns]
        display_df = clean_df[final_cols].copy()

        # Summary KPIs
        total_items = (
            int(display_df["Quantity"].sum())
            if "Quantity" in display_df.columns
            else len(display_df)
        )
        total_orders = (
            int(display_df["Order ID"].nunique())
            if "Order ID" in display_df.columns
            else len(display_df)
        )
        total_rev = (
            float(display_df["Line Total"].sum())
            if "Line Total" in display_df.columns
            else 0.0
        )
        unique_skus = (
            int(display_df["SKU"].nunique()) if "SKU" in display_df.columns else 0
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("📦 Units Shipped", f"{total_items:,}")
        m2.metric("📋 Orders", f"{total_orders:,}")
        m3.metric("৳ Shipped Revenue", f"৳ {total_rev:,.0f}")
        m4.metric("🏷️ Unique SKUs", f"{unique_skus:,}")

        # Search box
        search_q = st.text_input(
            "🔍 Search items by Order ID, Product Name, SKU, Customer, or Phone",
            key="shipped_product_export_search",
        ).strip()

        view_df = display_df.copy()
        if search_q:
            mask = pd.Series(False, index=view_df.index)
            for c in ["Order ID", "Product Name", "SKU", "Customer", "Phone", "City"]:
                if c in view_df.columns:
                    mask = mask | view_df[c].astype(str).str.contains(
                        search_q, case=False, na=False
                    )
            view_df = view_df[mask]

        st.dataframe(
            view_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Order ID": st.column_config.NumberColumn("Order ID", format="%d"),
                "Quantity": st.column_config.NumberColumn("Qty", format="%d"),
                "Item Cost": st.column_config.NumberColumn("Price (৳)", format="%.2f"),
                "Line Total": st.column_config.NumberColumn("Total (৳)", format="%.2f"),
            },
        )

        file_tag = (
            start_date.strftime("%Y%m%d")
            if start_date == end_date
            else f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        )
        now_str = bd_now().strftime("%H%M")
        base_filename = f"DEEN_Shipped_Products_{file_tag}_{now_str}"

        # Export generators
        c_down1, c_down2 = st.columns(2)
        with c_down1:
            try:
                excel_bytes = export_to_styled_excel(
                    {f"Shipped_{file_tag}"[:31]: display_df},
                    group_by_col="Order ID"
                    if "Order ID" in display_df.columns
                    else None,
                )
                st.download_button(
                    label=f"⬇️ Download Excel (.xlsx) — {len(display_df)} items",
                    data=excel_bytes,
                    file_name=f"{base_filename}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                    key="shipped_product_download_excel",
                )
            except Exception as e:
                log_system_event("EXCEL_EXPORT_ERROR", str(e))
                st.warning("Excel formatting unavailable, use CSV download.")

        with c_down2:
            csv_bytes = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"⬇️ Download CSV (.csv) — {len(display_df)} items",
                data=csv_bytes,
                file_name=f"{base_filename}.csv",
                mime="text/csv",
                type="secondary",
                use_container_width=True,
                key="shipped_product_download_csv",
            )
