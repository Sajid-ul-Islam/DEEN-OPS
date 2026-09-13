# Live Dashboard Components - Refactored for Hick's Law Compliance
"""
Phase 2 Refactoring: Breaking down render_live_tab() into focused components.
Each function now has a single responsibility and follows progressive disclosure.
"""

import hashlib

import pandas as pd
import streamlit as st

from src.config.constants import bd_today
from src.processing.data_processing import compute_live_filter_counts
from src.services.woocommerce.client import load_live_source as _load_live_source


def _compute_live_data_fingerprint(df):
    """Return a stable fingerprint for dashboard data relevant to auto-sync."""
    if df is None or df.empty:
        return ""

    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    modified_col = (
        "mod_dt_parsed"
        if "mod_dt_parsed" in df.columns
        else "Order Date Modified"
        if "Order Date Modified" in df.columns
        else None
    )
    order_id_col = "Order ID" if "Order ID" in df.columns else None
    columns = [
        column
        for column in (order_id_col, status_col, modified_col)
        if column and column in df.columns
    ]
    if not columns:
        return str(len(df))

    summary = f"{len(df)}_{df[columns].astype(str).to_string()}"
    return hashlib.md5(summary.encode("utf-8")).hexdigest()


def _check_and_trigger_ui_rerun():
    """Rerun the dashboard only when its cached live data actually changed."""
    current_df = st.session_state.get("wc_curr_df")
    if current_df is None or current_df.empty:
        return

    new_fingerprint = _compute_live_data_fingerprint(current_df)
    old_fingerprint = st.session_state.get("_live_dash_data_fingerprint", "")
    st.session_state["_live_dash_data_fingerprint"] = new_fingerprint
    if old_fingerprint and new_fingerprint != old_fingerprint:
        st.rerun()


@st.fragment(run_every=60)
def _sync_60s():
    """Run the higher-frequency sync used by the active shipped view."""
    if st.session_state.get("_initial_page_load", True):
        st.session_state["_initial_page_load"] = False
        return
    try:
        _load_live_source()
        _check_and_trigger_ui_rerun()
    except Exception:
        pass


@st.fragment(run_every=180)
def _sync_180s():
    """Run the background sync used by other dashboard views."""
    if st.session_state.get("_initial_page_load", True):
        st.session_state["_initial_page_load"] = False
        return
    try:
        _load_live_source()
        _check_and_trigger_ui_rerun()
    except Exception:
        pass


def _render_date_range_selector():
    """Render custom date range picker with clear button.

    Hick's Law: Only shows advanced date filtering when explicitly needed.
    """
    today_bd = bd_today()
    if "live_custom_range" not in st.session_state:
        st.session_state["live_custom_range"] = (today_bd, today_bd)
    curr_range = st.session_state.get("live_custom_range", (today_bd, today_bd))

    col1, col2 = st.columns([3, 1])

    with col1:
        sel_dates = st.date_input(
            "📅 Date Range",
            value=curr_range,
            max_value=today_bd,
            key="live_date_picker_widget",
            label_visibility="collapsed",
            help="Select custom start and end date range to filter orders.",
        )

        if isinstance(sel_dates, (list, tuple)) and len(sel_dates) == 2:
            new_r = (sel_dates[0], sel_dates[1])
            if st.session_state.get("live_custom_range") != new_r:
                st.session_state["live_custom_range"] = new_r
                st.session_state["wc_sync_start_date"] = sel_dates[0]
                st.session_state["wc_sync_end_date"] = sel_dates[1]
                st.rerun()
        elif isinstance(sel_dates, (list, tuple)) and len(sel_dates) == 1:
            new_r = (sel_dates[0], sel_dates[0])
            if st.session_state.get("live_custom_range") != new_r:
                st.session_state["live_custom_range"] = new_r
                st.session_state["wc_sync_start_date"] = sel_dates[0]
                st.session_state["wc_sync_end_date"] = sel_dates[0]
                st.rerun()

    with col2:
        if curr_range and (curr_range[0] != today_bd or curr_range[1] != today_bd):
            if st.button(
                "❌ Clear",
                key="btn_clear_custom_range",
                type="secondary",
                use_container_width=True,
                help="Reset to today's date",
            ):
                st.session_state["live_custom_range"] = (today_bd, today_bd)
                if "wc_sync_start_date" in st.session_state:
                    del st.session_state["wc_sync_start_date"]
                if "wc_sync_end_date" in st.session_state:
                    del st.session_state["wc_sync_end_date"]
                st.rerun()


