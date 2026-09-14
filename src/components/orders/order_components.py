"""Reusable components for WooCommerce Orders module.

This module implements Hick's Law principles:
- Single Primary Action per view
- Progressive Disclosure for advanced options
- Clear visual hierarchy between primary/secondary actions
"""

from datetime import time

import pandas as pd
import streamlit as st

from src.config.constants import bd_today


def render_date_range_selector() -> tuple:
    """Render date range picker with fetch button.

    Returns:
        tuple: (date_range, fetch_clicked)
    """
    today = bd_today()
    c_date, c_fetch = st.columns([1.5, 1])

    with c_date:
        date_range = st.date_input(
            "📅 WooCommerce Date Range",
            value=(today, today),
            help="Select dates to fetch orders",
            key=f"wc_date_{st.session_state.get('wc_date_counter', 0)}",
        )

    with c_fetch:
        st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
        fetch_clicked = st.button(
            "📥 Fetch Orders",
            use_container_width=True,
            type="primary",
            key="wc_fetch_btn",
        )

        if fetch_clicked:
            _handle_fetch_orders(date_range)

    return date_range, fetch_clicked


def _handle_fetch_orders(date_range):
    """Handle order fetching from WooCommerce API."""
    from src.services.woocommerce.client import load_from_woocommerce

    st.session_state["wc_sync_mode"] = "Custom Range"
    if isinstance(date_range, (tuple, list)):
        if len(date_range) >= 2:
            st.session_state["wc_sync_start_date"] = date_range[0]
            st.session_state["wc_sync_end_date"] = date_range[1]
        elif len(date_range) == 1:
            st.session_state["wc_sync_start_date"] = date_range[0]
            st.session_state["wc_sync_end_date"] = date_range[0]
        else:
            st.session_state["wc_sync_start_date"] = bd_today()
            st.session_state["wc_sync_end_date"] = bd_today()
    elif date_range:
        st.session_state["wc_sync_start_date"] = date_range
        st.session_state["wc_sync_end_date"] = date_range
    else:
        st.session_state["wc_sync_start_date"] = bd_today()
        st.session_state["wc_sync_end_date"] = bd_today()

    st.session_state["wc_sync_start_time"] = time(0, 0, 0)
    st.session_state["wc_sync_end_time"] = time(23, 59, 59)

    with st.status("📡 Fetching from WooCommerce API...", expanded=True) as wc_status:
        wc_status.write("🔄 Clearing cache...")
        load_from_woocommerce.clear()
        wc_status.write("📥 Downloading order pages...")
        res = load_from_woocommerce()
        wc_status.write("✅ Orders fetched successfully")
        st.session_state["wc_tracking_df"] = res.get("df_to_return")
        st.session_state["wc_pathao_statuses"] = {}
        wc_status.update(
            label="WooCommerce sync complete", state="complete", expanded=False
        )


def render_order_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Render contextual order filters with progressive disclosure.

    Args:
        df: Input dataframe

    Returns:
        Filtered dataframe
    """
    if df is None or df.empty:
        return df

    filter_col = st.columns(3)

    with filter_col[0]:
        status_filter = st.selectbox(
            "Filter by Status",
            options=["All"] + sorted(df["Order Status"].unique().tolist())
            if "Order Status" in df.columns
            else ["All"],
            key="wc_status_filter",
        )

    with filter_col[1]:
        payment_filter = st.selectbox(
            "Filter by Payment",
            options=["All"] + sorted(df["Payment Method"].unique().tolist())
            if "Payment Method" in df.columns
            else ["All"],
            key="wc_payment_filter",
        )

    # Progressive disclosure: Advanced filters only shown when needed
    with filter_col[2]:
        show_advanced = st.checkbox("Advanced Filters", key="wc_advanced_toggle")

    if show_advanced:
        with st.expander("🔍 Advanced Filtering Options", expanded=True):
            adv_cols = st.columns(3)
            with adv_cols[0]:
                city_filter = st.text_input("Filter by City", key="wc_city_filter")
            with adv_cols[1]:
                merchant_filter = st.text_input(
                    "Filter by Merchant", key="wc_merchant_filter"
                )
            with adv_cols[2]:
                high_value = st.checkbox(
                    "High Value Orders Only (>৳1000)", key="wc_high_value"
                )

            # Apply advanced filters
            if city_filter and "City" in df.columns:
                df = df[df["City"].str.contains(city_filter, case=False, na=False)]
            if merchant_filter and "Merchant" in df.columns:
                df = df[
                    df["Merchant"].str.contains(merchant_filter, case=False, na=False)
                ]
            if high_value and "Total Amount" in df.columns:
                df = df[pd.to_numeric(df["Total Amount"], errors="coerce") > 1000]

    # Apply basic filters
    if status_filter != "All" and "Order Status" in df.columns:
        df = df[df["Order Status"] == status_filter]
    if payment_filter != "All" and "Payment Method" in df.columns:
        df = df[df["Payment Method"] == payment_filter]

    return df


def render_order_actions_bar(selected_count: int):
    """Render action bar with single primary action pattern.

    Args:
        selected_count: Number of selected orders
    """
    if selected_count == 0:
        st.info("👆 Select orders from the table to perform bulk actions")
        return

    action_cols = st.columns([1, 1, 1, 2])

    with action_cols[0]:
        if st.button("✅ Mark Complete", use_container_width=True, type="primary"):
            st.success(f"Marking {selected_count} orders as complete")

    with action_cols[1]:
        if st.button("🚚 Assign Courier", use_container_width=True):
            st.info("Courier assignment dialog would open here")

    with action_cols[2]:
        if st.button("📧 Send Updates", use_container_width=True):
            st.info("Bulk notification would be sent")

    with action_cols[3]:
        st.metric("Selected", f"{selected_count} orders")


def render_empty_state(message: str = "No orders found"):
    """Render consistent empty state for order views."""
    st.info(f"📭 {message}")
    st.caption("Try adjusting your filters or fetch new orders from WooCommerce")


def render_loading_status(label: str = "Loading...", expanded: bool = True):
    """Render standardized loading status indicator."""
    return st.status(label, expanded=expanded)
