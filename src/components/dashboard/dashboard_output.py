"""Thin orchestrator for dashboard output — delegates to sub-modules."""

from datetime import datetime

import pandas as pd
import streamlit as st

from src.components.dashboard.dashboard_charts import (
    render_category_charts,
    render_spotlight,
)
from src.components.dashboard.dashboard_filters import render_ingestion_filters
from src.components.dashboard.dashboard_metrics import render_operational_metrics
from src.config.constants import bd_now
from src.processing.data_processing import (
    filter_all_orders_to_slot,
    filter_shipped_by_slot,
    generate_executive_briefing,
    get_dispatch_metrics,
)
from src.services.exports.excel_exporter import export_to_styled_excel
from src.utils.metric_history import load_snapshot_history


def _render_operational_cycle_metrics(
    m_df, c_df, nav_mode, dummy_mapping, wc_raw_mapping, render_core_metrics=True
):
    """Render operational cycle metrics section (Today/Prev/Backlog mode)."""
    if m_df is None:
        return None, None, None, {}, pd.DataFrame()

    if m_df.empty:
        m_df = pd.DataFrame(
            columns=["Quantity", "Item Cost", "Order ID", "Order Status"]
        )

    order_view_mode = (
        st.session_state.get("live_order_filter", "Shipped")
        if nav_mode == "Today"
        else "All Orders"
    )
    status_col_m = (
        "Order Status"
        if "Order Status" in m_df.columns
        else "Status"
        if "Status" in m_df.columns
        else None
    )
    status_col_c = None
    if c_df is not None:
        status_col_c = (
            "Order Status"
            if "Order Status" in c_df.columns
            else "Status"
            if "Status" in c_df.columns
            else None
        )

    dashboard_view = st.session_state.get("live_dashboard_view")
    is_pre_scoped = dashboard_view in {
        "Today",
        "Today Shipped",
        "Last Day",
        "Last Day Shipped",
        "Queue",
        "All Orders",
    }

    if not is_pre_scoped and order_view_mode == "All Orders" and nav_mode == "Today":
        m_df = filter_all_orders_to_slot(m_df, nav_mode)
        if c_df is not None and not c_df.empty:
            c_df = filter_all_orders_to_slot(c_df, "Prev")
    elif not is_pre_scoped and order_view_mode == "Shipped":
        m_df = filter_shipped_by_slot(m_df, nav_mode, is_comparison=False)
        if c_df is not None:
            c_df = filter_shipped_by_slot(c_df, nav_mode, is_comparison=True)
    elif not is_pre_scoped and order_view_mode == "Processing":
        if status_col_m:
            m_df = m_df[m_df[status_col_m].astype(str).str.lower() == "processing"]
        if c_df is not None and status_col_c:
            c_df = c_df[c_df[status_col_c].astype(str).str.lower() == "processing"]

    if render_core_metrics:
        st.subheader("Core Metrics")
        drill, summ, top, basket, active_df = render_operational_metrics(
            m_df,
            c_df,
            nav_mode,
            dummy_mapping,
            wc_raw_mapping,
            forecast_val=0,
            avg_proc_time=0,
        )
    else:
        # Still compute the values needed downstream without rendering the cards
        from src.processing.data_processing import aggregate_data, prepare_granular_data

        m_df_std, _ = prepare_granular_data(m_df, wc_raw_mapping)
        if not m_df_std.empty:
            drill, summ, top, basket = aggregate_data(m_df_std, dummy_mapping)
            active_df = m_df_std
        else:
            drill, summ, top, basket, active_df = None, None, None, {}, pd.DataFrame()

    return drill, summ, top, basket, active_df


