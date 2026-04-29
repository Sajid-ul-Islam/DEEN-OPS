"""Thin orchestrator for dashboard output — delegates to sub-modules."""

import os
import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import datetime, timedelta, timezone
from io import BytesIO
from itertools import combinations

from src.processing.data_processing import get_dispatch_metrics, generate_executive_briefing
from src.pages.dashboard_charts import render_category_charts, render_spotlight
from src.pages.dashboard_filters import render_ingestion_filters
from src.pages.dashboard_metrics import render_operational_metrics
from src.processing.forecasting import PredictiveIntelligence
from src.services.woocommerce.client import get_items_sold_label
from src.utils.safe_ops import safe_render


def render_performance_analysis(df: pd.DataFrame):
    """Generates time-series performance trends for Ingestion analytics."""
    if df.empty or "Date" not in df.columns:
        return

    st.divider()
    c_hdr, c_window, c_toggle = st.columns([2, 1, 1])
    with c_hdr:
        st.subheader("\U0001f4c8 Time-Series Performance Analysis")
    with c_window:
        if "perf_zoom_window" not in st.session_state:
            st.session_state.perf_zoom_window = "7 Days"
        zoom_opt = st.selectbox(
            "Zoom Window", 
            ["7 Days", "14 Days", "30 Days", "All Time"], 
            key="perf_zoom_window", 
            label_visibility="collapsed"
        )
    with c_toggle:
        if "perf_enable_ml" not in st.session_state:
            st.session_state.perf_enable_ml = False
        enable_ml = st.checkbox(
            "\U0001f680 Enable ML Forecasting", 
            key="perf_enable_ml", 
            help="Apply Predictive Intelligence models to forecast future trends."
        )

    df_day = df.copy()
    df_day["Day"] = pd.to_datetime(df_day["Date"]).dt.date

    daily_stats = df_day.groupby("Day").agg({
        "Total Amount": "sum",
        "Quantity": "sum",
        "Order ID": "nunique"
    }).reset_index()

    daily_stats["Avg Basket Value"] = (daily_stats["Total Amount"] / daily_stats["Order ID"]).fillna(0)
    daily_stats = daily_stats.sort_values("Day")

    # Add 7-Day Rolling Averages for Trend Lines
    daily_stats["Revenue Trend"] = daily_stats["Total Amount"].rolling(window=7, min_periods=1).mean()
    daily_stats["Volume Trend"] = daily_stats["Quantity"].rolling(window=7, min_periods=1).mean()
    daily_stats["Orders Trend"] = daily_stats["Order ID"].rolling(window=7, min_periods=1).mean()

    if not daily_stats.empty:
        last_date = daily_stats["Day"].max()
        first_date = daily_stats["Day"].min()
        
        if zoom_opt == "All Time":
            window_start = first_date
        else:
            window_days = int(zoom_opt.split()[0])
            window_start = last_date - timedelta(days=window_days) if (last_date - first_date).days > window_days else first_date
            
        window_end = last_date + timedelta(days=7) if enable_ml else last_date
        # Convert to strings so Plotly reliably updates the axis range dynamically
        x_axis_range = [window_start.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")]
    else:
        x_axis_range = None

    c1, c2 = st.columns(2)

    with c1:
        rev_data = daily_stats.set_index("Day")["Total Amount"]
        fc_res_rev, standings_rev = PredictiveIntelligence.forecast(rev_data) if enable_ml else (None, None)

        fig_rev = px.area(daily_stats, x="Day", y="Total Amount",
                          title=f"Revenue Outlook {'(Best 3 Strategy Ensemble)' if enable_ml else '(with 7-Day Trend)'}",
                          labels={"Total Amount": "Revenue", "Day": ""},
                          color_discrete_sequence=["#1d4ed8"],
                          hover_data={"Total Amount": ":,.0f", "Revenue Trend": ":,.0f"})

        if not enable_ml:
            fig_rev.add_scatter(x=daily_stats["Day"], y=daily_stats["Revenue Trend"], mode="lines", name="7-Day Avg", line=dict(color="#fcd34d", width=3, dash="dot"))

        if enable_ml and fc_res_rev:
            fc_dates = [daily_stats["Day"].iloc[-1] + timedelta(days=i+1) for i in range(7)]
            forecast_colors = ["#4f46e5", "#818cf8", "#c7d2fe"]
            for i, res in enumerate(fc_res_rev):
                fig_rev.add_scatter(x=fc_dates, y=res["forecast"], mode="lines+markers",
                                   name=f"Rank {i+1}: {res['name']}",
                                   line=dict(dash="dot" if i > 0 else "dash", color=forecast_colors[i], width=2 if i == 0 else 1))

        fig_rev.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350, showlegend=False)
        fig_rev.update_xaxes(rangeslider_visible=True, range=x_axis_range, autorange=False)
        st.plotly_chart(fig_rev, use_container_width=True, config={"displayModeBar": False})

        qty_data = daily_stats.set_index("Day")["Quantity"]
        fc_res_qty, _ = PredictiveIntelligence.forecast(qty_data) if enable_ml else (None, None)

        fig_qty = px.line(daily_stats, x="Day", y="Quantity",
                          title=f"Volume Outlook {'(Top Models Displayed)' if enable_ml else '(with 7-Day Trend)'}",
                          labels={"Quantity": "Volume", "Day": ""},
                          color_discrete_sequence=["#10b981"],
                          hover_data={"Quantity": ":,.0f", "Volume Trend": ":,.0f"})

        if not enable_ml:
            fig_qty.add_scatter(x=daily_stats["Day"], y=daily_stats["Volume Trend"], mode="lines", name="7-Day Avg", line=dict(color="#fcd34d", width=3, dash="dot"))

        if enable_ml and fc_res_qty:
            fc_dates = [daily_stats["Day"].iloc[-1] + timedelta(days=i+1) for i in range(7)]
            forecast_colors = ["#059669", "#34d399", "#a7f3d0"]
            for i, res in enumerate(fc_res_qty):
                fig_qty.add_scatter(x=fc_dates, y=res["forecast"], mode="lines",
                                   name=f"Rank {i+1}: {res['name']}",
                                   line=dict(dash="dot" if i > 0 else "dash", color=forecast_colors[i], width=2 if i == 0 else 1))

        fig_qty.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350, showlegend=False)
        fig_qty.update_xaxes(rangeslider_visible=True, range=x_axis_range, autorange=False)
        st.plotly_chart(fig_qty, use_container_width=True, config={"displayModeBar": False})

    with c2:
        ord_data = daily_stats.set_index("Day")["Order ID"]
        fc_res_ord, _ = PredictiveIntelligence.forecast(ord_data) if enable_ml else (None, None)

        fig_ord = px.bar(daily_stats, x="Day", y="Order ID",
                         title=f"Orders Outlook {'(Multi-Model Mode)' if enable_ml else '(with 7-Day Trend)'}",
                         labels={"Order ID": "Orders", "Day": ""},
                         color_discrete_sequence=["#6366f1"],
                         hover_data={"Order ID": ":,.0f", "Orders Trend": ":,.1f"})

        if not enable_ml:
            fig_ord.add_scatter(x=daily_stats["Day"], y=daily_stats["Orders Trend"], mode="lines", name="7-Day Avg", line=dict(color="#fcd34d", width=3, dash="dot"))

        if enable_ml and fc_res_ord:
             fc_dates = [daily_stats["Day"].iloc[-1] + timedelta(days=i+1) for i in range(7)]
             forecast_colors = ["#4f46e5", "#818cf8", "#c7d2fe"]
             for i, res in enumerate(fc_res_ord):
                 fig_ord.add_scatter(x=fc_dates, y=res["forecast"], mode="markers+lines",
                                    name=f"Rank {i+1}: {res['name']}",
                                    line=dict(dash="dot" if i > 0 else "solid", color=forecast_colors[i], width=2 if i == 0 else 1))

        fig_ord.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350, showlegend=False)
        fig_ord.update_xaxes(rangeslider_visible=True, range=x_axis_range, autorange=False)
        st.plotly_chart(fig_ord, use_container_width=True, config={"displayModeBar": False})

        if enable_ml and standings_rev is not None and not isinstance(standings_rev, str):
             with st.expander("\U0001f3c6 ML Forecasting Tournament Standings"):
                 st.write("**Revenue Performance Leaderboard** (MAE Comparison)")
                 st.dataframe(standings_rev, hide_index=True, use_container_width=True)
                 st.caption("Lower error indicates better historical accuracy for this specific metric.")

        fig_bv = px.line(daily_stats, x="Day", y="Avg Basket Value",
                         title="Market Basket Efficiency (AOV)",
                         labels={"Avg Basket Value": "Avg Value", "Day": ""},
                         color_discrete_sequence=["#f59e0b"])
        fig_bv.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350)
        fig_bv.update_xaxes(rangeslider_visible=True, range=x_axis_range, autorange=False)
        st.plotly_chart(fig_bv, use_container_width=True, config={"displayModeBar": False})


