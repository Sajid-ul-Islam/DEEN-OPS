"""Operational metrics rendering: KPI cards, deltas, and status breakdown."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src.processing.data_processing import aggregate_data, prepare_granular_data


def render_operational_metrics(
    m_df,
    c_df,
    nav_mode: str,
    dummy_mapping: dict,
    wc_raw_mapping: dict,
    forecast_val: float = 0,
    avg_proc_time: float = 0,
):
    """Render the operational KPI cards and return updated aggregates."""
    if (
        "Category" not in m_df.columns
        or "Product Name" not in m_df.columns
        or "Clean_Product" not in m_df.columns
    ):
        m_df, _ = prepare_granular_data(m_df, wc_raw_mapping)
    if c_df is not None and (
        "Category" not in c_df.columns
        or "Product Name" not in c_df.columns
        or "Clean_Product" not in c_df.columns
    ):
        c_df, _ = prepare_granular_data(c_df, wc_raw_mapping)

    active_df = m_df
    drill, summ, top, basket = aggregate_data(m_df, dummy_mapping)

    m_qty = m_df["Quantity"].sum()
    m_rev = (m_df["Quantity"] * m_df["Item Cost"]).sum()
    m_ord = basket["total_orders"]
    m_bv = basket["avg_basket_value"]

    dq_str, dr_str, do_str, db_str = None, None, None, None
    if c_df is not None and not c_df.empty:
        co_q = c_df["Quantity"].sum()
        co_r = (c_df["Quantity"] * c_df["Item Cost"]).sum()
        _, _, _, co_basket = aggregate_data(c_df, dummy_mapping)
        co_o = co_basket["total_orders"]
        co_b = co_basket["avg_basket_value"]

        prefix = "Today " if nav_mode == "Prev" else ""
        suffix = "" if nav_mode == "Prev" else " vs Prev"

        dq = m_qty - co_q
        dr = m_rev - co_r
        d_o = m_ord - co_o
        db = m_bv - co_b
        if nav_mode == "Prev":
            dq = co_q - m_qty
            dr = co_r - m_rev
            d_o = co_o - m_ord
            db = co_b - m_bv

        dq_str = f"{prefix}{dq:+,.0f}{suffix}"
        dr_str = f"{prefix}{'+' if dr >= 0 else '-'}TK {abs(dr):,.0f}{suffix}"
        do_str = f"{prefix}{d_o:+,.0f}{suffix}"
        db_str = f"{prefix}{'+' if db >= 0 else '-'}TK {abs(db):,.0f}{suffix}"

    if st.session_state.get("live_sync_time"):
        diff = datetime.now() - st.session_state.live_sync_time
        mins = int(diff.total_seconds() / 60)
        _sync_label = "Just now" if mins < 1 else f"{mins}m ago"
    else:
        _sync_label = "Just now"

    def format_delta(delta_str):
        if not delta_str:
            return ""
        is_up = "+" in delta_str
        cls = "delta-up" if is_up else "delta-down"
        return f'<div class="metric-delta {cls}">{delta_str}</div>'

    v_qty = f"{m_qty:,.0f}"
    v_rev = f"TK {m_rev:,.0f}"
    v_ord = f"{m_ord:,.0f}"
    v_bv = f"TK {m_bv:,.0f}"

    html_dq = format_delta(dq_str)
    html_dr = format_delta(dr_str)
    html_do = format_delta(do_str)
    html_db = format_delta(db_str)

    extra_metric_label = "Avg Basket"
    extra_metric_value = v_bv
    extra_metric_delta = html_db
    extra_metric_icon = "🛍️"

    if nav_mode == "Backlog" and not m_df.empty:
        try:
            m_df["dt_temp"] = pd.to_datetime(
                m_df[wc_raw_mapping["date"]], errors="coerce"
            ).dt.tz_localize(None)
            oldest_t = m_df["dt_temp"].min()
            if oldest_t:
                diff = datetime.now() - oldest_t
                hours = int(diff.total_seconds() / 3600)
                mins = int((diff.total_seconds() % 3600) / 60)
                color = "#ef4444" if hours >= 12 else "#3b82f6"

                extra_metric_label = "Oldest Order"
                extra_metric_value = f"{hours}h {mins}m"
                extra_metric_delta = (
                    '<div class="metric-delta" '
                    f'style="background: rgba(239, 68, 68, 0.1); color: {color};">'
                    "AGING IN QUEUE</div>"
                )
                extra_metric_icon = "⏳"
        except Exception:
            pass

    l1 = "Backlog Items" if nav_mode == "Backlog" else "Gross Items"
    l2 = "Backlog Rev" if nav_mode == "Backlog" else "Revenue"
    l3 = "Backlog Orders" if nav_mode == "Backlog" else "Orders"

    gross_items_card = (
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l1}</div>'
        f'<div class="metric-value">{v_qty}</div>{html_dq}</div>'
        '<div class="metric-icon">📦</div></div>'
    )

    card_html = (
        '<div class="metric-container metric-container-4">'
        f"{gross_items_card}"
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l2}</div>'
        f'<div class="metric-value">{v_rev}</div>{html_dr}</div><div class="metric-icon">৳</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l3}</div>'
        f'<div class="metric-value">{v_ord}</div>{html_do}</div><div class="metric-icon">🛒</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{extra_metric_label}</div>'
        f'<div class="metric-value">{extra_metric_value}</div>{extra_metric_delta}</div>'
        f'<div class="metric-icon">{extra_metric_icon}</div></div>'
        "</div>"
    )

    st.markdown(card_html, unsafe_allow_html=True)

    return drill, summ, top, basket, active_df
