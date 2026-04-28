"""Passive live banner showing real-time stats from the current shift."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_live_banner() -> None:
    """Display a compact banner with today's live stats from ``wc_curr_df``.

    Shows nothing if no live data is available in session state.
    Computes: order count, revenue, and pending order count.
    """
    df: pd.DataFrame | None = st.session_state.get("wc_curr_df")
    if df is None or df.empty:
        return

    # Exclude pending payments, cancelled, and failed orders from live banner totals
    if "Order Status" in df.columns:
        df = df[~df["Order Status"].astype(str).str.lower().isin(["pending", "pending payment", "cancelled", "failed", "refunded", "trash"])]

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

        parts = [
            f"Today: {orders} orders",
            f"\u09f3{revenue:,.0f} revenue",
        ]
        if pending:
            parts.append(f"{pending} pending")

        banner_text = " | ".join(parts)
        st.markdown(
            f'<div style="background:#1e293b; color:#94a3b8; padding:4px 14px; '
            f'border-radius:6px; font-size:12px; text-align:center; margin-bottom:4px;">'
            f'{banner_text}</div>',
            unsafe_allow_html=True,
        )
    except Exception:
        # Silently skip banner if data is malformed
        pass
