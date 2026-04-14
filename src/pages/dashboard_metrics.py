"""Operational metrics rendering — KPI cards, deltas, and status breakdown."""

from __future__ import annotations

import streamlit as st
from datetime import datetime, timedelta, timezone

from src.processing.data_processing import prepare_granular_data, aggregate_data


def render_operational_metrics(
    m_df,
    c_df,
    nav_mode: str,
    dummy_mapping: dict,
    wc_raw_mapping: dict,
):
    """Render the operational KPI cards with delta comparisons.

    Standardises *m_df* and *c_df* if needed, computes metrics, and renders
    the four KPI columns (Qty, Revenue, Orders, Avg Basket) with optional
    comparison deltas.

    Args:
        m_df: Main DataFrame for the current mode.
        c_df: Comparison DataFrame (may be None).
        nav_mode: Current navigation mode ('Today', 'Prev', 'Backlog').
        dummy_mapping: Standard column mapping for re-aggregation.
        wc_raw_mapping: WooCommerce raw column mapping.

    Returns:
        Tuple of (drill, summ, top, basket, active_df) after re-aggregation.
    """
    # Standardise if needed
    if "Category" not in m_df.columns or "Product Name" not in m_df.columns or "Clean_Product" not in m_df.columns:
        m_df, _ = prepare_granular_data(m_df, wc_raw_mapping)
    if c_df is not None and ("Category" not in c_df.columns or "Product Name" not in c_df.columns or "Clean_Product" not in c_df.columns):
        c_df, _ = prepare_granular_data(c_df, wc_raw_mapping)

    active_df = m_df

    # Re-calculate aggregates
    drill, summ, top, basket = aggregate_data(m_df, dummy_mapping)

    m_qty = m_df["Quantity"].sum()
    m_rev = (m_df["Quantity"] * m_df["Item Cost"]).sum()
    m_ord = basket["total_orders"]
    m_bv = basket["avg_basket_value"]

    # Comparison deltas
    dq_str, dr_str, do_str, db_str = None, None, None, None
    if c_df is not None and not c_df.empty:
        co_q = c_df["Quantity"].sum()
        co_r = (c_df["Quantity"] * c_df["Item Cost"]).sum()
        _, _, _, co_basket = aggregate_data(c_df, dummy_mapping)
        co_o = co_basket["total_orders"]
        co_b = co_basket["avg_basket_value"]

        prefix = "Today " if nav_mode == "Prev" else ""
        suffix = "" if nav_mode == "Prev" else " vs Prev"

        dq, dr, d_o, db = (m_qty - co_q), (m_rev - co_r), (m_ord - co_o), (m_bv - co_b)
        if nav_mode == "Prev":
            dq, dr, d_o, db = (co_q - m_qty), (co_r - m_rev), (co_o - m_ord), (co_b - m_bv)

        dq_str = f"{prefix}{dq:+,.0f}{suffix}"
        dr_str = f"{prefix}{'+' if dr >= 0 else '-'}TK {abs(dr):,.0f}{suffix}"
        do_str = f"{prefix}{d_o:+,.0f}{suffix}"
        db_str = f"{prefix}{'+' if db >= 0 else '-'}TK {abs(db):,.0f}{suffix}"

    # Sync label
    sync_label = "Just now"
    if st.session_state.get("live_sync_time"):
        diff = datetime.now() - st.session_state.live_sync_time
        mins = int(diff.total_seconds() / 60)
        sync_label = "Just now" if mins < 1 else f"{mins}m ago"

    # Radio logic moved to dashboard_output for layout reasons
    pass

    # KPI cards
    with st.container():
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            l1 = "Backlog Items" if nav_mode == "Backlog" else "Gross Sales Items"
            st.metric(l1, f"{m_qty:,.0f}", delta=dq_str, help="Includes Shipped, Confirmed, and Completed orders.")
        with col2:
            l2 = "Backlog Rev" if nav_mode == "Backlog" else "Revenue"
            st.metric(l2, f"TK {m_rev:,.0f}", delta=dr_str)
        with col3:
            l3 = "Backlog Orders" if nav_mode == "Backlog" else "Orders"
            st.metric(l3, f"{m_ord:,.0f}", delta=do_str)
        with col4:
            st.metric("Avg Basket", f"TK {m_bv:,.0f}", delta=db_str)
    st.divider()

    return drill, summ, top, basket, active_df