def _render_operation_mode_selector(nav_mode: str):
    """Render operation mode pills (Last Day, Active, Queue).

    Hick's Law: Single primary action with clear visual hierarchy using pills.
    """
    mode_options = ["Last Day", "Active", "Queue"]
    mode_icons = {"Last Day": "⏳", "Active": "⚡", "Queue": "📥"}
    mode_to_state = {"Last Day": "Prev", "Active": "Today", "Queue": "Backlog"}
    state_to_mode = {v: k for k, v in mode_to_state.items()}
    current_idx = mode_options.index(state_to_mode.get(nav_mode, "Active"))

    if hasattr(st, "pills"):
        selected_mode = st.pills(
            "Op Mode",
            mode_options,
            default=mode_options[current_idx],
            format_func=lambda x: f"{mode_icons.get(x, '')} {x}".strip(),
            key="banner_op_mode_pills",
            label_visibility="collapsed",
        )
        if not selected_mode:
            selected_mode = mode_options[current_idx]
    else:  # Fallback for older Streamlit versions
        selected_mode = st.radio(
            "Op Mode",
            mode_options,
            index=current_idx,
            horizontal=True,
            format_func=lambda x: f"{mode_icons.get(x, '')} {x}".strip(),
            key="banner_op_mode_radio",
            label_visibility="collapsed",
        )

    new_nav = mode_to_state[selected_mode]
    if new_nav != nav_mode:
        st.session_state.wc_nav_mode = new_nav
        st.rerun()

    return selected_mode


def _render_order_filter_selector(nav_mode: str):
    """Render order filter options (All Orders, Shipped, Processing).

    Hick's Law: Progressive disclosure - only shown in 'Today' mode.
    """
    if nav_mode != "Today":
        st.markdown('<div style="height: 38px;"></div>', unsafe_allow_html=True)
        return

    opts_filter = ["All Orders", "Shipped", "Processing"]
    filter_icons = {"All Orders": "📦", "Shipped": "🚚", "Processing": "⚙️"}
    curr_filter = st.session_state.get("live_order_filter", "Shipped")
    if curr_filter not in opts_filter:
        curr_filter = "Shipped"

    if hasattr(st, "pills"):
        sel_filter = st.pills(
            "Shift View",
            opts_filter,
            default=curr_filter,
            format_func=lambda x: f"{filter_icons.get(x, '')} {x}".strip(),
            key="live_order_filter_pills",
            label_visibility="collapsed",
        )
    else:
        sel_filter = st.radio(
            "Shift View",
            opts_filter,
            index=opts_filter.index(curr_filter),
            horizontal=True,
            format_func=lambda x: f"{filter_icons.get(x, '')} {x}".strip(),
            key="live_order_filter_radio",
            label_visibility="collapsed",
        )

    if sel_filter and sel_filter != curr_filter:
        st.session_state.live_order_filter = sel_filter
        st.rerun()

    # Progressive disclosure: Online Only toggle only appears when Shipped is selected
    if sel_filter == "Shipped":
        online_only = st.toggle(
            "Online Only",
            value=st.session_state.get("shipped_online_only", False),
            key="shipped_online_only_toggle",
            help="Show only online orders (exclude outlet)",
        )
        if online_only != st.session_state.get("shipped_online_only", False):
            st.session_state.shipped_online_only = online_only
            st.rerun()


