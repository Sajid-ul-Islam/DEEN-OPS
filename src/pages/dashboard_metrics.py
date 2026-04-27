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

    # Modern Metric Card Styling (Theme Aware)
    st.markdown("""
        <style>
        .metric-container {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }
        .metric-card {
            background: var(--background-secondary, rgba(255, 255, 255, 0.03));
            backdrop-filter: blur(8px);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(128, 128, 128, 0.1);
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: all 0.3s ease;
        }
        .metric-card:hover {
            transform: translateY(-3px);
            border-color: #3b82f6;
            background: var(--background-hover, rgba(255, 255, 255, 0.05));
        }
        .metric-content {
            flex: 1;
        }
        .metric-icon {
            font-size: 24px;
            width: 44px;
            height: 44px;
            background: rgba(59, 130, 246, 0.1);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #3b82f6;
            margin-left: 15px;
        }
        .metric-label {
            color: var(--text-muted, #888);
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 2px;
        }
        .metric-value {
            color: var(--text-color, #31333F);
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.01em;
        }
        .metric-delta {
            display: inline-flex;
            align-items: center;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 700;
            margin-top: 8px;
        }
        .delta-up { background: rgba(16, 185, 129, 0.1); color: #10b981; }
        .delta-down { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
        
        @media (max-width: 900px) {
            .metric-container { grid-template-columns: repeat(2, 1fr); }
            .metric-value { font-size: 1.3rem; }
        }
        @media (max-width: 600px) {
            .metric-container { grid-template-columns: 1fr; gap: 12px; }
            .metric-card { padding: 16px; }
            .metric-value { font-size: 1.4rem; }
        }
        @media (prefers-color-scheme: dark) {
            .metric-value { color: #ffffff !important; }
            .metric-label { color: #cbd5e1 !important; }
            .metric-card { background: rgba(255, 255, 255, 0.05); }
        }
        </style>
    """, unsafe_allow_html=True)

    def format_delta(delta_str):
        if not delta_str: return ""
        is_up = "+" in delta_str
        cls = "delta-up" if is_up else "delta-down"
        return f'<div class="metric-delta {cls}">{delta_str}</div>'

    # Format values for display to avoid f-string confusion in markdown
    v_qty = f"{m_qty:,.0f}"
    v_rev = f"TK {m_rev:,.0f}"
    v_ord = f"{m_ord:,.0f}"
    v_bv = f"TK {m_bv:,.0f}"
    
    html_dq = format_delta(dq_str)
    html_dr = format_delta(dr_str)
    html_do = format_delta(do_str)
    html_db = format_delta(db_str)

    # 1. Backlog Aging Intelligence (v15.0)
    extra_metric_label = "Avg Basket"
    extra_metric_value = v_bv
    extra_metric_delta = html_db
    extra_metric_icon = "🛍️"

    if nav_mode == "Backlog" and not m_df.empty:
        try:
            # Calculate oldest order age
            m_df['dt_temp'] = pd.to_datetime(m_df[wc_raw_mapping["date"]], errors="coerce").dt.tz_localize(None)
            oldest_t = m_df['dt_temp'].min()
            if oldest_t:
                diff = datetime.now() - oldest_t
                hours = int(diff.total_seconds() / 3600)
                mins = int((diff.total_seconds() % 3600) / 60)
                
                # Highlight if > 12h
                color = "#ef4444" if hours >= 12 else "#3b82f6"
                
                extra_metric_label = "Oldest Order"
                extra_metric_value = f"{hours}h {mins}m"
                extra_metric_delta = f'<div class="metric-delta" style="background: rgba(239, 68, 68, 0.1); color: {color};">AGING IN QUEUE</div>'
                extra_metric_icon = "⏳"
        except Exception:
            pass

    # KPI labels
    l1 = "Backlog Items" if nav_mode == "Backlog" else "Gross Items"
    l2 = "Backlog Rev" if nav_mode == "Backlog" else "Revenue"
    l3 = "Backlog Orders" if nav_mode == "Backlog" else "Orders"

    # Compact HTML construction to avoid Streamlit's markdown parser interference
    card_html = (
        '<div class="metric-container">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l1}</div><div class="metric-value">{v_qty}</div>{html_dq}</div><div class="metric-icon">📦</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l2}</div><div class="metric-value">{v_rev}</div>{html_dr}</div><div class="metric-icon">৳</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l3}</div><div class="metric-value">{v_ord}</div>{html_do}</div><div class="metric-icon">🛒</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{extra_metric_label}</div><div class="metric-value">{extra_metric_value}</div>{extra_metric_delta}</div><div class="metric-icon">{extra_metric_icon}</div></div>'
        '</div>'
    )

    st.markdown(card_html, unsafe_allow_html=True)

    return drill, summ, top, basket, active_df