def render_dashboard_output(
    drill, summ, top, timeframe, basket, source_name, last_updated="N/A", granular_df=None
):
    """Renders common dashboard widgets/charts/tables/export."""

    dummy_mapping = {"name":"Product Name", "cost":"Item Cost", "qty":"Quantity", "date":"Date", "order_id":"Order ID", "phone":"Phone", "sku":"SKU"}
    wc_raw_mapping = {"name":"Item Name", "cost":"Item Cost", "qty":"Quantity", "date":"Order Date", "order_id":"Order ID", "phone":"Phone (Billing)", "sku":"SKU"}

    active_df = granular_df

    if st.session_state.get("wc_sync_mode") == "Operational Cycle":
        nav_mode = st.session_state.get("wc_nav_mode", "Today")

        m_df = None
        c_df = None

        if nav_mode == "Prev":
            m_df = st.session_state.get("wc_prev_df")
            c_df = st.session_state.get("wc_curr_df")
        elif nav_mode == "Backlog":
            m_df = st.session_state.get("wc_backlog_df")
        else:
            m_df = st.session_state.get("wc_curr_df")
            c_df = st.session_state.get("wc_prev_df")

        if m_df is not None:
             # Operational mode controls moved to Banner for HUD-style UI
             pass
 
             drill, summ, top, basket, active_df = render_operational_metrics(
                m_df, c_df, nav_mode, dummy_mapping, wc_raw_mapping
            )

    else:
        # Ingestion mode filters
        f_drill, f_summ, f_top, f_basket, f_active = render_ingestion_filters(
            granular_df, dummy_mapping
        )
        if f_summ is not None:
            drill, summ, top, basket = f_drill, f_summ, f_top, f_basket
        active_df = f_active

        if granular_df is not None and summ is not None:
            with st.container():
                st.subheader("Core Metrics")
                
                m_qty = summ['Total Qty'].sum()
                m_rev = summ['Total Amount'].sum()
                m_ord = basket.get("total_orders", 0) if basket else 0
                m_bv = basket.get('avg_basket_value', 0) if basket else 0
                
                # Build Compact HTML string to prevent markdown parser interference
                label1 = get_items_sold_label(last_updated).upper()
                ingestion_html = (
                    '<div class="metric-container">'
                    f'<div class="metric-card"><div><div class="metric-label">{label1}</div><div class="metric-value">{m_qty:,.0f}</div></div><div class="metric-icon">📦</div></div>'
                    f'<div class="metric-card"><div><div class="metric-label">REVENUE</div><div class="metric-value">TK {m_rev:,.0f}</div></div><div class="metric-icon">৳</div></div>'
                    f'<div class="metric-card"><div><div class="metric-label">NUMBER OF ORDERS</div><div class="metric-value">{m_ord:,.0f}</div></div><div class="metric-icon">🛒</div></div>'
                    f'<div class="metric-card"><div><div class="metric-label">MARKET BASKET VALUE</div><div class="metric-value">TK {m_bv:,.0f}</div></div><div class="metric-icon">🛍️</div></div>'
                    '</div>'
                )
                st.markdown(ingestion_html, unsafe_allow_html=True)
                st.divider()

    # ── Charts ──
    st.subheader("Performance Outlook")

    sel_unified = st.session_state.get("fallback_filter_unified", [])

    display_col = "Category"
    if "Sub-Category" in summ.columns:
        display_col = "Sub-Category"

    sorted_cats = summ.sort_values("Total Amount", ascending=False)[display_col].tolist()
    color_map = {
        cat: px.colors.sample_colorscale(
            "Plasma",
            [(i / max(1, len(sorted_cats) - 1)) * 0.85 if len(sorted_cats) > 1 else 0],
        )[0]
        for i, cat in enumerate(sorted_cats)
    }

    render_category_charts(summ, display_col, color_map)
    st.divider()

    # ── Executive Briefing & Power BI Export ──
    st.subheader("📱 Executive Briefing & Analytics Export")
    today_rev = summ['Total Amount'].sum() if summ is not None else 0
    today_qty = summ['Total Qty'].sum() if summ is not None else 0
    today_orders = basket.get('total_orders', 0) if basket else 0
    today_aov = basket.get('avg_basket_value', 0) if basket else 0
    
    dm = get_dispatch_metrics(active_df, today_orders)

    report_text = generate_executive_briefing(today_rev, today_qty, today_orders, today_aov, dm, top)

    buf_pbi = BytesIO()
    with pd.ExcelWriter(buf_pbi, engine="xlsxwriter") as wr:
        pd.DataFrame({"Executive Summary": report_text.split('\n')}).to_excel(wr, sheet_name="Executive Briefing", index=False)
        if summ is not None and not summ.empty:
            summ.to_excel(wr, sheet_name="Category Summary", index=False)
        if top is not None and not top.empty:
            top.to_excel(wr, sheet_name="Top Products", index=False)
        if active_df is not None and not active_df.empty:
            active_df.to_excel(wr, sheet_name="Raw Shift Data", index=False)

    exp1, exp2 = st.columns(2)
    with exp1:
        st.download_button(
            label="💾 Download Full Analytics Report (Excel)",
            data=buf_pbi.getvalue(),
            file_name=f"DEEN_Analytics_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            type="primary",
            use_container_width=True
        )
    
    with exp2:
        if active_df is not None and not active_df.empty:
            st.download_button(
                label="📄 Download Raw Data (CSV)",
                data=active_df.to_csv(index=False).encode('utf-8'),
                file_name=f"DEEN_Raw_Data_{datetime.now().strftime('%Y%m%d')}.csv",
                type="secondary",
                use_container_width=True
            )
    
    with st.expander("📋 View/Copy Executive Briefing Text", expanded=False):
        st.markdown("**Copy for Quick Briefing:**")
        st.code(report_text, language="markdown")

    st.divider()

    # v15.0: Calculate comparison top items for velocity indicators
    prev_top = None
    if st.session_state.get("wc_sync_mode") == "Operational Cycle":
        nav_mode = st.session_state.get("wc_nav_mode", "Today")
        comp_df = None
        if nav_mode == "Today":
            comp_df = st.session_state.get("wc_prev_df")
        elif nav_mode == "Prev":
            # Comparison for yesterday is today (passive)
            comp_df = st.session_state.get("wc_curr_df")
        
        if comp_df is not None and not comp_df.empty:
            from src.processing.data_processing import aggregate_data
            _, _, prev_top, _ = aggregate_data(comp_df, wc_raw_mapping)

    from src.pages.dashboard_charts import render_spotlight
    render_spotlight(top, color_map, prev_top=prev_top)