def _render_refresh_controls(nav_mode: str, load_live_source):
    """Render auto-sync indicator and manual refresh button.

    Hick's Law: Secondary action demoted visually with icon-only button.
    """
    dashboard_view = st.session_state.get("live_dashboard_view", "All Orders")

    # Auto-sync fragment runs based on mode
    if dashboard_view in {
        "All Orders",
        "Today",
        "Today Shipped",
        "Last Day",
        "Last Day Shipped",
    }:
        _sync_60s()
    else:
        _sync_180s()

    # Manual refresh - secondary action
    if st.button(
        "🔄",
        use_container_width=True,
        key="btn_refresh_newly_shipped",
        type="secondary",
        help="Force a manual data refresh",
    ):
        load_live_source(force_refresh=True)
        st.toast("⚡ Data refreshed!")
        st.rerun()


def _get_live_combined_source(online_only: bool = True):
    """Combine operational partitions for dashboard view filtering and badge counts."""
    manual = st.session_state.get("live_manual_override_df")
    if manual is not None and not manual.empty:
        if online_only:
            from src.processing.completed_analytics import filter_online_orders

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
        return None
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
        from src.processing.completed_analytics import filter_online_orders

        return filter_online_orders(res)
    return res


def apply_dashboard_view_selection(selected: str) -> None:
    """Synchronize session state when the active dashboard view changes."""
    nav_modes = {
        "All Orders": "Today",
        "Today Shipped": "Today",
        "Last Day Shipped": "Prev",
        "Queue": "Backlog",
    }
    order_filters = {
        "All Orders": "All Orders",
        "Today Shipped": "Shipped",
        "Last Day Shipped": "Shipped",
        "Queue": "Queue",
    }
    st.session_state["live_dashboard_view"] = selected
    st.session_state["wc_nav_mode"] = nav_modes.get(selected, "Today")
    st.session_state["live_order_filter"] = order_filters.get(selected, "All Orders")
    today = bd_today()
    st.session_state["live_custom_range"] = (today, today)
    st.session_state.pop("wc_sync_start_date", None)
    st.session_state.pop("wc_sync_end_date", None)


def _render_dashboard_view_selector():
    """Render the dashboard's single, mutually exclusive scope selector with real-time count badges."""
    options = ["All Orders", "Today Shipped", "Last Day Shipped", "Queue"]
    icons = {
        "All Orders": "📋",
        "Today Shipped": "🚚",
        "Last Day Shipped": "🕘",
        "Queue": "📥",
    }
    today_val = bd_today()
    from src.processing.data_processing import get_previous_working_day

    prev_w_day = get_previous_working_day(today_val)
    prev_day_name = prev_w_day.strftime("%A")

    if today_val.weekday() == 5:
        descriptions = {
            "All Orders": "Today's online checkout orders + backlog unfulfilled queue (Friday included in Saturday)",
            "Today Shipped": "Online checkout orders shipped on Friday + Saturday (off-day dispatches rolled into Saturday)",
            "Last Day Shipped": f"Online checkout orders shipped on {prev_day_name} (last operational working day, skipping Friday)",
            "Queue": "All online checkout orders on hold, waiting, or pending across all dates",
        }
    else:
        descriptions = {
            "All Orders": "Today's online checkout orders + backlog unfulfilled queue (excluding hold & waiting)",
            "Today Shipped": "Online checkout orders shipped or completed today (00:00–23:59 BD time)",
            "Last Day Shipped": f"Online checkout orders shipped on {prev_day_name} (previous working day)",
            "Queue": "All online checkout orders on hold, waiting, or pending across all dates",
        }

    current = st.session_state.get("live_dashboard_view", "All Orders")
    if current not in options:
        if current == "Today":
            current = "Today Shipped"
        elif current == "Last Day":
            current = "Last Day Shipped"
        else:
            current = "All Orders"

    # Compute dynamic real-time counts from combined operational data
    source_df = _get_live_combined_source()
    counts = compute_live_filter_counts(source_df)

    def _format_label(opt: str) -> str:
        count = counts.get(opt, 0)
        return f"{icons[opt]} {opt} ({count})"

    if hasattr(st, "pills"):
        selected = st.pills(
            "Dashboard View",
            options,
            default=current,
            format_func=_format_label,
            key="live_dashboard_view_pills",
            label_visibility="collapsed",
        )
    else:
        selected = st.radio(
            "Dashboard View",
            options,
            index=options.index(current),
            horizontal=True,
            format_func=_format_label,
            key="live_dashboard_view_radio",
            label_visibility="collapsed",
        )

    selected = selected or current
    st.caption(f"ℹ️ {descriptions.get(selected, '')}")

    if selected != current:
        apply_dashboard_view_selection(selected)
        st.rerun()


