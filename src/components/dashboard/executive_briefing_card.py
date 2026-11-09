"""Executive Briefing Visual Card & Clipboard Generator.

Renders structured executive briefing cards with toggle between:
1. Modern metric chip grid (Volume, Financials, Selects Portfolio Share, Courier Hand-off)
2. Formatted Markdown briefing text ready for instant copy to WhatsApp/Slack/Telegram
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import streamlit as st

from src.config.constants import bd_now


def render_executive_briefing_card(
    revenue: float,
    items_count: int,
    orders_count: int,
    aov: float,
    dispatch_metrics: dict[str, Any] | None = None,
    top_products_df: pd.DataFrame | None = None,
    selects_stats: dict[str, Any] | None = None,
    title: str = "Executive Shift Briefing",
    key_prefix: str = "exec_briefing",
) -> None:
    """Render executive briefing view with visual chips and copyable text.

    Args:
        revenue: Total revenue in BDT.
        items_count: Total garments/units sold.
        orders_count: Total number of orders.
        aov: Average order value in BDT.
        dispatch_metrics: Dispatch metrics dict (dispatched, pending, rate).
        top_products_df: DataFrame of top products.
        selects_stats: Stats for DEEN Selects luxury line vs Regular.
        title: Title of briefing section.
        key_prefix: Key prefix for session state widgets.
    """
    st.markdown(f"#### 👔 {title}")

    dm = dispatch_metrics or {}
    dispatched = dm.get("dispatched", 0)
    pending = dm.get("pending", 0)
    dispatch_rate = dm.get("dispatch_rate", 0.0)

    # Calculate Selects metrics if available
    sel_share_pct = 0.0
    sel_rev = 0.0
    if selects_stats:
        sel_rev = float(selects_stats.get("selects_revenue", 0.0))
        sel_share_pct = float(selects_stats.get("revenue_share_pct", 0.0))

    # View Mode toggle: Visual Grid vs Text Format
    mode = st.radio(
        "Briefing View Mode",
        ["Visual Grid", "Copyable Text"],
        horizontal=True,
        key=f"{key_prefix}_view_mode",
        label_visibility="collapsed",
    )

    if mode == "Visual Grid":
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 1px solid #86efac; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #166534; text-transform: uppercase;">💰 Revenue & Value</div>
                    <div style="font-size: 20px; font-weight: 800; color: #14532d; margin-top: 4px;">৳ {revenue:,.0f}</div>
                    <div style="font-size: 12px; color: #15803d; margin-top: 2px;">AOV: <strong>৳ {aov:,.0f}</strong></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            items_per_order = (
                round(items_count / orders_count, 1) if orders_count > 0 else 0.0
            )
            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); border: 1px solid #93c5fd; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #1e40af; text-transform: uppercase;">📦 Order Volume</div>
                    <div style="font-size: 20px; font-weight: 800; color: #1e3a8a; margin-top: 4px;">{orders_count:,} <span style="font-size: 13px; font-weight: 600;">orders</span></div>
                    <div style="font-size: 12px; color: #2563eb; margin-top: 2px;">{items_count:,} units ({items_per_order}/ord)</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%); border: 1px solid #d8b4fe; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #6b21a8; text-transform: uppercase;">💎 DEEN Selects Share</div>
                    <div style="font-size: 20px; font-weight: 800; color: #581c87; margin-top: 4px;">{sel_share_pct:.1f}%</div>
                    <div style="font-size: 12px; color: #7e22ce; margin-top: 2px;">৳ {sel_rev:,.0f} luxury tier</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border: 1px solid #fde68a; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #92400e; text-transform: uppercase;">🚚 Dispatch Hand-off</div>
                    <div style="font-size: 20px; font-weight: 800; color: #78350f; margin-top: 4px;">{dispatch_rate:.0f}%</div>
                    <div style="font-size: 12px; color: #b45309; margin-top: 2px;">{dispatched} shipped · {pending} pending</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Top product highlight
        if top_products_df is not None and not top_products_df.empty:
            top_row = top_products_df.iloc[0]
            name = top_row.get("Product Name", top_row.get("name", "Product"))
            qty = int(top_row.get("Total Qty", top_row.get("Quantity", 0)))
            amt = float(top_row.get("Total Amount", top_row.get("Line Total", 0.0)))
            st.caption(
                f"🔥 **Leading Seller:** {name} — **{qty:,} units** (৳ {amt:,.0f})"
            )

    else:
        # Formatted copyable text
        top_lines = ""
        if top_products_df is not None and not top_products_df.empty:
            for _, r in top_products_df.head(3).iterrows():
                p_name = r.get("Product Name", r.get("name", "Item"))
                p_qty = int(r.get("Total Qty", r.get("Quantity", 0)))
                p_amt = float(r.get("Total Amount", r.get("Line Total", 0.0)))
                top_lines += f"  • {p_name}: {p_qty} pcs (৳ {p_amt:,.0f})\n"

        briefing_text = (
            f"📊 *DEEN ENTERPRISE — EXECUTIVE BRIEFING*\n"
            f"📅 As of: {bd_now().strftime('%d %b %Y, %I:%M %p')} (BDT)\n\n"
            f"💰 *Financial Performance:*\n"
            f"  • Gross Revenue: ৳ {revenue:,.0f}\n"
            f"  • Orders: {orders_count:,}\n"
            f"  • Units Sold: {items_count:,}\n"
            f"  • AOV: ৳ {aov:,.0f}\n\n"
            f"💎 *DEEN Selects:* {sel_share_pct:.1f}% share (৳ {sel_rev:,.0f})\n"
            f"🚚 *Logistics:* {dispatched} dispatched ({dispatch_rate:.0f}%) | {pending} pending\n"
        )
        if top_lines:
            briefing_text += f"\n🔥 *Top Styles:*\n{top_lines}"

        from src.components.ui.clipboard import render_copy_button

        col_cp, _ = st.columns([0.3, 0.7])
        with col_cp:
            render_copy_button(briefing_text, label="📋 Copy Briefing Text")
        st.code(briefing_text, language="text")