def _render_ingestion_mode_metrics(granular_df, dummy_mapping, last_updated):
    """Render ingestion mode metrics and filters."""
    f_drill, f_summ, f_top, f_basket, f_active = render_ingestion_filters(
        granular_df, dummy_mapping
    )
    drill, summ, top, basket = (
        (f_drill, f_summ, f_top, f_basket)
        if f_summ is not None
        else (None, None, None, None)
    )
    active_df = f_active

    if granular_df is not None and summ is not None:
        with st.container():
            st.subheader(
                "Core Metrics"
            )  # This subheader is now rendered by render_operational_metrics
            # Ingestion mode uses the same KPI card renderer as the live dashboard for consistency.
            # We pass the filtered `active_df` as the main dataframe (`m_df`) and `None` for comparison (`c_df`).
            # The `nav_mode` is set to a neutral value like "Ingestion" to avoid comparison logic.
            from src.components.dashboard.dashboard_metrics import (
                render_operational_metrics,
            )

            wc_raw_mapping = {
                "name": "Item Name",
                "cost": "Item Cost",
                "qty": "Quantity",
                "date": "Order Date",
                "order_id": "Order ID",
                "phone": "Phone (Billing)",
                "sku": "SKU",
            }
            render_operational_metrics(
                active_df, None, "Ingestion", dummy_mapping, wc_raw_mapping
            )
            st.divider()

    return drill, summ, top, basket, active_df


def _render_charts(summ, total_rev=None):
    """Render the Performance Outlook charts section with executive metric highlights."""
    if summ is None or summ.empty:
        st.info("No category sales data available for current selection.")
        return {}

    # Create a two-column layout to place the toggle next to the subheader
    col_header, col_toggle = st.columns([3, 1])

    with col_header:
        st.subheader("📊 Performance Outlook & Category Analytics")

    chart_summ = summ.copy()

    with col_toggle:
        # Use a toggle for view selection, placed in the second column
        show_sub_cat = st.toggle(
            "Show Sub-Category View",
            value=st.session_state.get("perf_outlook_view", "Sub-Category")
            == "Sub-Category",
            key="perf_outlook_toggle",
            help="Toggle between high-level Category view (off) and granular Sub-Category view (on).",
        )

    new_view = "Sub-Category" if show_sub_cat else "Category"
    st.session_state["perf_outlook_view"] = new_view
    display_col = new_view

    if display_col == "Category" and "Category" in chart_summ.columns:
        chart_summ = chart_summ.groupby("Category", as_index=False).agg(
            {"Total Qty": "sum", "Total Amount": "sum"}
        )

    # Prepare metrics summary for inline placement inside chart whitespace
    metrics_summary = {}
    top_rev_cat = (
        chart_summ.sort_values("Total Amount", ascending=False).iloc[0]
        if not chart_summ.empty
        else None
    )
    top_vol_cat = (
        chart_summ.sort_values("Total Qty", ascending=False).iloc[0]
        if not chart_summ.empty
        else None
    )
    tot_rev = (
        total_rev
        if (total_rev is not None and total_rev > 0)
        else chart_summ["Total Amount"].sum()
    )
    tot_vol = chart_summ["Total Qty"].sum()

    if top_rev_cat is not None:
        cat_rev = top_rev_cat["Total Amount"]
        pct_rev = (cat_rev / tot_rev * 100) if tot_rev > 0 else 0
        metrics_summary["rev_name"] = top_rev_cat[display_col]
        metrics_summary["rev_val"] = cat_rev
        metrics_summary["rev_pct"] = pct_rev

    if top_vol_cat is not None:
        cat_v_qty = top_vol_cat["Total Qty"]
        pct_vol = (cat_v_qty / tot_vol * 100) if tot_vol > 0 else 0
        metrics_summary["vol_name"] = top_vol_cat[display_col]
        metrics_summary["vol_val"] = cat_v_qty
        metrics_summary["vol_pct"] = pct_vol

    metrics_summary["cat_cnt"] = len(chart_summ)
    metrics_summary["avg_price"] = (tot_rev / tot_vol) if tot_vol > 0 else 0

    sorted_cats = (
        chart_summ.sort_values("Total Amount", ascending=False)[display_col].tolist()
        if not chart_summ.empty
        else []
    )
    from src.config.ui_config import CHART_THEMES

    theme_name = st.session_state.get("chart_theme", "✨ Emerald Cyberpunk")
    theme_cfg = CHART_THEMES.get(theme_name, CHART_THEMES["✨ Emerald Cyberpunk"])
    palette = theme_cfg["colors"]
    color_map = {cat: palette[i % len(palette)] for i, cat in enumerate(sorted_cats)}

    if not chart_summ.empty:
        render_category_charts(
            chart_summ,
            display_col,
            color_map,
            metrics_summary=metrics_summary,
            total_revenue=total_rev,
        )
    st.divider()

    return color_map