def _render_completed_orders_section():
    """Render date-wise completed orders section with progressive disclosure.

    Hick's Law:
    - Single primary action (Show KPIs button)
    - Advanced filters hidden until needed
    - Clear visual hierarchy
    """
    st.markdown("---")
    st.markdown("### 📅 Date-Wise Completed Orders")
    st.caption("Pick a date and filter by source to see completed order KPIs.")

    # Date picker and source toggle in a row
    c_date, c_source, c_btn = st.columns([2, 2, 1])

    with c_date:
        today_bd = bd_today()
        default_date = st.session_state.get("completed_date", today_bd)
        selected_date = st.date_input(
            "Select Date",
            value=default_date,
            max_value=today_bd,
            key="completed_date_picker",
            help="Pick a date to view completed orders for that day",
        )
        if selected_date != default_date:
            st.session_state["completed_date"] = selected_date

    with c_source:
        st.markdown('<div style="height: 5px;"></div>', unsafe_allow_html=True)
        source_filter = st.radio(
            "Source",
            ["Both", "Online", "Outlet"],
            horizontal=True,
            key="completed_source_filter",
            help="Filter by order source: Online (website) or Outlet (physical store)",
        )

    with c_btn:
        st.markdown('<div style="height: 5px;"></div>', unsafe_allow_html=True)
        # PRIMARY ACTION - Only button with emphasis
        show_kpis = st.button(
            "📊 Show KPIs",
            key="show_completed_kpis",
            type="primary",  # Visual hierarchy: primary vs default
            use_container_width=True,
        )

    return show_kpis, st.session_state.get("completed_date", bd_today()), source_filter


def _render_completed_kpis_display(selected_date, source_filter, df_live):
    """Display completed orders KPIs with progressive disclosure.

    Hick's Law: Details hidden in expanders, only shown on demand.
    """
    from src.processing.completed_analytics import (
        filter_completed_orders_by_date,
        compute_completed_kpis,
    )

    with st.status(
        f"Loading completed orders for {selected_date}...", expanded=True
    ) as status:
        # Get full dataset
        full_df = st.session_state.get("wc_full_df")

        if full_df is None or full_df.empty:
            st.error("No order data available. Please sync data first.")
            status.update(label="❌ No data available", state="error")
            return

        # Filter by date and source
        filtered_df = filter_completed_orders_by_date(
            full_df, selected_date, source_filter
        )

        if filtered_df.empty:
            st.info(f"No completed orders found for {selected_date} ({source_filter})")
            status.update(label="ℹ️ No orders found", state="complete")
            return

        # Compute KPIs
        kpis = compute_completed_kpis(filtered_df)

        status.update(label="✅ KPIs computed", state="complete")

    # Display KPIs using the modern flat design
    from src.components.dashboard.modern_kpi import render_modern_kpi_cards

    # Primary metric: Total Revenue (largest)
    # Secondary metrics: Order Count, AOV, Completion Rate (smaller)
    metrics_config = [
        {
            "label": "Total Revenue",
            "value": kpis.get("total_revenue", 0),
            "prefix": "৳",
            "trend_label": "vs yesterday",
            "is_primary": True,  # Makes this the hero number
        },
        {
            "label": "Orders Completed",
            "value": kpis.get("order_count", 0),
            "trend_label": "orders",
            "is_primary": False,
        },
        {
            "label": "Average Order Value",
            "value": kpis.get("aov", 0),
            "prefix": "৳",
            "trend_label": "per order",
            "is_primary": False,
        },
        {
            "label": "Completion Rate",
            "value": kpis.get("completion_rate", 0),
            "suffix": "%",
            "trend_label": "of total",
            "is_primary": False,
        },
    ]

    render_modern_kpi_cards(metrics_config, key_prefix="completed_")

    # Progressive disclosure: Order details hidden in expander
    with st.expander("📋 View Order Details", expanded=False):
        st.dataframe(
            filtered_df[["Order ID", "Customer Name", "Total", "Status"]],
            use_container_width=True,
            hide_index=True,
        )

        # Export option - secondary action
        if st.button("📥 Download CSV", key="download_completed_csv", type="secondary"):
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="Download",
                data=csv,
                file_name=f"completed_orders_{selected_date}.csv",
                mime="text/csv",
            )


