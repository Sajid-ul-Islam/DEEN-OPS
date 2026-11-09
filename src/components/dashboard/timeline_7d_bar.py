"""7-Day Rolling Dispatch History Timeline Component.

Renders an interactive 7-day timeline banner with operational performance cards:
- Rolling 7-day revenue, order volume, and AOV benchmarks
- Daily day-cards with order counts, revenues, and exchange badges
- Interactive day selection to scope the dashboard to any historical day in 1-click
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.processing.orders.timeline_7d import (
    Timeline7dReport,
    build_7day_dispatch_timeline,
)


def render_timeline_7d_bar(
    full_orders_df: pd.DataFrame,
    key_prefix: str = "dispatch_timeline_7d",
) -> str | None:
    """Render the 7-day rolling dispatch history bar with interactive day selection.

    Args:
        full_orders_df: Multi-day orders DataFrame.
        key_prefix: Unique widget key prefix.

    Returns:
        The selected date ISO string (YYYY-MM-DD) if clicked, or None.
    """
    if full_orders_df is None or full_orders_df.empty:
        return None

    # Compute timeline model
    report: Timeline7dReport = build_7day_dispatch_timeline(full_orders_df)
    if not report.days:
        return None

    st.markdown("#### 📅 7-Day Rolling Dispatch Performance")

    # Benchmark subheader
    col_bench1, col_bench2, col_bench3, col_bench4 = st.columns(4)
    with col_bench1:
        st.caption(f"7D Total Rev: **৳ {report.total_7d_revenue:,.0f}**")
    with col_bench2:
        st.caption(f"7D Orders: **{report.total_7d_orders}**")
    with col_bench3:
        st.caption(f"Daily Avg Rev: **৳ {report.avg_7d_revenue:,.0f}**")
    with col_bench4:
        st.caption(f"7D Avg AOV: **৳ {report.avg_7d_aov:,.0f}**")

    # Render day cards horizontally in 7 columns
    selected_date_key = f"{key_prefix}_selected"
    current_selected = st.session_state.get(selected_date_key)

    cols = st.columns(len(report.days))

    for idx, day in enumerate(report.days):
        with cols[idx]:
            is_active = (current_selected == day.date_iso) or (
                not current_selected and day.is_today
            )
            border = "2px solid #2563eb" if is_active else "1px solid #e2e8f0"
            bg = "#eff6ff" if is_active else "#ffffff"

            # Tag
            tag = (
                "🌟 TODAY"
                if day.is_today
                else ("PREV" if day.is_prev_day else day.day_short)
            )
            exchange_badge = (
                f"<span style='background:#fef3c7;color:#92400e;font-size:11px;padding:2px 5px;border-radius:4px;'>🔄 {day.exchange_count}</span>"
                if day.exchange_count > 0
                else ""
            )

            date_display = (
                day.date_label.split(",")[1].strip()
                if "," in day.date_label
                else day.date_iso
            )
            st.markdown(
                f"""
                <div style="border: {border}; background: {bg}; border-radius: 8px; padding: 8px 10px; text-align: center; margin-bottom: 6px;">
                    <div style="font-size: 11px; font-weight: 700; color: #64748b; letter-spacing: 0.05em;">{tag}</div>
                    <div style="font-size: 13px; font-weight: 700; color: #1e293b; margin: 2px 0;">{date_display} ({day.day_short})</div>
                    <div style="font-size: 15px; font-weight: 800; color: #0f172a;">{day.order_count} <span style="font-size: 11px; font-weight: normal; color: #64748b;">orders</span></div>
                    <div style="font-size: 12px; font-weight: 600; color: #059669; margin-top: 2px;">৳ {day.revenue:,.0f}</div>
                    <div style="margin-top: 4px;">{exchange_badge}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            btn_label = "Active" if is_active else f"View {day.day_short}"
            if st.button(
                btn_label,
                key=f"{key_prefix}_btn_{day.date_iso}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            ):
                st.session_state[selected_date_key] = day.date_iso
                st.rerun()

    return st.session_state.get(selected_date_key)