def _render_sku_report(top):
    """Render the Master SKU-Wise Product Sales Report table."""
    if top is None or top.empty:
        st.info("No product sales data available for current selection.")
        return

    st.subheader("📦 Product Sales Report (Master SKU Wise)")
    st.caption(
        "Aggregated item count and revenue grouped by Master SKU / Clean Product Name."
    )

    top_df = top.copy()
    group_keys = ["SKU"]
    if "Clean_Product" in top_df.columns:
        group_keys.append("Clean_Product")
    elif "Product Name" in top_df.columns:
        group_keys.append("Product Name")

    report_df = top_df.groupby(group_keys, as_index=False).agg(
        {"Total Qty": "sum", "Total Amount": "sum", "Category": "first"}
    )

    if "Clean_Product" in report_df.columns:
        report_df.rename(columns={"Clean_Product": "Product Name"}, inplace=True)

    if "SKU" in report_df.columns:
        report_df["SKU"] = report_df["SKU"].fillna("N/A").astype(str).str.strip()
        report_df["SKU"] = report_df["SKU"].replace(
            {"": "N/A", "nan": "N/A", "None": "N/A"}
        )

    col_order = [
        c
        for c in ["SKU", "Product Name", "Category", "Total Qty", "Total Amount"]
        if c in report_df.columns
    ]
    report_df = report_df[col_order]
    report_df = report_df.sort_values("Total Qty", ascending=False).reset_index(
        drop=True
    )
    report_df.index = report_df.index + 1

    display_df = report_df.copy()
    search_q = st.text_input(
        "🔍 Search Product Name or SKU in Report", key="sku_report_search"
    ).strip()
    if search_q:
        display_df = display_df[
            display_df["Product Name"]
            .astype(str)
            .str.contains(search_q, case=False, na=False)
            | display_df["SKU"].astype(str).str.contains(search_q, case=False, na=False)
        ]
        st.caption(
            f'Showing **{len(display_df)}** of **{len(report_df)}** products matching `"{search_q}"`'
        )

    st.dataframe(
        display_df.style.format({"Total Qty": "{:,.0f}", "Total Amount": "৳{:,.0f}"}),
        use_container_width=True,
        column_order=col_order,
        column_config={
            "SKU": st.column_config.TextColumn(
                "SKU", help="Master SKU identification key"
            ),
            "Product Name": st.column_config.TextColumn(
                "Product Name", help="Clean/Base product name"
            ),
            "Category": st.column_config.TextColumn(
                "Category", help="Product main category"
            ),
            "Total Qty": st.column_config.NumberColumn(
                "Quantity Sold", help="Total product item count sold"
            ),
            "Total Amount": st.column_config.NumberColumn(
                "Total Revenue", help="Total revenue generated from product style"
            ),
        },
    )
    st.divider()