def _render_manual_upload_override():
    """Collapsible manual file uploader allowing users to override automatic sync with their own CSV/Excel."""
    is_active = st.session_state.get("live_manual_override_df") is not None
    source_name = st.session_state.get("live_manual_override_name", "Custom Upload")

    expander_title = (
        f"📁 Manual Data Upload (🟢 Active Override: {source_name})"
        if is_active
        else "📁 Manual Data Upload (Optional Override)"
    )

    with st.expander(expander_title, expanded=is_active):
        if is_active:
            col_info, col_reset = st.columns([4, 1.2], vertical_alignment="center")
            with col_info:
                st.success(
                    f"🟢 **Manual Override Active:** Displaying orders from `{source_name}` (Filtered to online checkout orders only)."
                )
            with col_reset:
                if st.button(
                    "🔄 Reset to Auto Sync",
                    key="btn_reset_manual_override",
                    type="primary",
                    use_container_width=True,
                    help="Discard manual file and resume live WooCommerce API sync",
                ):
                    st.session_state.pop("live_manual_override_df", None)
                    st.session_state.pop("live_manual_override_name", None)
                    st.session_state.pop("live_df_standard", None)
                    st.session_state.pop("live_cmp_standard", None)
                    st.toast("⚡ Restored automatic live sync!")
                    st.rerun()

        st.caption(
            "Upload your own order export (`.xlsx` or `.csv`) if you prefer to view manual data instead of auto-sync. "
            "The Live Dashboard KPI cards, view badges, and charts will immediately compute on your uploaded file."
        )
        uploaded = st.file_uploader(
            "Upload sales file",
            type=["csv", "xlsx"],
            key="live_manual_file_uploader",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            current_name = st.session_state.get("live_manual_override_name")
            if current_name != uploaded.name:
                from src.utils.file_io import read_sales_file
                from src.processing.data_processing import safe_coerce_datetime_naive

                try:
                    df_up = read_sales_file(uploaded, uploaded.name)
                    if df_up is not None and not df_up.empty:
                        # Ensure date parsing compatibility
                        if (
                            "Order Date" in df_up.columns
                            and "dt_parsed" not in df_up.columns
                        ):
                            df_up["dt_parsed"] = safe_coerce_datetime_naive(
                                df_up["Order Date"]
                            )
                        if (
                            "Order Date Modified" in df_up.columns
                            and "mod_dt_parsed" not in df_up.columns
                        ):
                            df_up["mod_dt_parsed"] = safe_coerce_datetime_naive(
                                df_up["Order Date Modified"]
                            )

                        st.session_state["live_manual_override_df"] = df_up
                        st.session_state["live_manual_override_name"] = uploaded.name
                        st.session_state.pop("live_df_standard", None)
                        st.session_state.pop("live_cmp_standard", None)
                        st.toast(f"✅ Loaded {uploaded.name} ({len(df_up)} rows)")
                        st.rerun()
                except Exception as ex:
                    st.error(f"⚠️ Failed to read uploaded file: {ex}")


def render_dashboard_banner(load_live_source):
    """Render the main dashboard banner with controls.

    Hick's Law Implementation:
    - Single primary action per section
    - Progressive disclosure for advanced options
    - Clear visual hierarchy with button types
    """
    nav_mode = st.session_state.get("wc_nav_mode", "Today")

    st.caption("One view controls the KPI cards, order list, and analysis.")
    c1, c2 = st.columns([6, 0.5], vertical_alignment="center")
    with c1:
        _render_dashboard_view_selector()

    with c2:
        _render_refresh_controls(nav_mode, load_live_source)

    _render_manual_upload_override()
