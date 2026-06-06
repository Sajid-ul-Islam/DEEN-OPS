"""Passive live banner showing real-time stats from the current shift."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_live_banner() -> None:
    """Display a compact HUD-style banner with today's live stats from ``wc_curr_df``.

    Shows nothing if no live data is available in session state.
    Computes: order count, revenue, and pending order count.
    """
    df: pd.DataFrame | None = st.session_state.get("wc_curr_df")
    if df is None or df.empty:
        return

    # Exclude pending payments, cancelled, and failed orders from live banner totals
    if "Order Status" in df.columns:
        df = df[~df["Order Status"].astype(str).str.lower().isin(
            ["pending", "pending payment", "cancelled", "failed", "refunded", "trash"]
        )]

    try:
        qty = int(df["Quantity"].sum()) if "Quantity" in df.columns else 0

        revenue = 0.0
        if {"Quantity", "Item Cost"}.issubset(df.columns):
            revenue = float((df["Quantity"] * df["Item Cost"]).sum())

        order_col = "Order ID" if "Order ID" in df.columns else "Order Number"
        orders = int(df[order_col].nunique()) if order_col in df.columns else 0

        pending = 0
        if "Order Status" in df.columns:
            pending = int(
                df[df["Order Status"].isin(["processing", "on-hold"])][order_col].nunique()
            ) if order_col in df.columns else 0

        # Build rich HUD badge HTML
        badge_style = (
            "display:inline-flex; align-items:center; gap:5px; "
            "padding:3px 10px; border-radius:20px; font-size:0.72rem; font-weight:700; "
            "letter-spacing:0.04em; white-space:nowrap;"
        )

        orders_chip = (
            f'<span style="{badge_style} background:rgba(59,130,246,0.15); '
            f'border:1px solid rgba(59,130,246,0.3); color:#60a5fa;">'
            f'🛒 {orders} orders</span>'
        )
        revenue_chip = (
            f'<span style="{badge_style} background:rgba(16,185,129,0.15); '
            f'border:1px solid rgba(16,185,129,0.3); color:#34d399;">'
            f'৳ {revenue:,.0f}</span>'
        )
        qty_chip = (
            f'<span style="{badge_style} background:rgba(99,102,241,0.12); '
            f'border:1px solid rgba(99,102,241,0.25); color:#818cf8;">'
            f'📦 {qty} units</span>'
        )
        pending_chip = ""
        if pending:
            pending_chip = (
                f'<span style="{badge_style} background:rgba(245,158,11,0.15); '
                f'border:1px solid rgba(245,158,11,0.3); color:#fbbf24;">'
                f'⚙️ {pending} processing</span>'
            )

        status_dot = (
            '<span style="display:inline-block; width:7px; height:7px; border-radius:50%; '
            'background:#10b981; margin-right:6px; animation:statusPulse 2s ease-in-out infinite; '
            'flex-shrink:0;"></span>'
        )

        st.markdown(
            f'<div style="'
            f'display:flex; align-items:center; gap:8px; flex-wrap:wrap; '
            f'background:rgba(8,14,30,0.6); backdrop-filter:blur(12px); '
            f'border:1px solid rgba(59,130,246,0.15); border-radius:10px; '
            f'padding:7px 14px; margin-bottom:8px; '
            f'box-shadow:0 4px 20px -4px rgba(0,0,0,0.4);">'
            f'{status_dot}'
            f'<span style="font-size:0.65rem; font-weight:800; letter-spacing:0.15em; '
            f'color:rgba(148,163,184,0.6); text-transform:uppercase; margin-right:4px;">Live</span>'
            f'{orders_chip}{revenue_chip}{qty_chip}{pending_chip}'
            f'</div>',
            unsafe_allow_html=True,
        )
    except Exception:
        # Silently skip banner if data is malformed
        pass
