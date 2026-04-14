"""Dashboard snapshot — exports a PNG metrics-summary card with optional kaleido support."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ── Metric computation ────────────────────────────────────────────────────────

def compute_snapshot_metrics(
    granular_df: pd.DataFrame | None,
    basket_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute a snapshot of core metrics from the current dashboard state."""
    tz_bd = timezone(timedelta(hours=6))
    snapshot: dict[str, Any] = {
        "timestamp": datetime.now(tz_bd).isoformat(),
        "core": {
            "total_qty": 0,
            "total_revenue": 0,
            "total_orders": 0,
            "avg_basket_value": 0,
        },
        "volume_by_category": {},
        "revenue_by_category": {},
    }

    if granular_df is None or granular_df.empty:
        return snapshot

    qty = granular_df["Quantity"].sum() if "Quantity" in granular_df.columns else 0
    revenue = (
        (granular_df["Quantity"] * granular_df["Item Cost"]).sum()
        if {"Quantity", "Item Cost"}.issubset(granular_df.columns)
        else 0
    )

    snapshot["core"]["total_qty"] = int(qty)
    snapshot["core"]["total_revenue"] = float(revenue)

    if basket_metrics:
        snapshot["core"]["total_orders"] = int(basket_metrics.get("total_orders", 0))
        snapshot["core"]["avg_basket_value"] = round(
            float(basket_metrics.get("avg_basket_value", 0)), 2
        )

    if "Category" in granular_df.columns:
        vol = granular_df.groupby("Category")["Quantity"].sum()
        snapshot["volume_by_category"] = {k: int(v) for k, v in vol.items()}

        if "Item Cost" in granular_df.columns:
            rev = granular_df.copy()
            rev["_rev"] = rev["Quantity"] * rev["Item Cost"]
            rev_by_cat = rev.groupby("Category")["_rev"].sum()
            snapshot["revenue_by_category"] = {
                k: round(float(v), 2) for k, v in rev_by_cat.items()
            }

    return snapshot


# ── PNG card builder ──────────────────────────────────────────────────────────

def _build_snapshot_png(metrics: dict[str, Any]) -> bytes | None:
    """Render a styled metrics-summary card as a PNG using Plotly."""
    try:
        core = metrics.get("core", {})
        ts = metrics.get("timestamp", "")

        total_rev = f"TK {core.get('total_revenue', 0):,.0f}"
        total_qty = f"{core.get('total_qty', 0):,}"
        total_ord = f"{core.get('total_orders', 0):,}"
        avg_bv = f"TK {core.get('avg_basket_value', 0):,.0f}"

        vol_by_cat = metrics.get("volume_by_category", {})
        rev_by_cat = metrics.get("revenue_by_category", {})

        cats = sorted(set(list(vol_by_cat.keys()) + list(rev_by_cat.keys())))
        cat_col = cats if cats else ["—"]
        vol_col = [f"{vol_by_cat.get(c, 0):,}" for c in cats] if cats else ["—"]
        rev_col = [f"{rev_by_cat.get(c, 0):,.0f}" for c in cats] if cats else ["—"]

        BG = "#0f172a"
        CARD = "#1e293b"
        ACCENT = "#3b82f6"
        TEXT = "#f1f5f9"
        MUTED = "#94a3b8"

        fig = go.Figure()

        fig.add_annotation(
            x=0.5, y=0.97, xref="paper", yref="paper",
            text="<b>📊 Dashboard Snapshot</b>", showarrow=False,
            font=dict(size=22, color=TEXT, family="Arial")
        )

        fig.add_trace(go.Table(
            domain=dict(x=[0.0, 1.0], y=[0.72, 0.90]),
            header=dict(
                values=["<b>Revenue</b>", "<b>Items Sold</b>", "<b>Orders</b>", "<b>Avg Basket</b>"],
                fill_color=ACCENT, align="center", font=dict(color=TEXT)
            ),
            cells=dict(
                values=[[total_rev], [total_qty], [total_ord], [avg_bv]],
                fill_color=CARD, align="center", font=dict(color=TEXT, size=14)
            )
        ))

        if cats:
            fig.add_trace(go.Table(
                domain=dict(x=[0.0, 1.0], y=[0.02, 0.68]),
                header=dict(
                    values=["<b>Category</b>", "<b>Qty</b>", "<b>Revenue</b>"],
                    fill_color="#1d4ed8", align="left", font=dict(color=TEXT)
                ),
                cells=dict(
                    values=[cat_col, vol_col, rev_col],
                    fill_color=CARD, align="left", font=dict(color=TEXT)
                )
            ))

        fig.update_layout(paper_bgcolor=BG, plot_bgcolor=BG, width=800, height=520, margin=dict(l=20, r=20, t=20, b=20))
        
        # This is where it might crash if kaleido is broken
        return fig.to_image(format="png")
    except Exception:
        return None


# ── Public widget ─────────────────────────────────────────────────────────────

def render_snapshot_button(
    granular_df: pd.DataFrame | None = None,
    basket_metrics: dict[str, Any] | None = None,
) -> None:
    """Render a download button for a PNG snapshot or JSON fallback."""
    metrics = compute_snapshot_metrics(granular_df, basket_metrics)

    # Attempt PNG build
    png_bytes = None
    if "kaleido" in st.session_state.get("_kaleido_check", "unknown"):
         png_bytes = _build_snapshot_png(metrics)
    else:
        # One-time check to see if kaleido works without crashing the process
        try:
            import kaleido
            st.session_state["_kaleido_check"] = "kaleido_present"
            png_bytes = _build_snapshot_png(metrics)
        except Exception:
            st.session_state["_kaleido_check"] = "kaleido_failed"

    if png_bytes:
        data = png_bytes
        file_name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M')}.png"
        mime = "image/png"
        label = "📸 Save Snapshot (PNG)"
    else:
        # Fallback to JSON
        data = json.dumps(metrics, indent=2, default=str).encode()
        file_name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        mime = "application/json"
        label = "💾 Save Snapshot (JSON)"
        if st.session_state.get("_kaleido_check") == "kaleido_failed":
             st.caption("⚠️ PNG export failed (kaleido error). Saving as JSON.")

    col1, col2 = st.columns([4, 1])
    with col2:
        st.download_button(
            label=label,
            data=data,
            file_name=file_name,
            mime=mime,
            use_container_width=True,
            key=f"snap_btn_{datetime.now().microsecond}" # Force refresh if needed
        )
