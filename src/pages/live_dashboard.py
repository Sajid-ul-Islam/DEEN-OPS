import streamlit as st
from datetime import datetime, timedelta, timezone

from src.components.widgets import render_reset_confirm
from src.processing.column_detection import find_columns
from src.processing.data_processing import prepare_granular_data, aggregate_data
from src.pages.dashboard_output import render_dashboard_output
from src.services.woocommerce.client import load_live_source
from src.utils.logging import log_system_event
from src.utils.safe_ops import safe_render


def render_live_tab():
    def _reset_live_state():
        st.session_state.wc_curr_df = None
        st.session_state.wc_prev_df = None
        st.session_state.live_sync_time = None
        st.session_state.wc_view_historical = False
        st.session_state.wc_sync_mode = "Operational Cycle"

    render_reset_confirm("Live Dashboard", "live", _reset_live_state)
    st.session_state.manual_tab_active = False # v11.3 Flag Reset

    # Use global imports
    tz_bd = timezone(timedelta(hours=6))

    # Force Operational Cycle in live dashboard
    st.session_state["wc_sync_mode"] = "Operational Cycle"

    st.markdown("### 🎛️ Shift View Filter")
    order_view_mode = st.radio(
        "Filter orders in current slot:",
        ["All Orders", "Shipped Only"],
        horizontal=True,
        key="live_order_filter"
    )

    # Standardize autorefresh for Live Dashboard

    try:
        try:
            df_live, source_name, modified_at = load_live_source()
        except Exception as api_err:
            log_system_event("LIVE_API_ERROR", f"Live sync failed, attempting fallback: {api_err}")
            from src.utils.snapshots import load_sales_snapshot
            df_snap = load_sales_snapshot()
            
            if df_snap is not None and not df_snap.empty:
                st.error("📡 **WooCommerce API Unreachable**")
                st.warning("⚠️ **Offline Mode:** Operating on the last locally saved snapshot. Data will not reflect live changes.")
                df_live = df_snap
                source_name = "LOCAL_SNAPSHOT_FALLBACK"
                modified_at = "OFFLINE_MODE"
                st.session_state.wc_nav_mode = "Offline"
            else:
                raise api_err # Bubble up if no snapshot exists

        # Handle v9.5 Multi-Mode Shift Navigation
        nav_mode = st.session_state.get("wc_nav_mode", "Today")
        if nav_mode == "Offline":
            pass # Bypass slot navigation, just use the fallback snapshot df
        elif nav_mode == "Prev" and "wc_prev_df" in st.session_state:
            df_live = st.session_state.wc_prev_df
            p_s, p_e = st.session_state.get("wc_prev_slot", (datetime.now(), datetime.now()))
            source_name = f"PREV_SLOT_{p_s.strftime('%a_%d%b')}"
            modified_at = "HISTORICAL_SNAPSHOT"
        elif nav_mode == "Backlog" and "wc_backlog_df" in st.session_state:
            df_live = st.session_state.wc_backlog_df
            b_s, b_e = st.session_state.get("wc_backlog_slot", (datetime.now(), datetime.now()))
            source_name = f"INCOMING_BATCH_{b_s.strftime('%H:%M')}"
            modified_at = "BACKLOG_QUEUE"
        elif nav_mode == "Today" and "wc_curr_df" in st.session_state:
            df_live = st.session_state.wc_curr_df
            # default df_live from load_live_source is already the current one

        if df_live is None or df_live.empty:
            st.warning(f"No data found for the {nav_mode} slot.")
            # Fallback to Today if we were in another mode
            if nav_mode != "Today" and nav_mode != "Offline":
                st.session_state.wc_nav_mode = "Today"
                st.rerun()

        # Apply Shipped Filter
        if order_view_mode == "Shipped Only":
            status_col = "Order Status" if "Order Status" in df_live.columns else "Status" if "Status" in df_live.columns else None
            
            if status_col:
                df_live = df_live[df_live[status_col].astype(str).str.lower().isin(["shipped"])]
                if df_live.empty:
                    st.info(f"📦 No shipped orders found in the {nav_mode} slot.")
                    return
            else:
                st.warning("⚠️ 'Order Status' column not found in data. Cannot apply filter.")

        try:
            auto_cols = find_columns(df_live)
        except Exception as col_err:
            log_system_event("LIVE_COLUMN_DETECT_ERROR", str(col_err))
            st.error(f"Column detection failed: {col_err}")
            st.dataframe(df_live.head(20), use_container_width=True)
            return

        missing_required = [k for k in ["name", "cost", "qty"] if k not in auto_cols]
        if missing_required:
            st.error(f"Cannot auto-map required columns: {', '.join(missing_required)}")
            st.dataframe(df_live.head(20), use_container_width=True)
            return

        live_mapping = {
            "name": auto_cols.get("name"),
            "cost": auto_cols.get("cost"),
            "qty": auto_cols.get("qty"),
            "date": auto_cols.get("date"),
            "order_id": auto_cols.get("order_id"),
            "phone": auto_cols.get("phone"),
        }

        df_standard, timeframe = prepare_granular_data(df_live, live_mapping)
        if df_standard.empty:
            st.warning("Data preparation returned empty results. Raw data shown below.")
            st.dataframe(df_live.head(20), use_container_width=True)
            return

        drill, summ, top, basket = aggregate_data(df_standard, live_mapping)
        if drill is None or summ is None:
            st.warning("Data aggregation failed. Raw data shown below.")
            st.dataframe(df_standard.head(20), use_container_width=True)
            return

        safe_render(
            lambda: render_dashboard_output(
                drill,
                summ,
                top,
                timeframe,
                basket,
                source_name,
                modified_at,
                granular_df=df_standard
            ),
            fallback_msg="Dashboard rendering encountered an error.",
        )

    except Exception as e:
        log_system_event("LIVE_FILE_ERROR", str(e))
        st.error(f"Live source error: {e}")
        st.info("\U0001f4a1 Tip: If WooCommerce is down, use the '\U0001f4e5 Sales Data Ingestion' tab to upload a local file or paste a public URL.")