def _build_export_data(
    is_operational,
    summ,
    top,
    active_df,
    today_rev,
    today_qty,
    today_orders,
    today_aov,
    dm,
    final_report_text,
):
    """Build the export data dictionary for Excel export."""
    export_data = {}
    if is_operational:
        export_data["Executive Briefing"] = pd.DataFrame(
            {"Executive Summary": final_report_text.split("\n")}
        )

    metrics_data = [
        {"Metric": "Total Revenue (TK)", "Value": today_rev},
        {"Metric": "Total Items Sold", "Value": today_qty},
        {"Metric": "Total Orders", "Value": today_orders},
        {"Metric": "Basket Size (TK)", "Value": today_aov},
    ]
    if is_operational and dm:
        metrics_data.extend(
            [
                {"Metric": "Pending Dispatch", "Value": dm.get("pending", 0)},
                {"Metric": "Dispatched", "Value": dm.get("dispatched", 0)},
                {"Metric": "Dispatch Rate (%)", "Value": dm.get("dispatch_rate", 0)},
            ]
        )
    export_data["Core Metrics"] = pd.DataFrame(metrics_data)

    if summ is not None and not summ.empty:
        export_data["Category Summary"] = summ
    if top is not None and not top.empty:
        export_data["Top Products"] = top
    if active_df is not None and not active_df.empty:
        export_data["Raw Shift Data"] = active_df

    return export_data


def _render_ai_briefing_section(
    is_operational,
    summ,
    top,
    active_df,
    today_rev,
    today_qty,
    today_orders,
    today_aov,
    dm,
    current_data_fingerprint,
    final_report_text,
):
    """Render the executive briefing expander (deterministic narrative only).

    The former LLM-streamed briefing (Data Pilot) has been removed; this now
    renders the deterministic briefing generated by generate_executive_briefing.
    """
    if not is_operational:
        return

    with st.expander("📋 View/Copy Executive Briefing", expanded=False):
        from src.components.ui.clipboard import render_copy_button

        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown("##### 📊 Executive Narrative")
        with c2:
            render_copy_button(final_report_text, label="📋 Copy Briefing")

        st.info(final_report_text)


