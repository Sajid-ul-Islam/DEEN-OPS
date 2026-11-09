"""7-Day Rolling Dispatch History Timeline Component.

Renders an interactive 7-day timeline banner with operational dispatch cards:
- Rolling 7-day shipped order volume and daily dispatch average
- Daily day-cards with authoritative shipped/completed order counts
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

    # Clean, uncluttered operational benchmark
    col_bench1, col_bench2 = st.columns([1, 1])
    with col_bench1:
        ex_diff = report.total_7d_orders - report.total_7d_regular_orders
        if ex_diff > 0:
            st.caption(
                f"📦 7-Day Shipped Orders: **{report.total_7d_regular_orders}** (+{ex_diff} exchanges)"
            )
        else:
            st.caption(f"📦 7-Day Shipped Orders: **{report.total_7d_orders}**")
    with col_bench2:
        st.caption(
            f"📈 Daily Dispatch Avg: **{report.avg_7d_regular_orders:.1f} orders/day**"
        )

    # Render day cards horizontally in 7 columns
    selected_date_key = f"{key_prefix}_selected"
    current_selected = st.session_state.get(selected_date_key)

    # Scoped banner if historical day is active
    selected_day = next(
        (d for d in report.days if d.date_iso == current_selected), None
    )
    if selected_day and not selected_day.is_today:
        col_scoped1, col_scoped2 = st.columns([0.78, 0.22])
        with col_scoped1:
            st.info(
                f"📅 **Scoped to {selected_day.date_label}** ({selected_day.order_count} dispatches). "
                "All KPI metrics, charts, and product data below reflect this day."
            )
        with col_scoped2:
            today_iso = next(
                (d.date_iso for d in report.days if d.is_today),
                report.days[-1].date_iso,
            )
            if st.button(
                "🔄 Reset to Today",
                key=f"{key_prefix}_reset_today",
                use_container_width=True,
            ):
                st.session_state[selected_date_key] = today_iso
                st.rerun()

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

            date_display = (
                day.date_label.split(",")[1].strip()
                if "," in day.date_label
                else day.date_iso
            )
            if day.exchange_count > 0:
                reg_cnt = day.regular_order_count or (
                    day.order_count - day.exchange_count
                )
                orders_line = f'{reg_cnt} <span style="font-size: 11px; font-weight: 600; color: #2563eb;">orders</span> <span style="font-size: 10px; font-weight: 700; color: #7c3aed; background: rgba(124,58,237,0.1); padding: 1px 4px; border-radius: 4px;">+{day.exchange_count} ex</span>'
            else:
                orders_line = f'{day.order_count} <span style="font-size: 11px; font-weight: 600; color: #2563eb;">orders</span>'

            st.markdown(
                f"""
                <div style="border: {border}; background: {bg}; border-radius: 8px; padding: 10px 6px; text-align: center; margin-bottom: 6px;">
                    <div style="font-size: 11px; font-weight: 700; color: #64748b; letter-spacing: 0.05em;">{tag}</div>
                    <div style="font-size: 13px; font-weight: 700; color: #1e293b; margin: 2px 0;">{date_display} ({day.day_short})</div>
                    <div style="font-size: 18px; font-weight: 800; color: #0f172a; margin-top: 4px;">{orders_line}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            btn_label = (
                f"Viewing {day.day_short}" if is_active else f"View {day.day_short}"
            )
            if st.button(
                btn_label,
                key=f"{key_prefix}_btn_{day.date_iso}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            ):
                st.session_state[selected_date_key] = day.date_iso
                st.rerun()

    return st.session_state.get(selected_date_key)
