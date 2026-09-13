"""Operational metrics rendering: KPI cards, deltas, and status breakdown."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import pandas as pd
import streamlit as st

from src.components.dashboard.svg import _generate_sparkline_svg
from src.processing.column_detection import (
    EMAIL_COL_CANDIDATES,
    ORDER_ID_COL_CANDIDATES,
    PHONE_COL_CANDIDATES,
    pick_column,
)
from src.processing.data_processing import (
    aggregate_data,
    prepare_granular_data,
    safe_coerce_datetime_naive,
)
from src.utils.customer_registry import (
    compute_new_vs_returning_counts,
    get_customer_first_order_date,
    load_customer_registry,
    normalize_phone_key,
)
from src.utils.logging import log_system_event
from src.utils.metric_history import save_shift_snapshot


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

    active_df = m_df
    drill, summ, top, basket = aggregate_data(m_df, dummy_mapping)

    m_qty = m_df["Quantity"].sum() if "Quantity" in m_df.columns else 0
    m_ord = basket["total_orders"] if basket else 0
    m_item_rev = (
        (m_df["Quantity"] * m_df["Item Cost"]).sum()
        if "Quantity" in m_df.columns and "Item Cost" in m_df.columns
        else 0.0
    )

    # ── Robust Gross Revenue, Cashback, and Net Revenue Calculation ──
    # ``prepare_granular_data`` (called above) guarantees ``Cashback Discount``,
    # ``Gross Amount`` and ``Total Amount`` columns already exist on ``m_df`` and
    # ``c_df``, so these are the single source of truth (no secondary derivation).
    m_cashback_disc = (
        float(m_df["Cashback Discount"].sum())
        if "Cashback Discount" in m_df.columns
        else 0.0
    )
    m_gross_rev = (
        float(m_df["Gross Amount"].sum())
        if "Gross Amount" in m_df.columns
        else m_item_rev
    )

    # Net Revenue = Gross Revenue - Cashback/Discount Fees
    m_net_rev = max(0.0, m_gross_rev - m_cashback_disc)

    m_loss_pct = (m_cashback_disc / m_gross_rev * 100) if m_gross_rev > 0 else 0.0
    m_gross_bv = (m_gross_rev / m_ord) if m_ord > 0 else 0.0
    m_net_bv = (m_net_rev / m_ord) if m_ord > 0 else 0.0
    m_cb_per_basket = (m_cashback_disc / m_ord) if m_ord > 0 else 0.0
    m_bv = m_gross_bv

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

        co_cb = (
            float(c_df["Cashback Discount"].sum())
            if "Cashback Discount" in c_df.columns
            else 0.0
        )
        co_gross = (
            float(c_df["Gross Amount"].sum())
            if "Gross Amount" in c_df.columns
            else co_item_r
        )
        co_net_r = max(0.0, co_gross - co_cb)
        co_b = (co_gross / co_o) if co_o > 0 else 0.0

        dashboard_view = st.session_state.get("live_dashboard_view")
        if dashboard_view in {"Last Day Shipped", "Last Day"}:
            prefix = ""
            suffix = " vs Prior"
            dq = m_qty - co_q
            dr = m_gross_rev - co_gross
            d_o = m_ord - co_o
            db = m_gross_bv - co_b
            cmp_label = "Day Prior"
        elif nav_mode == "Prev":
            prefix = "Today "
            suffix = ""
            dq = co_q - m_qty
            dr = co_gross - m_gross_rev
            d_o = co_o - m_ord
            db = co_b - m_gross_bv
            cmp_label = "Today"
        else:
            from src.config.constants import bd_today
            from src.processing.data_processing import get_previous_working_day

            prev_w_day = get_previous_working_day(bd_today())
            prev_abbr = prev_w_day.strftime("%a")
            prefix = ""
            suffix = f" vs {prev_abbr}"
            dq = m_qty - co_q
            dr = m_gross_rev - co_gross
            d_o = m_ord - co_o
            db = m_gross_bv - co_b
            cmp_label = prev_w_day.strftime("%A")

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

    def format_delta(delta_str, prev_val_str=None, pct_val=None):
        if not delta_str:
            return ""
        is_up = "+" in delta_str
        cls = "delta-up" if is_up else "delta-down"
        arrow = "▲" if is_up else "▼"
        pct_snippet = (
            f" ({pct_val:+.1f}%)"
            if pct_val is not None and not pd.isna(pct_val)
            else ""
        )
        prev_snippet = (
            f' <span class="delta-prev">(Prev: {prev_val_str})</span>'
            if prev_val_str
            else ""
        )
        return f'<div class="metric-delta {cls}">{arrow} {delta_str}{pct_snippet}{prev_snippet}</div>'

    v_qty = f"{m_qty:,.0f}"
    v_rev = f"TK {m_gross_rev:,.0f}"
    v_ord = f"{m_ord:,.0f}"
    v_bv = f"TK {int(m_gross_bv):,}"

    html_dq = format_delta(dq_str, prev_val_str=prev_q_str, pct_val=pct_q)
    html_dr = format_delta(dr_str, prev_val_str=prev_r_str, pct_val=pct_r)
    html_do = format_delta(do_str, prev_val_str=prev_o_str, pct_val=pct_o)
    html_db = format_delta(db_str, prev_val_str=prev_b_str, pct_val=pct_b)

    # ── "Last Day" Comparison Badges ─────────────────────────────────────
    # Prominent badges showing the previous period's absolute values,
    # placed between the main value and the delta on each KPI card.
    def _last_day_badge(prev_str, label="Last Day", color="#64748b"):
        if not prev_str:
            return ""
        return (
            f'<div style="font-size:0.68rem;font-weight:600;color:{color};'
            f"background:rgba(100,116,139,0.08);padding:2px 7px;"
            f"border-radius:4px;margin-top:5px;display:inline-block;"
            f'letter-spacing:0.02em;">'
            f"📅 {label}: {prev_str}</div>"
        )

    cmp_badge_label = cmp_label if "cmp_label" in locals() else "Last Day"
    badge_qty = _last_day_badge(prev_q_str, label=cmp_badge_label)
    badge_rev = _last_day_badge(prev_r_str, label=cmp_badge_label)
    badge_ord = _last_day_badge(prev_o_str, label=cmp_badge_label)
    badge_bv = _last_day_badge(prev_b_str, label=cmp_badge_label)

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

    # ── Last 7-Days KPI Sparkline Extraction ──
    # Initialize all sparkline and customer mix variables to safe defaults
    m_new_cnt, m_ret_cnt = 0, 0
    s_cust, d_cust = "", ""
    s_qty, s_rev, s_ord, s_bv = "", "", "", ""
    d_qty, d_rev, d_ord, d_bv, d_cust = "", "", "", "", ""
    if not m_df.empty and nav_mode != "Backlog":
        try:
            # 1. Fetch the multi-day source DataFrame from session state if available, fallback to m_df
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

            # ── 36-hour hourly sparkline series (orders & products sold per hour) ──
            src_df["_hr"] = src_df["_dt"].dt.floor("h")

            hour_map_qty = {}
            hour_map_rev = {}
            hour_map_ord = {}

            if not src_df.empty:
                for h_key, grp in src_df.groupby("_hr"):
                    hour_map_qty[h_key] = float(grp["Quantity"].sum())
                    hour_map_rev[h_key] = float(grp["_rev"].sum())
                    hour_map_ord[h_key] = float(grp[order_id_col].nunique())

            # Window end = latest data hour (falls back to now), 36h span.
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

            # Trim leading zeros (data collection started recently).
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

            # ── New vs Returning Customer Calculation (Lifetime Registry Integrated) ──
            try:
                # NOTE: the authoritative counts come from
                # compute_new_vs_returning_counts() below, which already refreshes
                # BOTH the full 3-bucket registry and the legacy flat registry
                # from full_df. Do NOT call update_customer_registry() here as
                # well — it duplicated the same disk I/O on every render.
                phone_col = pick_column(m_df, PHONE_COL_CANDIDATES)
                email_col = pick_column(m_df, EMAIL_COL_CANDIDATES)
                cust_col = phone_col or email_col

                if cust_col and not full_df.empty:
                    full_dt_col = (
                        "Date"
                        if "Date" in full_df.columns
                        else wc_raw_mapping.get("date", "Order Date")
                    )
                    if full_dt_col not in full_df.columns:
                        full_dt_col = next(
                            (c for c in ["Order Date", "Date"] if c in full_df.columns),
                            full_df.columns[0],
                        )

                    f_df = full_df.copy()
                    f_df["_dt"] = safe_coerce_datetime_naive(f_df[full_dt_col])
                    f_df["_norm_cust"] = f_df[cust_col].apply(normalize_phone_key)
                    f_df = f_df.dropna(subset=["_dt"])
                    f_df = f_df[f_df["_norm_cust"] != ""]

                    if not m_df.empty and cust_col in m_df.columns:
                        # first_order_map is still needed by the 7-day sparkline below.
                        active_dt_col = (
                            "Date"
                            if "Date" in m_df.columns
                            else wc_raw_mapping.get("date", "Order Date")
                        )
                        t_act = m_df.copy()
                        t_act["_dt"] = safe_coerce_datetime_naive(t_act[active_dt_col])
                        t_act["_norm_cust"] = t_act[cust_col].apply(normalize_phone_key)
                        order_id_col = wc_raw_mapping.get("order_id", "Order ID")
                        if order_id_col not in t_act.columns:
                            order_id_col = pick_column(
                                t_act, ORDER_ID_COL_CANDIDATES, t_act.columns[0]
                            )
                        first_order_map = (
                            t_act.dropna(subset=["_dt"])
                            .query("_norm_cust != ''")
                            .groupby("_norm_cust")["_dt"]
                            .min()
                            .to_dict()
                        )

                        # Authoritative new vs returning using the full 3-bucket
                        # registry (email -> phone -> name/city). This is the same
                        # source the Customer Insights panels use, and it correctly
                        # detects returning customers whose earlier order was keyed
                        # by a different identity (e.g. email) than the current one.
                        # The legacy flat-registry + session-window loop below
                        # under-counted returning customers (it only saw phone keys
                        # within the cached window).
                        m_new_cnt, m_ret_cnt = compute_new_vs_returning_counts(
                            m_df, full_df, wc_raw_mapping
                        )

                    # 7-Day % New Customers Sparkline
                    if not f_df.empty:
                        f_df["_day"] = f_df["_dt"].dt.floor("d")
                        order_id_col = wc_raw_mapping.get("order_id", "Order ID")
                        if order_id_col not in f_df.columns:
                            order_id_col = next(
                                (
                                    c
                                    for c in ["Order ID", "Order Number"]
                                    if c in f_df.columns
                                ),
                                f_df.columns[0],
                            )

                        # Read-only lifetime lookup for the 7-day sparkline
                        # (registry refresh itself is owned by
                        # compute_new_vs_returning_counts() above).
                        lifetime_registry = load_customer_registry()

                        day_map_total = defaultdict(int)
                        day_map_new = defaultdict(int)

                        for d_key, d_grp in f_df.groupby("_day"):
                            d_uniq = d_grp.drop_duplicates(subset=[order_id_col])
                            day_map_total[d_key] = len(d_uniq)

                            for _, drow in d_uniq.iterrows():
                                c_id = drow.get("_norm_cust")
                                d_dt = drow.get("_dt")
                                first_dt = first_order_map.get(c_id, d_dt)
                                reg_dt = get_customer_first_order_date(
                                    c_id, lifetime_registry
                                )
                                if reg_dt and (pd.isna(first_dt) or reg_dt < first_dt):
                                    first_dt = reg_dt

                                if pd.isna(first_dt) or first_dt.floor("d") == d_key:
                                    day_map_new[d_key] += 1

                        today_dt = f_df["_day"].max()
                        all_7days = pd.date_range(end=today_dt, periods=7, freq="d")

                        t_new_vals = []
                        t_ret_vals = []
                        for d in all_7days:
                            d_tot = day_map_total.get(d, 0)
                            d_new = day_map_new.get(d, 0)

                            if d == today_dt and (m_new_cnt + m_ret_cnt) > 0:
                                d_tot = m_new_cnt + m_ret_cnt
                                d_new = m_new_cnt

                            d_ret = max(0, d_tot - d_new)

                            pct_new = (d_new / d_tot * 100.0) if d_tot > 0 else 0.0
                            pct_ret = (d_ret / d_tot * 100.0) if d_tot > 0 else 0.0

                            t_new_vals.append(pct_new)
                            t_ret_vals.append(pct_ret)

                        t_new_vals = _trim_leading_zeros(t_new_vals)
                        t_ret_vals = _trim_leading_zeros(t_ret_vals)
                        # Pure-gradient sparkline of the 7-day new-customer trend
                        # (matches the other metric cards' minimal visual style).
                        s_cust, _ = _generate_sparkline_svg(
                            t_new_vals,
                            color="#a855f7",
                            prefix="",
                            suffix="%",
                            title="7-day trend",
                        )
                        d_cust = ""
            except Exception as e:
                log_system_event(
                    "CUSTOMER_MIX_ERROR", f"Failed to compute customer mix: {e}"
                )
        except Exception as e:
            log_system_event("SPARKLINE_ERROR", f"Failed to generate sparklines: {e}")

    # % of unique orders with cashback
    _ord_id_col = next(
        (c for c in ["Order ID", "Order Number"] if c in m_df.columns), None
    )
    if _ord_id_col and m_cashback_disc > 0 and "Cashback Discount" in m_df.columns:
        _uniq = m_df.drop_duplicates(subset=[_ord_id_col])
        _cb_ord_cnt = int((_uniq["Cashback Discount"] > 0).sum())
        _total_ord = max(1, len(_uniq))
    else:
        _cb_ord_cnt = 0
        _total_ord = max(1, int(m_ord))
    m_cb_orders_pct = (_cb_ord_cnt / _total_ord * 100) if _cb_ord_cnt > 0 else 0.0

    order_view_mode = st.session_state.get("live_order_filter", "Shipped")
    dashboard_view = st.session_state.get("live_dashboard_view")

    if dashboard_view == "Queue":
        l1 = "Queue Items"
        l2 = "Pipeline Value"
        l3 = "Queue Orders"
        icon_l3 = "📥"
    elif dashboard_view in {"Today Shipped", "Today"}:
        l1 = "Shipped Items · Today"
        l2 = "Sales Revenue · Today"
        l3 = "Shipped Orders · Today"
        icon_l3 = "🚚"
    elif dashboard_view in {"Last Day Shipped", "Last Day"}:
        l1 = "Shipped Items · Last Day"
        l2 = "Sales Revenue · Last Day"
        l3 = "Shipped Orders · Last Day"
        icon_l3 = "🕘"
    elif dashboard_view == "All Orders":
        l1 = "Total Items"
        l2 = "Total Order Value"
        l3 = "All Orders"
        icon_l3 = "📋"
    elif nav_mode == "Backlog":
        l1 = "Backlog Items"
        l2 = "Backlog Rev"
        l3 = "Backlog Orders"
        icon_l3 = "🛒"
    elif order_view_mode == "Shipped":
        l1 = "Shipped Items"
        l2 = "Shipped Revenue"
        l3 = "Shipped Orders"
        icon_l3 = "🚚"
    elif order_view_mode == "Processing":
        l1 = "Processing Items"
        l2 = "Processing Rev"
        l3 = "Processing Orders"
        icon_l3 = "⚙️"
    else:
        l1 = "Gross Items"
        l2 = "Gross Revenue"
        l3 = "Orders"
        icon_l3 = "🛒"

    gross_items_card = (
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l1}</div>'
        f'<div class="metric-value">{v_qty}</div>{badge_qty}{html_dq}{s_qty}{d_qty}</div>'
        '<div class="metric-icon">📦</div></div>'
    )

    cb_badge = ""
    cb_basket_badge = ""
    cb_orders_badge = ""

    tot_cust = m_new_cnt + m_ret_cnt
    pct_new = (m_new_cnt / tot_cust * 100) if tot_cust > 0 else 0
    pct_ret = (m_ret_cnt / tot_cust * 100) if tot_cust > 0 else 0

    v_cust = f"{m_new_cnt} New / {m_ret_cnt} Ret" if tot_cust > 0 else "0 New / 0 Ret"
    cust_badge = (
        f'<div style="font-size:0.75rem;color:#a855f7;font-weight:700;background:rgba(168,85,247,0.12);padding:3px 8px;border-radius:4px;margin-top:4px;display:inline-block;">🆕 {pct_new:.0f}% New || 🔄 {pct_ret:.0f}% Returning</div>'
        if tot_cust > 0
        else ""
    )

    # Previous slot comparison for Customer Mix
    html_dcust = ""
    if c_df is not None and not c_df.empty:
        try:
            full_ref = (
                full_df
                if "full_df" in locals() and full_df is not None and not full_df.empty
                else m_df
            )
            co_new_cnt, co_ret_cnt = compute_new_vs_returning_counts(
                c_df, full_ref, wc_raw_mapping
            )
            co_tot = co_new_cnt + co_ret_cnt
            if co_tot > 0:
                d_new = m_new_cnt - co_new_cnt
                pct_new_change = (
                    ((m_new_cnt - co_new_cnt) / co_new_cnt * 100)
                    if co_new_cnt > 0
                    else (100.0 if m_new_cnt > 0 else 0.0)
                )
                html_dcust = format_delta(
                    f"{d_new:+d} New vs Prev",
                    prev_val_str=f"{co_new_cnt}N / {co_ret_cnt}R",
                    pct_val=pct_new_change,
                )
        except Exception:
            pass

    customer_mix_card = (
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Customer Mix</div>'
        f'<div class="metric-value" style="font-size:1.3rem;">{v_cust}</div>{cust_badge}{html_dcust}{s_cust}{d_cust}</div>'
        '<div class="metric-icon">👥</div></div>'
    )

    card_html = (
        '<div class="metric-container metric-container-5">'
        f"{gross_items_card}"
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l2}</div>'
        f'<div class="metric-value">{v_rev}</div>{badge_rev}{cb_badge}{html_dr}{s_rev}{d_rev}</div><div class="metric-icon">৳</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{l3}</div>'
        f'<div class="metric-value">{v_ord}</div>{badge_ord}{cb_orders_badge}{html_do}{s_ord}{d_ord}</div><div class="metric-icon">{icon_l3}</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">{extra_metric_label}</div>'
        f'<div class="metric-value">{extra_metric_value}</div>{badge_bv}{cb_basket_badge}{extra_metric_delta}'
        f"{(s_bv + d_bv) if nav_mode != 'Backlog' else ''}</div>"
        f'<div class="metric-icon">{extra_metric_icon}</div></div>'
        f"{customer_mix_card}"
        "</div>"
    )

    rendered_react = False
    from src.components.react_kpi import (
        is_react_kpi_available,
        render_react_kpi_toolbar,
    )

    if is_react_kpi_available() and st.session_state.get("use_react_kpi", True):
        try:
            from src.components.dashboard.live_components import (
                _get_live_combined_source,
                apply_dashboard_view_selection,
            )
            from src.processing.data_processing import compute_live_filter_counts

            views = ["All Orders", "Today Shipped", "Last Day Shipped", "Queue"]
            source_df = _get_live_combined_source()
            view_counts = compute_live_filter_counts(source_df)
            sync_time = st.session_state.get("live_sync_time")

            def _clean_delta(pct_val, delta_str):
                if pct_val is not None:
                    return {
                        "value": delta_str or "",
                        "pct": round(float(pct_val), 1),
                        "positive": pct_val >= 0,
                        "text": f"{pct_val:+.1f}% vs prev",
                    }
                if delta_str:
                    return {
                        "value": delta_str,
                        "positive": not str(delta_str).startswith("-"),
                        "text": f"{delta_str} vs prev",
                    }
                return None

            react_metrics = {
                "revenue": {
                    "label": l2,
                    "value": f"{int(m_gross_rev):,}",
                    "prefix": "৳",
                    "delta": _clean_delta(pct_r, dr_str),
                    "sparkline": [float(x) for x in t_rev_vals] if t_rev_vals else None,
                },
                "orders": {
                    "label": l3,
                    "value": f"{int(m_ord):,}",
                    "delta": _clean_delta(pct_o, do_str),
                    "sparkline": [float(x) for x in t_ord_vals] if t_ord_vals else None,
                },
                "units": {
                    "label": l1,
                    "value": f"{int(m_qty):,}",
                    "subtext": "Units fulfilled",
                    "sparkline": [float(x) for x in t_qty_vals] if t_qty_vals else None,
                },
                "aov": {
                    "label": extra_metric_label,
                    "value": f"{int(m_bv):,}",
                    "prefix": "৳",
                    "delta": _clean_delta(pct_b, db_str),
                    "sparkline": [float(x) for x in t_bv_vals] if t_bv_vals else None,
                },
            }

            customer_mix_data = {
                "newCount": int(m_new_cnt),
                "returningCount": int(m_ret_cnt),
                "returningRatio": float(round(pct_ret, 1)),
            }

            selected_new = render_react_kpi_toolbar(
                views=views,
                selected_view=dashboard_view or "All Orders",
                view_counts=view_counts,
                metrics=react_metrics,
                customer_mix=customer_mix_data,
                sync_time=sync_time,
            )

            if (
                selected_new
                and selected_new != dashboard_view
                and selected_new in views
            ):
                apply_dashboard_view_selection(selected_new)
                st.rerun()

            rendered_react = True
        except Exception:
            rendered_react = False

    if not rendered_react:
        st.markdown(card_html, unsafe_allow_html=True)

    # ── Feature #5: Auto-Save Shift Snapshot ───────────────────────────────────
    # Only save once per render cycle, silently — keyed by data fingerprint
    snap_key = f"{m_gross_rev:.0f}_{m_ord}_{m_qty}"
    if st.session_state.get("_last_snap_key") != snap_key and m_ord > 0:
        top_list = []
        if top is not None and not top.empty:
            name_col = (
                "Product Name" if "Product Name" in top.columns else top.columns[0]
            )
            amt_col = "Total Amount" if "Total Amount" in top.columns else None
            for _, row in (
                top.sort_values(amt_col, ascending=False).head(5).iterrows()
                if amt_col
                else []
            ):
                top_list.append(
                    {
                        "name": str(row.get(name_col, "")),
                        "revenue": float(row.get(amt_col, 0)),
                    }
                )
        save_shift_snapshot(
            revenue=float(m_gross_rev),
            orders=int(m_ord),
            qty=int(m_qty),
            aov=float(m_bv),
            shift_label=nav_mode,
            top_products=top_list,
        )
        st.session_state["_last_snap_key"] = snap_key

    # Publish Hero Metrics as the single source of truth for downstream widgets
    st.session_state["hero_metrics"] = {
        "gross_rev": float(m_gross_rev),
        "cashback_disc": float(m_cashback_disc),
        "net_rev": float(m_net_rev),
        "orders": int(m_ord),
        "qty": int(m_qty),
        "net_aov": float(m_net_bv),
        "gross_aov": float(m_gross_bv),
        "cb_per_basket": float(m_cb_per_basket),
        "loss_pct": float(m_loss_pct),
        "new_customers": int(m_new_cnt),
        "returning_customers": int(m_ret_cnt),
    }

    return drill, summ, top, basket, active_df