def _render_bottom_tabs(active_df, top, today_rev, today_qty, today_orders, today_aov):
    """Render the bottom tabbed section: History, Handover."""
    bottom_tabs = st.tabs(
        [
            "📅 30-Day History",
            "📝 Shift Handover",
        ]
    )

    with bottom_tabs[0]:
        st.markdown("#### 📈 30-Day Revenue & Order Trend")
        hist_df = load_snapshot_history(30)
        if hist_df.empty or len(hist_df) < 2:
            st.info(
                "📂 Need at least 2 days of history to show trends. Metrics are saved automatically each time the dashboard loads with live data."
            )
        else:
            import plotly.graph_objects as go

            fig_hist = go.Figure()
            fig_hist.add_trace(
                go.Bar(
                    x=hist_df["date"].dt.strftime("%d %b"),
                    y=hist_df["revenue"],
                    name="Revenue",
                    marker_color="rgba(59,130,246,0.7)",
                    hovertemplate="%{x}<br>Revenue: ৳%{y:,.0f}<extra></extra>",
                )
            )
            fig_hist.add_trace(
                go.Scatter(
                    x=hist_df["date"].dt.strftime("%d %b"),
                    y=hist_df["orders"],
                    name="Orders",
                    yaxis="y2",
                    mode="lines+markers",
                    line=dict(color="#10b981", width=2),
                    marker=dict(size=5),
                    hovertemplate="%{x}<br>Orders: %{y}<extra></extra>",
                )
            )
            fig_hist.update_layout(
                xaxis=dict(type="category"),
                yaxis=dict(
                    title="Revenue (৳)",
                    showgrid=True,
                    gridcolor="rgba(128,128,128,0.1)",
                ),
                yaxis2=dict(
                    title="Orders", overlaying="y", side="right", showgrid=False
                ),
                legend=dict(orientation="h", y=1.05),
                margin=dict(l=10, r=10, t=30, b=10),
                height=320,
            )
            st.plotly_chart(
                fig_hist, use_container_width=True, config={"displayModeBar": False}
            )
            with st.expander("Raw History Table"):
                st.dataframe(
                    hist_df.rename(
                        columns={
                            "date": "Date",
                            "revenue": "Revenue (৳)",
                            "orders": "Orders",
                            "qty": "Units",
                        }
                    )
                    .assign(**{"Date": hist_df["date"].dt.strftime("%Y-%m-%d")})
                    .sort_values("Date", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                )

    with bottom_tabs[1]:
        st.markdown("#### 📝 Shift Handover Report")
        st.caption(
            "Generate a formatted summary ready to share with the next shift or management."
        )
        if st.button(
            "✨ Generate Handover Report",
            type="primary",
            use_container_width=True,
            key="gen_handover_btn",
        ):
            dm_h = (
                get_dispatch_metrics(active_df, today_orders)
                if active_df is not None and not active_df.empty
                else {}
            )

            top_lines = ""
            if top is not None and not top.empty:
                name_col_h = (
                    "Product Name" if "Product Name" in top.columns else top.columns[0]
                )
                amt_col_h = "Total Amount" if "Total Amount" in top.columns else None
                qty_col_h = "Total Qty" if "Total Qty" in top.columns else None
                for _, row in (
                    top.sort_values(amt_col_h, ascending=False).head(5).iterrows()
                    if amt_col_h
                    else []
                ):
                    top_lines += f"  • {row.get(name_col_h, 'Unknown')} — {row.get(qty_col_h, 0):.0f} units | ৳{row.get(amt_col_h, 0):,.0f}\n"

            now_bd = bd_now()
            handover_text = (
                f"*🛡️ DEEN OPS — Shift Handover Report*\n"
                f"Generated: {now_bd.strftime('%d %b %Y, %I:%M %p')} (BD)\n\n"
                f"*📊 Shift Summary*\n"
                f"  Revenue: ৳{today_rev:,.0f}\n"
                f"  Orders: {today_orders}\n"
                f"  Units Sold: {today_qty:.0f}\n"
                f"  Basket Size: ৳{today_aov:,.0f}\n\n"
                f"*🚚 Dispatch Status*\n"
                f"  Shipped: {dm_h.get('dispatched', 0)}\n"
                f"  Pending: {dm_h.get('pending', 0)}\n"
                f"  Dispatch Rate: {dm_h.get('dispatch_rate', 0):.0f}%\n\n"
                f"*🔥 Top Products*\n{top_lines if top_lines else '  N/A'}\n"
                f"*Next Shift:* Please check backlog for {dm_h.get('pending', 0)} pending orders."
            )
            st.session_state["shift_handover_text"] = handover_text

        if st.session_state.get("shift_handover_text"):
            from src.components.ui.clipboard import render_copy_button

            render_copy_button(
                st.session_state["shift_handover_text"], label="📋 Copy Handover"
            )
            st.code(st.session_state["shift_handover_text"], language="text")


def _render_export_buttons(export_data, export_date_str, active_df):
    """Render exports without generating the Excel workbook on every rerun."""
    c1, c2 = st.columns(2)
    with c1:
        row_count = len(active_df) if active_df is not None else 0
        metric_signature = export_data.get("Core Metrics", pd.DataFrame()).to_json()
        export_key = f"{export_date_str}:{row_count}:{metric_signature}"
        if st.session_state.get("_prepared_export_key") != export_key:
            st.session_state.pop("_prepared_excel_report", None)

        if "_prepared_excel_report" not in st.session_state:
            if st.button(
                "💾 Prepare Excel Export",
                key="prepare_dashboard_excel",
                type="primary",
                width="stretch",
            ):
                with st.spinner("Preparing workbook..."):
                    st.session_state["_prepared_excel_report"] = export_to_styled_excel(
                        export_data
                    )
                    st.session_state["_prepared_export_key"] = export_key

        if excel_report_bytes := st.session_state.get("_prepared_excel_report"):
            st.download_button(
                label="⬇️ Download Excel",
                data=excel_report_bytes,
                file_name=f"DEEN_Analytics_Report_{export_date_str}.xlsx",
                type="primary",
                width="stretch",
            )
    with c2:
        if active_df is not None and not active_df.empty:
            st.download_button(
                label="📄 Export Filtered View (CSV)",
                data=active_df.to_csv(index=False).encode("utf-8"),
                file_name=f"DEEN_Filtered_Data_{export_date_str}.csv",
                type="secondary",
                width="stretch",
            )


def render_dashboard_output(
    drill,
    summ,
    top,
    timeframe,
    basket,
    source_name,
    last_updated="N/A",
    granular_df=None,
    show_core_metrics=True,
    raw_df=None,
):
    """Renders common dashboard widgets/charts/tables/export.

    Args:
        show_core_metrics: When False, skips the Core Metrics KPI card rendering
            (useful when a separate @st.fragment handles auto-refresh of metrics).
    """

    dummy_mapping = {
        "name": "Product Name",
        "cost": "Item Cost",
        "qty": "Quantity",
        "date": "Date",
        "order_id": "Order ID",
        "phone": "Phone",
        "sku": "SKU",
    }
    wc_raw_mapping = {
        "name": "Item Name",
        "cost": "Item Cost",
        "qty": "Quantity",
        "date": "Order Date",
        "order_id": "Order ID",
        "phone": "Phone (Billing)",
        "sku": "SKU",
    }

    # ── Mode selection: Operational Cycle vs Ingestion ──
    is_operational = st.session_state.get("wc_sync_mode") == "Operational Cycle"

    if is_operational:
        if show_core_metrics:
            nav_mode = st.session_state.get("wc_nav_mode", "Today")
            if nav_mode == "Today":
                m_df = st.session_state.get("wc_curr_df")
            elif nav_mode == "Backlog":
                m_df = st.session_state.get("wc_backlog_df")
            else:
                m_df = st.session_state.get("wc_prev_df")

            c_df = (
                st.session_state.get(
                    "wc_prev_df" if nav_mode == "Today" else "wc_curr_df"
                )
                if nav_mode != "Backlog"
                else None
            )
            drill, summ, top, basket, active_df = _render_operational_cycle_metrics(
                m_df,
                c_df,
                nav_mode,
                dummy_mapping,
                wc_raw_mapping,
                render_core_metrics=True,
            )
        else:
            active_df = granular_df if granular_df is not None else pd.DataFrame()
    else:
        drill, summ, top, basket, active_df = _render_ingestion_mode_metrics(
            granular_df, dummy_mapping, last_updated
        )

    # ── Executive Briefing & Key Metrics ──
    today_qty = summ["Total Qty"].sum() if summ is not None else 0
    today_orders = basket.get("total_orders", 0) if basket else 0
    today_aov = (
        basket.get("avg_customer_value", basket.get("avg_basket_value", 0))
        if basket
        else 0
    )

    dm = None
    final_report_text = ""
    hero = st.session_state.get("hero_metrics", {})

    today_qty = hero.get("qty", summ["Total Qty"].sum() if summ is not None else 0)
    today_orders = hero.get("orders", basket.get("total_orders", 0) if basket else 0)
    today_aov = hero.get(
        "net_aov",
        (
            basket.get("avg_customer_value", basket.get("avg_basket_value", 0))
            if basket
            else 0
        ),
    )

    dm = None
    final_report_text = ""
    today_rev = float(
        hero.get("net_rev", summ["Total Amount"].sum() if summ is not None else 0.0)
    )
    gross_rev = float(hero.get("gross_rev", today_rev))
    cashback_disc = float(hero.get("cashback_disc", 0.0))

    if is_operational:
        dm = get_dispatch_metrics(active_df, today_orders)

        _adf = active_df if (active_df is not None and not active_df.empty) else None
        if not hero:
            cashback_disc = (
                float(_adf["Cashback Discount"].sum())
                if (_adf is not None and "Cashback Discount" in _adf.columns)
                else 0.0
            )

            if _adf is not None and "Total Amount" in _adf.columns:
                today_rev = float(_adf["Total Amount"].sum())
            else:
                today_rev = (
                    float(summ["Total Amount"].sum()) if summ is not None else 0.0
                )

            if _adf is not None and "Gross Amount" in _adf.columns:
                gross_rev = float(_adf["Gross Amount"].sum())
            else:
                gross_rev = today_rev + cashback_disc

    # Unified performance view selector
    hub_view = st.segmented_control(
        "Performance view",
        ["Category Share", "Spotlight", "SKU Report", "Basket Analysis"],
        default=st.session_state.get("dashboard_performance_view", "Category Share"),
        key="dashboard_performance_view",
        label_visibility="collapsed",
    )
    color_map = {}

    if hub_view == "Category Share":
        color_map = _render_charts(summ, total_rev=gross_rev)
    elif hub_view == "Spotlight":
        prev_top = None
        if st.session_state.get("wc_sync_mode") == "Operational Cycle":
            nav_mode = st.session_state.get("wc_nav_mode", "Today")
            comp_df = (
                st.session_state.get("wc_prev_df")
                if nav_mode == "Today"
                else st.session_state.get("wc_curr_df")
                if nav_mode == "Prev"
                else None
            )

            if comp_df is not None and not comp_df.empty:
                from src.processing.data_processing import (
                    aggregate_data,
                    prepare_granular_data,
                )

                comp_df_std, _ = prepare_granular_data(comp_df, wc_raw_mapping)
                if not comp_df_std.empty:
                    _, _, prev_top, _ = aggregate_data(comp_df_std, wc_raw_mapping)

        render_spotlight(top, color_map, prev_top=prev_top)
    elif hub_view == "SKU Report":
        _render_sku_report(top)
    elif hub_view == "Basket Analysis":
        from src.components.dashboard.market_basket_view import (
            render_market_basket_analysis_section,
        )

        render_market_basket_analysis_section(
            active_df, raw_df=raw_df if raw_df is not None else active_df
        )

    if is_operational:
        gross_aov = float(
            hero.get(
                "gross_aov",
                (gross_rev / today_orders) if today_orders > 0 else float(today_aov),
            )
        )

        if "new_customers" in hero and "returning_customers" in hero:
            new_cust_cnt = hero["new_customers"]
            ret_cust_cnt = hero["returning_customers"]
        else:
            from src.utils.customer_registry import compute_new_vs_returning_counts

            full_df_for_cust = st.session_state.get("wc_curr_df")
            new_cust_cnt, ret_cust_cnt = compute_new_vs_returning_counts(
                active_df, full_df_for_cust, wc_raw_mapping
            )

        report_text = generate_executive_briefing(
            gross_rev,
            today_qty,
            today_orders,
            gross_aov,
            dm,
            top,
            gross_rev=gross_rev,
            cashback_disc=0.0,
        )

        current_data_fingerprint = f"{gross_rev}_{today_orders}_{dm.get('pathao_count', 0)}_{dm.get('other_count', 0)}_{new_cust_cnt}_{ret_cust_cnt}"

        final_report_text = report_text

        _render_ai_briefing_section(
            is_operational,
            summ,
            top,
            active_df,
            today_rev,
            today_qty,
            today_orders,
            gross_aov,
            dm,
            current_data_fingerprint,
            final_report_text,
        )

    # ── Export Preparation ──
    export_data = _build_export_data(
        is_operational,
        summ,
        top,
        active_df,
        today_rev,
        today_qty,
        today_orders,
        today_aov,
        dm,
        final_report_text,
    )
    export_date_str = datetime.now().strftime("%Y%m%d")
    if not is_operational:
        if (
            active_df is not None
            and not active_df.empty
            and "Date" in active_df.columns
        ):
            try:
                min_d = pd.to_datetime(active_df["Date"]).min()
                max_d = pd.to_datetime(active_df["Date"]).max()
                if min_d.date() == max_d.date():
                    export_date_str = min_d.strftime("%Y%m%d")
                else:
                    export_date_str = (
                        f"{min_d.strftime('%Y%m%d')}_to_{max_d.strftime('%Y%m%d')}"
                    )
            except Exception:
                pass

    st.divider()

    # ── BOTTOM SECTION: History | Handover ──
    _render_bottom_tabs(active_df, top, today_rev, today_qty, today_orders, today_aov)

    st.divider()

    # ── Export Buttons ──
    _render_export_buttons(export_data, export_date_str, active_df)
