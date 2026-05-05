"""Thin orchestrator for dashboard output — delegates to sub-modules."""

import os
import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import datetime, timedelta, timezone
from io import BytesIO
from itertools import combinations

from src.config.constants import SHIPPED_STATUSES
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
    st.subheader("\U0001f4c8 Time-Series Performance Analysis")
    
    c_window, c_toggle = st.columns(2)
    with c_window:
        if "perf_zoom_window" not in st.session_state:
            st.session_state.perf_zoom_window = "14 Days"
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
                          color_discrete_sequence=["#1d4ed8"])
        fig_rev.update_traces(
            customdata=daily_stats[["Revenue Trend"]],
            hovertemplate="<b>%{x}</b><br>Revenue: ৳%{y:,.0f}<br>7-Day Trend: ৳%{customdata[0]:,.0f}<extra></extra>"
        )

        if not enable_ml:
            fig_rev.add_scatter(x=daily_stats["Day"], y=daily_stats["Revenue Trend"], mode="lines", name="7-Day Avg", line=dict(color="#fcd34d", width=3, dash="dot"), hovertemplate="<b>%{x}</b><br>7-Day Avg: ৳%{y:,.0f}<extra></extra>")

        if enable_ml and fc_res_rev:
            fc_dates = [daily_stats["Day"].iloc[-1] + timedelta(days=i+1) for i in range(7)]
            forecast_colors = ["#4f46e5", "#818cf8", "#c7d2fe"]
            for i, res in enumerate(fc_res_rev):
                fig_rev.add_scatter(x=fc_dates, y=res["forecast"], mode="lines+markers",
                                   name=f"Rank {i+1}: {res['name']}",
                                   line=dict(dash="dot" if i > 0 else "dash", color=forecast_colors[i], width=2 if i == 0 else 1),
                                   hovertemplate="<b>%{x}</b><br>Forecast: ৳%{y:,.0f}<extra></extra>")

        fig_rev.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350, showlegend=False)
        fig_rev.update_xaxes(rangeslider_visible=False, range=x_axis_range, autorange=False)
        fig_rev.update_yaxes(showgrid=True, gridcolor="rgba(128, 128, 128, 0.2)", zeroline=False)
        st.plotly_chart(fig_rev, use_container_width=True, config={"displayModeBar": False})

        qty_data = daily_stats.set_index("Day")["Quantity"]
        fc_res_qty, _ = PredictiveIntelligence.forecast(qty_data) if enable_ml else (None, None)

        fig_qty = px.line(daily_stats, x="Day", y="Quantity",
                          title=f"Volume Outlook {'(Top Models Displayed)' if enable_ml else '(with 7-Day Trend)'}",
                          labels={"Quantity": "Volume", "Day": ""},
                          color_discrete_sequence=["#10b981"])
        fig_qty.update_traces(
            customdata=daily_stats[["Volume Trend"]],
            hovertemplate="<b>%{x}</b><br>Volume: %{y:,.0f} Units<br>7-Day Trend: %{customdata[0]:,.0f} Units<extra></extra>"
        )

        if not enable_ml:
            fig_qty.add_scatter(x=daily_stats["Day"], y=daily_stats["Volume Trend"], mode="lines", name="7-Day Avg", line=dict(color="#fcd34d", width=3, dash="dot"), hovertemplate="<b>%{x}</b><br>7-Day Avg: %{y:,.0f} Units<extra></extra>")

        if enable_ml and fc_res_qty:
            fc_dates = [daily_stats["Day"].iloc[-1] + timedelta(days=i+1) for i in range(7)]
            forecast_colors = ["#059669", "#34d399", "#a7f3d0"]
            for i, res in enumerate(fc_res_qty):
                fig_qty.add_scatter(x=fc_dates, y=res["forecast"], mode="lines",
                                   name=f"Rank {i+1}: {res['name']}",
                                   line=dict(dash="dot" if i > 0 else "dash", color=forecast_colors[i], width=2 if i == 0 else 1),
                                   hovertemplate="<b>%{x}</b><br>Forecast: %{y:,.0f} Units<extra></extra>")

        fig_qty.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350, showlegend=False)
        fig_qty.update_xaxes(rangeslider_visible=False, range=x_axis_range, autorange=False)
        fig_qty.update_yaxes(showgrid=True, gridcolor="rgba(128, 128, 128, 0.2)", zeroline=False)
        st.plotly_chart(fig_qty, use_container_width=True, config={"displayModeBar": False})

    with c2:
        ord_data = daily_stats.set_index("Day")["Order ID"]
        fc_res_ord, _ = PredictiveIntelligence.forecast(ord_data) if enable_ml else (None, None)

        fig_ord = px.bar(daily_stats, x="Day", y="Order ID",
                         title=f"Orders Outlook {'(Multi-Model Mode)' if enable_ml else '(with 7-Day Trend)'}",
                         labels={"Order ID": "Orders", "Day": ""},
                         color_discrete_sequence=["#6366f1"])
        fig_ord.update_traces(
            customdata=daily_stats[["Orders Trend"]],
            hovertemplate="<b>%{x}</b><br>Orders: %{y:,.0f}<br>7-Day Trend: %{customdata[0]:,.1f}<extra></extra>"
        )

        if not enable_ml:
            fig_ord.add_scatter(x=daily_stats["Day"], y=daily_stats["Orders Trend"], mode="lines", name="7-Day Avg", line=dict(color="#fcd34d", width=3, dash="dot"), hovertemplate="<b>%{x}</b><br>7-Day Avg: %{y:,.1f}<extra></extra>")

        if enable_ml and fc_res_ord:
             fc_dates = [daily_stats["Day"].iloc[-1] + timedelta(days=i+1) for i in range(7)]
             forecast_colors = ["#4f46e5", "#818cf8", "#c7d2fe"]
             for i, res in enumerate(fc_res_ord):
                 fig_ord.add_scatter(x=fc_dates, y=res["forecast"], mode="markers+lines",
                                    name=f"Rank {i+1}: {res['name']}",
                                    line=dict(dash="dot" if i > 0 else "solid", color=forecast_colors[i], width=2 if i == 0 else 1),
                                    hovertemplate="<b>%{x}</b><br>Forecast: %{y:,.0f}<extra></extra>")

        fig_ord.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350, showlegend=False)
        fig_ord.update_xaxes(rangeslider_visible=False, range=x_axis_range, autorange=False)
        fig_ord.update_yaxes(showgrid=True, gridcolor="rgba(128, 128, 128, 0.2)", zeroline=False)
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
        fig_bv.update_traces(hovertemplate="<b>%{x}</b><br>Avg Basket Value: ৳%{y:,.0f}<extra></extra>")
        fig_bv.update_layout(margin=dict(l=40, r=20, t=50, b=40), height=350)
        fig_bv.update_xaxes(rangeslider_visible=False, range=x_axis_range, autorange=False)
        fig_bv.update_yaxes(showgrid=True, gridcolor="rgba(128, 128, 128, 0.2)", zeroline=False)
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
 
             # Apply Live Dashboard order filter to metrics if applicable
             order_view_mode = st.session_state.get("live_order_filter", "All Orders")
             if order_view_mode == "Shipped Only":
                 status_col_m = "Order Status" if "Order Status" in m_df.columns else "Status" if "Status" in m_df.columns else None
                 if status_col_m:
                     # Modification-aware operational filtering for "Shift Sales"
                     m_slot_key = "wc_curr_slot" if nav_mode == "Today" else "wc_prev_slot" if nav_mode == "Prev" else None
                     m_slot = st.session_state.get(m_slot_key)
                     
                     if m_slot and "mod_dt_parsed" in m_df.columns:
                         ms, me = m_slot
                         m_df = m_df[
                             (m_df[status_col_m].astype(str).str.lower().isin(SHIPPED_STATUSES)) &
                             (m_df["mod_dt_parsed"] >= ms) &
                             (m_df["mod_dt_parsed"] <= (me + timedelta(minutes=30)))
                         ]
                     else:
                         m_df = m_df[m_df[status_col_m].astype(str).str.lower().isin(SHIPPED_STATUSES)]
                     
                 if c_df is not None and status_col_c:
                         # Comparison slot boundaries
                         c_slot_key = "wc_prev_slot" if nav_mode == "Today" else "wc_curr_slot" if nav_mode == "Prev" else None
                         c_slot = st.session_state.get(c_slot_key)
                         if c_slot and "mod_dt_parsed" in c_df.columns:
                             cs, ce = c_slot
                             c_df = c_df[
                                 (c_df[status_col_c].astype(str).str.lower().isin(SHIPPED_STATUSES)) &
                                 (c_df["mod_dt_parsed"] >= cs) &
                                 (c_df["mod_dt_parsed"] <= (ce + timedelta(minutes=30)))
                             ]
                         else:
                             c_df = c_df[c_df[status_col_c].astype(str).str.lower().isin(SHIPPED_STATUSES)]
             elif order_view_mode == "Processing Only":
                 if status_col_m:
                     m_df = m_df[m_df[status_col_m].astype(str).str.lower() == "processing"]
                 if c_df is not None and status_col_c:
                     c_df = c_df[c_df[status_col_c].astype(str).str.lower() == "processing"]

             # v16.0: Predictive & Lead Time Intelligence
             forecast_val = 0
             avg_proc_time = 0
             
             # 1. Next Day Forecast
             full_df = st.session_state.get("wc_full_df")
             if full_df is not None and not full_df.empty:
                 temp_full = full_df.copy()
                 temp_full['Day'] = pd.to_datetime(temp_full[wc_raw_mapping["date"]]).dt.date
                 daily_rev = temp_full.groupby('Day')['Order Total Amount'].sum()
                 if len(daily_rev) >= 3:
                     fc_res, _ = PredictiveIntelligence.forecast(daily_rev, steps=1)
                     if fc_res:
                         forecast_val = fc_res[0]['forecast'][0]

             # 2. Processing Lead Time (Created -> Modified to Shipped/Confirmed)
             ship_conf_df = m_df[m_df[status_col_m].astype(str).str.lower().isin(SHIPPED_STATUSES)].copy() if status_col_m else pd.DataFrame()
             if not ship_conf_df.empty and "mod_dt_parsed" in ship_conf_df.columns:
                 ship_conf_df["dt_created"] = pd.to_datetime(ship_conf_df[wc_raw_mapping["date"]], errors="coerce").dt.tz_localize(None)
                 # Calculate hours
                 ship_conf_df["lead_h"] = (ship_conf_df["mod_dt_parsed"] - ship_conf_df["dt_created"]).dt.total_seconds() / 3600
                 # Filter out negative or extreme outliers (e.g. status changes before creation which is an API quirk) and ensure non-NaN
                 valid_leads = ship_conf_df[(ship_conf_df["lead_h"] >= 0) & (ship_conf_df["lead_h"] < 168)]["lead_h"]
                 avg_proc_time = valid_leads.mean() if not valid_leads.empty else 0.0
                 if pd.isna(avg_proc_time): avg_proc_time = 0.0

             drill, summ, top, basket, active_df = render_operational_metrics(
                m_df, c_df, nav_mode, dummy_mapping, wc_raw_mapping, forecast_val, avg_proc_time
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
    chart_summ = summ.copy() if summ is not None else pd.DataFrame()

    if not chart_summ.empty and "Sub-Category" in chart_summ.columns:
        display_col = st.session_state.get("perf_outlook_view", "Sub-Category")
        if display_col == "Category":
            chart_summ = chart_summ.groupby("Category", as_index=False).agg({"Total Qty": "sum", "Total Amount": "sum"})

    sorted_cats = chart_summ.sort_values("Total Amount", ascending=False)[display_col].tolist() if not chart_summ.empty else []
    color_map = {
        cat: px.colors.sample_colorscale(
            "Plasma",
            [(i / max(1, len(sorted_cats) - 1)) * 0.85 if len(sorted_cats) > 1 else 0],
        )[0]
        for i, cat in enumerate(sorted_cats)
    }

    if not chart_summ.empty:
        render_category_charts(chart_summ, display_col, color_map)
    st.divider()

    # ── Executive Briefing & Power BI Export ──
    is_operational = st.session_state.get("wc_sync_mode") == "Operational Cycle"
    
    if is_operational:
        st.subheader("📱 Executive Briefing")
        
    today_rev = summ['Total Amount'].sum() if summ is not None else 0
    today_qty = summ['Total Qty'].sum() if summ is not None else 0
    today_orders = basket.get('total_orders', 0) if basket else 0
    today_aov = basket.get('avg_basket_value', 0) if basket else 0
    
    if is_operational:
        dm = get_dispatch_metrics(active_df, today_orders)
        report_text = generate_executive_briefing(today_rev, today_qty, today_orders, today_aov, dm, top)

    buf_pbi = BytesIO()
    with pd.ExcelWriter(buf_pbi, engine="xlsxwriter") as wr:
        if is_operational:
            df_exec = pd.DataFrame({"Executive Summary": report_text.split('\n')})
            df_exec.to_excel(wr, sheet_name="Executive Briefing", index=False)
            
        # Inject Core Metrics Sheet
        metrics_data = [
            {"Metric": "Total Revenue (TK)", "Value": today_rev},
            {"Metric": "Total Items Sold", "Value": today_qty},
            {"Metric": "Total Orders", "Value": today_orders},
            {"Metric": "Average Order Value (TK)", "Value": today_aov},
        ]
        if is_operational and dm:
            metrics_data.extend([
                {"Metric": "Pending Dispatch", "Value": dm.get("pending", 0)},
                {"Metric": "Dispatched", "Value": dm.get("dispatched", 0)},
                {"Metric": "Dispatch Rate (%)", "Value": dm.get("dispatch_rate", 0)}
            ])
        df_metrics = pd.DataFrame(metrics_data)
        df_metrics.to_excel(wr, sheet_name="Core Metrics", index=False)

        if summ is not None and not summ.empty:
            summ.to_excel(wr, sheet_name="Category Summary", index=False)
        if top is not None and not top.empty:
            top.to_excel(wr, sheet_name="Top Products", index=False)
        if active_df is not None and not active_df.empty:
            active_df.to_excel(wr, sheet_name="Raw Shift Data", index=False)

        workbook = wr.book
        header_format = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})

        # Auto-format column widths & apply header styles
        sheets_to_format = [
            ("Core Metrics", df_metrics),
            ("Category Summary", summ if summ is not None else pd.DataFrame()),
            ("Top Products", top if top is not None else pd.DataFrame()),
            ("Raw Shift Data", active_df if active_df is not None else pd.DataFrame())
        ]
        if is_operational:
            sheets_to_format.insert(0, ("Executive Briefing", df_exec))
            
        for sheet_name, df_ref in sheets_to_format:
            if sheet_name in wr.sheets and not df_ref.empty:
                ws = wr.sheets[sheet_name]
                for idx, col in enumerate(df_ref.columns):
                    ws.write(0, idx, str(col), header_format)
                    
                    try:
                        # Drop NA to avoid 'nan' skewing length, calculate actual max string length
                        col_data = df_ref[col].dropna().astype(str)
                        max_val_len = col_data.map(len).max() if not col_data.empty else 0
                        # Add a +4 buffer for cell padding, bold headers, and font scaling
                        max_len = max(max_val_len, len(str(col))) + 4
                    except Exception:
                        max_len = len(str(col)) + 4
                    
                    # Cap max width at 100 to prevent unreadably wide columns
                    ws.set_column(idx, idx, min(max_len, 100))

    export_date_str = datetime.now().strftime('%Y%m%d')
    if not is_operational:
        if active_df is not None and not active_df.empty and "Date" in active_df.columns:
            try:
                min_d = pd.to_datetime(active_df["Date"]).min()
                max_d = pd.to_datetime(active_df["Date"]).max()
                if min_d.date() == max_d.date():
                    export_date_str = min_d.strftime('%Y%m%d')
                else:
                    export_date_str = f"{min_d.strftime('%Y%m%d')}_to_{max_d.strftime('%Y%m%d')}"
            except Exception:
                pass

    if is_operational:
        with st.expander("📋 View/Copy Executive Briefing", expanded=False):
            from src.components.clipboard import render_copy_button
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown("##### 🤖 AI Executive Narrative")
            with c2:
                render_copy_button(report_text, label="📋 Copy Briefing")
            st.info(report_text)

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

    st.divider()
    
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="💾 Export Full Analytics (Excel)",
            data=buf_pbi.getvalue(),
            file_name=f"DEEN_Analytics_Report_{export_date_str}.xlsx",
            type="primary",
            use_container_width=True
        )
    with c2:
        if active_df is not None and not active_df.empty:
            st.download_button(
                label="📄 Export Filtered View (CSV)",
                data=active_df.to_csv(index=False).encode('utf-8'),
                file_name=f"DEEN_Filtered_Data_{export_date_str}.csv",
                type="secondary",
                use_container_width=True
            )