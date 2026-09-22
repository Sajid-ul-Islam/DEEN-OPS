"""Modern, human-centric KPI card renderer following the five design principles.

Design Rules Applied:
1. Flat Accents, Not Gradients - Single accent color (#2563eb) for meaning
2. Make the Number the Hero - No colored tiles, data is the visual focus
3. Clear Hierarchy - Primary metric larger, secondary metrics smaller
4. Refined Shadows/Corners - Hairline borders, 6px radii, shadows on floating only
5. Meaningful Data - Explicit time periods, tabular nums, sparkline trends
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from src.components.dashboard.svg import _generate_sparkline_svg
from src.processing.column_detection import (
    EMAIL_COL_CANDIDATES,
    PHONE_COL_CANDIDATES,
    pick_column,
)
from src.processing.data_processing import (
    aggregate_data,
    prepare_granular_data,
    safe_coerce_datetime_naive,
)
from src.utils.customer_registry import compute_new_vs_returning_counts


def render_modern_kpi_cards(
    m_df,
    c_df,
    nav_mode: str,
    dummy_mapping: dict,
    wc_raw_mapping: dict,
):
    """Render modern KPI cards with flat design, clear hierarchy, and meaningful data."""
    if m_df is None:
        m_df = pd.DataFrame()
    if (
        "Category" not in m_df.columns
        or "Product Name" not in m_df.columns
        or "Clean_Product" not in m_df.columns
    ):
        m_df, _ = prepare_granular_data(m_df, wc_raw_mapping)
    if c_df is not None and not c_df.empty:
        if (
            "Category" not in c_df.columns
            or "Product Name" not in c_df.columns
            or "Clean_Product" not in c_df.columns
        ):
            c_df, _ = prepare_granular_data(c_df, wc_raw_mapping)
    else:
        c_df = None

    drill, summ, top, basket = aggregate_data(m_df, dummy_mapping)

    m_qty = m_df["Quantity"].sum() if "Quantity" in m_df.columns else 0
    m_ord = basket["total_orders"] if basket else 0
    m_item_rev = (
        (m_df["Quantity"] * m_df["Item Cost"]).sum()
        if "Quantity" in m_df.columns and "Item Cost" in m_df.columns
        else 0.0
    )

    # Gross Revenue Calculation
    m_gross_rev = (
        float(m_df["Gross Amount"].sum())
        if "Gross Amount" in m_df.columns
        else m_item_rev
    )
    m_gross_bv = (m_gross_rev / m_ord) if m_ord > 0 else 0.0

    dq_str, dr_str, do_str, db_str = None, None, None, None
    pct_q, pct_r, pct_o, pct_b = None, None, None, None
    prev_q_str, prev_r_str, prev_o_str, prev_b_str = None, None, None, None

    if c_df is not None and not c_df.empty:
        co_q = c_df["Quantity"].sum() if "Quantity" in c_df.columns else 0
        co_item_r = (
            (c_df["Quantity"] * c_df["Item Cost"]).sum()
            if "Quantity" in c_df.columns and "Item Cost" in c_df.columns
            else 0.0
        )
        _, _, _, co_basket = aggregate_data(c_df, dummy_mapping)
        co_o = co_basket["total_orders"] if co_basket else 0

        co_gross = (
            float(c_df["Gross Amount"].sum())
            if "Gross Amount" in c_df.columns
            else co_item_r
        )
        co_b = (co_gross / co_o) if co_o > 0 else 0.0

        prefix = "Today " if nav_mode == "Prev" else ""
        suffix = "" if nav_mode == "Prev" else " vs Prev"

        dq = m_qty - co_q
        dr = m_gross_rev - co_gross
        d_o = m_ord - co_o
        db = m_gross_bv - co_b
        if nav_mode == "Prev":
            dq = co_q - m_qty
            dr = co_gross - m_gross_rev
            d_o = co_o - m_ord
            db = co_b - m_gross_bv

        pct_q = (
            ((dq / co_q) * 100)
            if co_q > 0
            else (100.0 if dq > 0 else 0.0 if dq == 0 else -100.0)
        )
        pct_r = (
            ((dr / co_gross) * 100)
            if co_gross > 0
            else (100.0 if dr > 0 else 0.0 if dr == 0 else -100.0)
        )
        pct_o = (
            ((d_o / co_o) * 100)
            if co_o > 0
            else (100.0 if d_o > 0 else 0.0 if d_o == 0 else -100.0)
        )
        pct_b = (
            ((db / co_b) * 100)
            if co_b > 0
            else (100.0 if db > 0 else 0.0 if db == 0 else -100.0)
        )

        dq_str = f"{prefix}{dq:+,.0f}{suffix}"
        dr_str = f"{prefix}{'+' if dr >= 0 else '-'}TK {abs(dr):,.0f}{suffix}"
        do_str = f"{prefix}{d_o:+,.0f}{suffix}"
        db_str = f"{prefix}{'+' if db >= 0 else '-'}TK {abs(db):,.0f}{suffix}"

        prev_q_str = f"{co_q:,.0f}"
        prev_r_str = f"TK {co_gross:,.0f}"
        prev_o_str = f"{co_o:,.0f}"
        prev_b_str = f"TK {int(co_b):,}"

    def format_delta_clean(delta_str, pct_val=None):
        """Format delta with flat color - green for up, red for down."""
        if not delta_str:
            return ""
        is_up = "+" in delta_str
        # Extract just the numeric part without "Today " or " vs Prev"
        clean_delta = delta_str.replace("Today ", "").replace(" vs Prev", "")
        pct_snippet = (
            f" ({pct_val:+.1f}%)"
            if pct_val is not None and not pd.isna(pct_val)
            else ""
        )
        return f'<span class="kpi-delta kpi-delta-{"up" if is_up else "down"}">{clean_delta}{pct_snippet}</span>'

    # Time period label based on nav_mode
    time_period_label = {
        "Today": "Today (BDT)",
        "Yesterday": "Yesterday (BDT)",
        "Last 7 Days": "Last 7 Days (BDT)",
        "Last 30 Days": "Last 30 Days (BDT)",
        "This Month": "This Month (BDT)",
        "Last Month": "Last Month (BDT)",
        "This Year": "Year to Date (BDT)",
        "Backlog": "Current Backlog",
        "Prev": "Previous Period",
    }.get(nav_mode, "Current Period")

    # Format numbers with tabular alignment in mind (monospace-friendly)
    v_qty = f"{int(m_qty):,}"
    v_rev = f"৳{int(m_gross_rev):,}"
    v_ord = f"{int(m_ord):,}"
    v_bv = f"৳{int(m_gross_bv):,}"

    html_dq = format_delta_clean(dq_str, pct_val=pct_q)
    html_dr = format_delta_clean(dr_str, pct_val=pct_r)
    html_do = format_delta_clean(do_str, pct_val=pct_o)
    html_db = format_delta_clean(db_str, pct_val=pct_b)

    # Previous period badge (flat design)
    def _prev_badge(prev_str):
        if not prev_str:
            return ""
        return f'<span class="kpi-prev">Prev: {prev_str}</span>'

    badge_qty = _prev_badge(prev_q_str)
    badge_rev = _prev_badge(prev_r_str)
    badge_ord = _prev_badge(prev_o_str)
    badge_bv = _prev_badge(prev_b_str)

    # Determine extra metric based on mode
    extra_metric_label = "Avg Order Value"
    extra_metric_value = v_bv
    extra_metric_delta = html_db
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

                extra_metric_label = "Oldest Order Age"
                extra_metric_value = f"{hours}h {mins}m"
                extra_metric_delta = (
                    '<span class="kpi-delta kpi-delta-warning">AGING IN QUEUE</span>'
                )
        except Exception:
            pass

    # Generate sparklines for trend visualization
    s_qty, d_qty = "", ""
    s_rev, d_rev = "", ""
    s_ord, d_ord = "", ""
    s_bv, d_bv = "", ""

    if not m_df.empty and nav_mode != "Backlog":
        try:
            full_df = (
                st.session_state.get("wc_full_df")
                if st.session_state.get("wc_full_df") is not None
                and not st.session_state.get("wc_full_df").empty
                else (
                    st.session_state.get("granular_df")
                    if st.session_state.get("granular_df") is not None
                    and not st.session_state.get("granular_df").empty
                    else (
                        st.session_state.get("raw_df")
                        if st.session_state.get("raw_df") is not None
                        and not st.session_state.get("raw_df").empty
                        else m_df
                    )
                )
            )

            date_col = (
                "Date"
                if "Date" in full_df.columns
                else wc_raw_mapping.get("date", "Order Date")
            )
            if date_col not in full_df.columns:
                date_col = next(
                    (
                        c
                        for c in ["Order Date", "Date", "Created Date"]
                        if c in full_df.columns
                    ),
                    full_df.columns[0],
                )

            src_df = full_df.copy()
            src_df["_dt"] = safe_coerce_datetime_naive(src_df[date_col])
            src_df = src_df.dropna(subset=["_dt"])

            order_id_col = wc_raw_mapping.get("order_id", "Order ID")
            if order_id_col not in src_df.columns:
                order_id_col = next(
                    (c for c in ["Order ID", "Order Number"] if c in src_df.columns),
                    src_df.columns[0],
                )

            if "Gross Amount" in src_df.columns:
                src_df["_rev"] = src_df["Gross Amount"]
            elif "Total Amount" in src_df.columns:
                src_df["_rev"] = src_df["Total Amount"]
            else:
                src_df["_rev"] = src_df["Quantity"] * src_df["Item Cost"]

            # 36-hour hourly sparkline series
            src_df["_hr"] = src_df["_dt"].dt.floor("h")

            hour_map_qty = {}
            hour_map_rev = {}
            hour_map_ord = {}

            if not src_df.empty:
                for h_key, grp in src_df.groupby("_hr"):
                    hour_map_qty[h_key] = float(grp["Quantity"].sum())
                    hour_map_rev[h_key] = float(grp["_rev"].sum())
                    hour_map_ord[h_key] = float(grp[order_id_col].nunique())

            end_hr = (
                src_df["_hr"].max()
                if not src_df.empty
                else pd.Timestamp.now().floor("h")
            )
            all_36h = pd.date_range(end=end_hr, periods=36, freq="h")

            t_qty_vals = [hour_map_qty.get(h, 0.0) for h in all_36h]
            t_rev_vals = [hour_map_rev.get(h, 0.0) for h in all_36h]
            t_ord_vals = [hour_map_ord.get(h, 0.0) for h in all_36h]
            t_bv_vals = [
                (r / o if o > 0 else 0)
                for r, o in zip(t_rev_vals, t_ord_vals, strict=True)
            ]

            def _trim_leading_zeros(vals: list[float]) -> list[float]:
                first_nz = next((i for i, v in enumerate(vals) if v > 0), None)
                if first_nz is not None:
                    nz_count = sum(1 for v in vals if v > 0)
                    if nz_count < 2:
                        return []
                    trimmed = vals[first_nz:]
                    if len(trimmed) >= 2:
                        return trimmed
                return []

            t_qty_vals = _trim_leading_zeros(t_qty_vals)
            t_rev_vals = _trim_leading_zeros(t_rev_vals)
            t_ord_vals = _trim_leading_zeros(t_ord_vals)
            t_bv_vals = _trim_leading_zeros(t_bv_vals)

            from src.config.ui_config import CHART_THEMES

            theme_name = st.session_state.get("chart_theme", "✨ Emerald Cyberpunk")
            theme_cfg = CHART_THEMES.get(
                theme_name, CHART_THEMES["✨ Emerald Cyberpunk"]
            )

            # Use flat colors from theme
            s_qty, d_qty = _generate_sparkline_svg(
                t_qty_vals,
                theme_cfg.get("spark_qty", "#06b6d4"),
                prefix="",
                suffix="",
                title="36-hour trend",
            )
            s_rev, d_rev = _generate_sparkline_svg(
                t_rev_vals,
                theme_cfg.get("spark_rev", "#10b981"),
                prefix="৳",
                suffix="",
                title="36-hour trend",
            )
            s_ord, d_ord = _generate_sparkline_svg(
                t_ord_vals,
                theme_cfg.get("spark_ord", "#3b82f6"),
                prefix="",
                suffix="",
                title="36-hour trend",
            )
            s_bv, d_bv = _generate_sparkline_svg(
                t_bv_vals,
                theme_cfg.get("spark_bv", "#f59e0b"),
                prefix="৳",
                suffix="",
                title="36-hour trend",
            )
        except Exception:
            pass

    # Customer mix calculation
    m_new_cnt, m_ret_cnt = 0, 0
    s_cust, d_cust = "", ""
    v_cust = "0 New / 0 Ret"

    if not m_df.empty and nav_mode != "Backlog":
        try:
            phone_col = pick_column(m_df, PHONE_COL_CANDIDATES)
            email_col = pick_column(m_df, EMAIL_COL_CANDIDATES)
            cust_col = phone_col or email_col

            if cust_col:
                m_new_cnt, m_ret_cnt = compute_new_vs_returning_counts(
                    m_df, m_df, wc_raw_mapping
                )
                tot_cust = m_new_cnt + m_ret_cnt
                if tot_cust > 0:
                    v_cust = f"{m_new_cnt} New / {m_ret_cnt} Ret"
        except Exception:
            pass

    # Build HTML with clear hierarchy:
    # - Primary metric (Revenue) is larger
    # - Secondary metrics (Orders, Items, AOV, Customers) are smaller

    # Helper to build individual KPI card HTML
    def build_kpi_card(
        label, value, delta_html, sparkline_html, prev_badge_html, is_primary=False
    ):
        """Build a single KPI card with flat design."""
        size_class = "kpi-card-primary" if is_primary else "kpi-card-secondary"
        return (
            f'<div class="kpi-card {size_class}">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value {"kpi-value-primary" if is_primary else ""}">{value}</div>'
            f"{prev_badge_html}"
            f"{delta_html}"
            f"{sparkline_html}"
            "</div>"
        )

    # Build the KPI container with hierarchy
    # Primary: Net Revenue (largest, most important)
    # Secondary: Orders, Items, AOV, Customer Mix (smaller)

    card_html = (
        '<div class="kpi-container">'
        # PRIMARY METRIC - Revenue (largest, leftmost)
        f"{build_kpi_card(f'Gross Revenue · {time_period_label}', v_rev, html_dr, s_rev + d_rev, badge_rev, is_primary=True)}"
        # SECONDARY METRICS
        f"{build_kpi_card('Orders', v_ord, html_do, s_ord + d_ord, badge_ord)}"
        f"{build_kpi_card('Items Sold', v_qty, html_dq, s_qty + d_qty, badge_qty)}"
        f"{build_kpi_card(extra_metric_label, extra_metric_value, extra_metric_delta, s_bv + d_bv if nav_mode != 'Backlog' else '', badge_bv)}"
        f"{build_kpi_card('Customers', v_cust, '', s_cust + d_cust, '')}"
        "</div>"
    )

    st.markdown(card_html, unsafe_allow_html=True)

    return drill, summ, top, basket
