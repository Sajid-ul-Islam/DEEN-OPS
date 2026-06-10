"""Operational metrics rendering: KPI cards, deltas, status breakdown, and goal tracking."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src.processing.data_processing import aggregate_data, prepare_granular_data, safe_coerce_datetime_naive
from src.utils.metric_history import save_shift_snapshot, load_snapshot_history
from src.utils.logging import log_system_event


def _generate_sparkline_svg(values: list[float], color: str = "#3b82f6") -> str:
    """Generates a lightweight normalized SVG path for metric trends.
    Uses base64 encoding inside an img tag to prevent Streamlit Cloud sanitizing raw SVG.
    """
    if not values or len(values) < 2:  # A line needs at least 2 points to show a trend.
        return ""
    
    # Normalize values to fit 100x30 SVG coordinate system
    min_v, max_v = min(values), max(values)
    rng = max_v - min_v if max_v != min_v else 1
    
    points = []
    width = 100
    height = 30
    step = width / (len(values) - 1)
    
    for i, v in enumerate(values):
        x = i * step
        # Use 4px padding top/bottom to prevent clipping line caps
        y = height - ((v - min_v) / rng * (height - 8)) - 4
        points.append(f"{x:.1f},{y:.1f}")
    
    path_data = "M " + " L ".join(points)
    # Create a closed path for the area fill
    area_data = path_data + f" L {width:.1f},{height:.1f} L 0.0,{height:.1f} Z"
    
    # Render SVG with explicit namespaces
    svg_raw = f"""<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 100 30" preserveAspectRatio="none">
        <path d="{area_data}" fill="{color}" fill-opacity="0.15" />
        <path d="{path_data}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>"""
    
    import base64
    b64_svg = base64.b64encode(svg_raw.encode("utf-8")).decode("utf-8")
    
    return f"""
    <div class="metric-sparkline">
        <img src="data:image/svg+xml;base64,{b64_svg}" style="width: 100%; height: 30px; display: block;" />
    </div>
    """


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

    m_qty = m_df["Quantity"].sum() if "Quantity" in m_df.columns else 0
    m_rev = (m_df["Quantity"] * m_df["Item Cost"]).sum() if "Quantity" in m_df.columns and "Item Cost" in m_df.columns else 0
    m_ord = basket["total_orders"] if basket else 0
    m_bv = basket.get("avg_customer_value", basket.get("avg_basket_value", 0)) if basket else 0
    if pd.isna(m_bv): m_bv = 0

    dq_str, dr_str, do_str, db_str = None, None, None, None
    if c_df is not None and not c_df.empty:
        co_q = c_df["Quantity"].sum() if "Quantity" in c_df.columns else 0
        co_r = (c_df["Quantity"] * c_df["Item Cost"]).sum() if "Quantity" in c_df.columns and "Item Cost" in c_df.columns else 0
        _, _, _, co_basket = aggregate_data(c_df, dummy_mapping)
        co_o = co_basket["total_orders"] if co_basket else 0
        co_b = co_basket.get("avg_customer_value", co_basket.get("avg_basket_value", 0)) if co_basket else 0
        if pd.isna(co_b): co_b = 0

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

    extra_metric_label = "Basket Size"
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
            
    # ── 24-Hour Trend Extraction ──
    s_qty, s_rev, s_ord, s_bv = "", "", "", ""
    if not m_df.empty and nav_mode != "Backlog":
        try:
            # Prefer standardized 'Date' column over raw Order Date
            date_col = "Date" if "Date" in m_df.columns else wc_raw_mapping.get("date", "Order Date")
            t_df = m_df.copy()
            t_df["_dt"] = safe_coerce_datetime_naive(t_df[date_col])
            t_df = t_df.dropna(subset=["_dt"])
            
            if not t_df.empty:
                t_df["_hr"] = t_df["_dt"].dt.floor("h")
                
                # Fetch slot boundaries from session state to build continuous hour index
                slot_key = "wc_curr_slot" if nav_mode == "Today" else "wc_prev_slot" if nav_mode == "Prev" else None
                slot = st.session_state.get(slot_key) if slot_key else None
                
                if slot:
                    start_time, end_time = slot
                    start_hour = pd.to_datetime(start_time).floor("h")
                    end_hour = pd.to_datetime(end_time).floor("h")
                    all_hours = pd.date_range(start=start_hour, end=end_hour, freq="h")
                else:
                    # Fallback to actual data range if slot is missing
                    start_hour = t_df["_dt"].min().floor("h")
                    end_hour = t_df["_dt"].max().floor("h")
                    if start_hour == end_hour:
                        # Ensure we have at least 2 points
                        all_hours = pd.date_range(start=start_hour - pd.Timedelta(hours=1), end=end_hour + pd.Timedelta(hours=1), freq="h")
                    else:
                        all_hours = pd.date_range(start=start_hour, end=end_hour, freq="h")
                
                # Group by hour and reindex to include all hours in the shift
                # 1. Quantity Sum
                qty_series = t_df.groupby("_hr")["Quantity"].sum().reindex(all_hours, fill_value=0)
                t_qty_vals = qty_series.tolist()
                
                # 2. Revenue Sum
                t_df["_rev"] = t_df["Quantity"] * t_df["Item Cost"]
                rev_series = t_df.groupby("_hr")["_rev"].sum().reindex(all_hours, fill_value=0)
                t_rev_vals = rev_series.tolist()
                
                # 3. Orders Count (unique order IDs)
                order_id_col = wc_raw_mapping.get("order_id", "Order ID")
                ord_series = t_df.groupby("_hr")[order_id_col].nunique().reindex(all_hours, fill_value=0)
                t_ord_vals = ord_series.tolist()
                
                s_qty = _generate_sparkline_svg(t_qty_vals, "#3b82f6")
                s_rev = _generate_sparkline_svg(t_rev_vals, "#10b981")
                s_ord = _generate_sparkline_svg(t_ord_vals, "#6366f1")
                
                # For Basket Size trend (Average Basket Value per hour)
                t_bv_vals = [ (r / o if o > 0 else 0) for r, o in zip(t_rev_vals, t_ord_vals)]
                s_bv = _generate_sparkline_svg(t_bv_vals, "#f59e0b")
        except Exception as e:
            log_system_event("SPARKLINE_ERROR", f"Failed to generate sparklines: {e}")

    l1 = "Backlog Items" if nav_mode == "Backlog" else "Gross Items"
    l2 = "Backlog Rev" if nav_mode == "Backlog" else "Revenue"
    l3 = "Backlog Orders" if nav_mode == "Backlog" else "Orders"

    gross_items_card = (
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l1}</div>'
        f'<div class="metric-value">{v_qty}</div>{html_dq}{s_qty}</div>'
        '<div class="metric-icon">📦</div></div>'
    )

    card_html = (
        '<div class="metric-container metric-container-4">'
        f"{gross_items_card}"
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l2}</div>'
        f'<div class="metric-value">{v_rev}</div>{html_dr}{s_rev}</div><div class="metric-icon">৳</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l3}</div>'
        f'<div class="metric-value">{v_ord}</div>{html_do}{s_ord}</div><div class="metric-icon">🛒</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{extra_metric_label}</div>'
        f'<div class="metric-value">{extra_metric_value}</div>{extra_metric_delta}'
        f'{s_bv if nav_mode != "Backlog" else ""}</div>'
        f'<div class="metric-icon">{extra_metric_icon}</div></div>'
        "</div>"
    )


    st.markdown(card_html, unsafe_allow_html=True)

    # ── Feature #3: Goal Threshold Alerts ──────────────────────────────────────
    goals = st.session_state.get("shift_goals", {})
    rev_goal = goals.get("revenue", 0)
    ord_goal = goals.get("orders", 0)

    if rev_goal > 0 or ord_goal > 0:
        st.markdown("###### 🎯 Shift Goal Progress")
        g1, g2 = st.columns(2)
        with g1:
            if rev_goal > 0:
                pct = min(m_rev / rev_goal, 1.0)
                color = "#10b981" if pct >= 1.0 else "#f59e0b" if pct >= 0.7 else "#ef4444"
                label = "✅ Goal Reached!" if pct >= 1.0 else f"৳{m_rev:,.0f} / ৳{rev_goal:,.0f}"
                st.markdown(
                    f'<div style="margin-bottom:8px;">'  
                    f'<span style="font-size:0.72rem;font-weight:700;color:{color};letter-spacing:0.05em;">'
                    f'💰 REVENUE — {label}</span>'
                    f'<div style="background:rgba(255,255,255,0.08);border-radius:6px;height:8px;margin-top:4px;overflow:hidden;">'
                    f'<div style="background:{color};width:{pct*100:.1f}%;height:100%;border-radius:6px;'
                    f'transition:width 0.6s ease;"></div></div></div>',
                    unsafe_allow_html=True,
                )
        with g2:
            if ord_goal > 0:
                pct_o = min(m_ord / ord_goal, 1.0)
                color_o = "#10b981" if pct_o >= 1.0 else "#f59e0b" if pct_o >= 0.7 else "#ef4444"
                label_o = "✅ Goal Reached!" if pct_o >= 1.0 else f"{m_ord} / {ord_goal} orders"
                st.markdown(
                    f'<div style="margin-bottom:8px;">'
                    f'<span style="font-size:0.72rem;font-weight:700;color:{color_o};letter-spacing:0.05em;">'
                    f'🛒 ORDERS — {label_o}</span>'
                    f'<div style="background:rgba(255,255,255,0.08);border-radius:6px;height:8px;margin-top:4px;overflow:hidden;">'
                    f'<div style="background:{color_o};width:{pct_o*100:.1f}%;height:100%;border-radius:6px;'
                    f'transition:width 0.6s ease;"></div></div></div>',
                    unsafe_allow_html=True,
                )

    # ── Feature #5: Auto-Save Shift Snapshot ───────────────────────────────────
    # Only save once per render cycle, silently — keyed by data fingerprint
    snap_key = f"{m_rev:.0f}_{m_ord}_{m_qty}"
    if st.session_state.get("_last_snap_key") != snap_key and m_ord > 0:
        top_list = []
        if top is not None and not top.empty:
            name_col = "Product Name" if "Product Name" in top.columns else top.columns[0]
            amt_col = "Total Amount" if "Total Amount" in top.columns else None
            for _, row in top.sort_values(amt_col, ascending=False).head(5).iterrows() if amt_col else []:
                top_list.append({"name": str(row.get(name_col, "")), "revenue": float(row.get(amt_col, 0))})
        save_shift_snapshot(
            revenue=float(m_rev),
            orders=int(m_ord),
            qty=int(m_qty),
            aov=float(m_bv),
            shift_label=nav_mode,
            top_products=top_list,
        )
        st.session_state["_last_snap_key"] = snap_key

    return drill, summ, top, basket, active_df
