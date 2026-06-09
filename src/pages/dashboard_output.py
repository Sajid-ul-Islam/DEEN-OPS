"""Thin orchestrator for dashboard output — delegates to sub-modules."""

import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import datetime, timedelta, timezone

from src.config.constants import SHIPPED_STATUSES
from src.processing.data_processing import get_dispatch_metrics, generate_executive_briefing
from src.pages.dashboard_charts import render_category_charts, render_spotlight
from src.pages.dashboard_filters import render_ingestion_filters
from src.pages.dashboard_metrics import render_operational_metrics
from src.processing.forecasting import PredictiveIntelligence
from src.services.woocommerce.client import get_items_sold_label
from src.pages.excel_exporter import export_to_styled_excel
from src.utils.safe_ops import safe_render
from src.utils.metric_history import load_snapshot_history


def render_performance_analysis(df: pd.DataFrame):
    """Generates time-series performance trends for Ingestion analytics."""
    if df.empty or "Date" not in df.columns:
        return

    st.divider()
    st.subheader("📈 Time-Series Performance Analysis")
    
    c_window, c_toggle = st.columns(2)
    with c_window:
        zoom_options = ["7 Days", "14 Days", "30 Days", "All Time"]
        curr_zoom = st.session_state.get("perf_zoom_window", "14 Days")
        if curr_zoom not in zoom_options: curr_zoom = "14 Days"
            
        if hasattr(st, "pills"):
            zoom_opt = st.pills(
                "Zoom Window", 
                zoom_options, 
                default=curr_zoom,
                selection_mode="single",
                label_visibility="collapsed"
            )
            if not zoom_opt: zoom_opt = curr_zoom
        else:
            zoom_opt = st.radio(
                "Zoom Window", 
                zoom_options, 
                index=zoom_options.index(curr_zoom),
                horizontal=True,
                label_visibility="collapsed"
            )
            
        if zoom_opt != curr_zoom:
            st.session_state.perf_zoom_window = zoom_opt
            st.rerun()
            
    with c_toggle:
        if "perf_enable_ml" not in st.session_state:
            st.session_state.perf_enable_ml = False
        enable_ml = st.checkbox(
            "🚀 Enable ML Forecasting", 
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
             with st.expander("🏆 ML Forecasting Tournament Standings"):
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

             # Ensure data is ready for metrics — fallback to empty df if filtered to zero
             if m_df.empty:
                 m_df = pd.DataFrame(columns=["Quantity", "Item Cost", "Order ID", "Order Status"])

             # Apply Live Dashboard order filter to metrics if applicable
             order_view_mode = st.session_state.get("live_order_filter", "All Orders") if nav_mode == "Today" else "All Orders"
             status_col_m = "Order Status" if "Order Status" in m_df.columns else "Status" if "Status" in m_df.columns else None
             status_col_c = None
             if c_df is not None:
                 status_col_c = "Order Status" if "Order Status" in c_df.columns else "Status" if "Status" in c_df.columns else None

             if order_view_mode == "Shipped Only":
                 from src.processing.data_processing import filter_shipped_by_slot
                 m_df = filter_shipped_by_slot(m_df, nav_mode, is_comparison=False)
                 if c_df is not None:
                     c_df = filter_shipped_by_slot(c_df, nav_mode, is_comparison=True)

             elif order_view_mode == "Processing Only":
                 if status_col_m:
                     m_df = m_df[m_df[status_col_m].astype(str).str.lower() == "processing"]
                 if c_df is not None and status_col_c:
                     c_df = c_df[c_df[status_col_c].astype(str).str.lower() == "processing"]

             # v16.0: Predictive & Lead Time Intelligence
             forecast_val = 0
             avg_proc_time = 0

             # Render Core Metrics KPI Cards
             st.subheader("Core Metrics")

             drill, summ, top, basket, active_df = render_operational_metrics(
                m_df, c_df, nav_mode, dummy_mapping, wc_raw_mapping, forecast_val, avg_proc_time
            )
        else:
            # Fallback if m_df is None
            active_df = granular_df if granular_df is not None else pd.DataFrame()
            drill, summ, top, basket = None, None, None, {}

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
                m_bv = basket.get('avg_customer_value', basket.get('avg_basket_value', 0)) if basket else 0
                if pd.isna(m_bv): m_bv = 0
                
                # Build Compact HTML string to prevent markdown parser interference
                label1 = get_items_sold_label(last_updated).upper()
                ingestion_html = (
                    '<div class="metric-container">'
                    f'<div class="metric-card"><div><div class="metric-label">{label1}</div><div class="metric-value">{m_qty:,.0f}</div></div><div class="metric-icon">📦</div></div>'
                    f'<div class="metric-card"><div><div class="metric-label">REVENUE</div><div class="metric-value">TK {m_rev:,.0f}</div></div><div class="metric-icon">৳</div></div>'
                    f'<div class="metric-card"><div><div class="metric-label">NUMBER OF ORDERS</div><div class="metric-value">{m_ord:,.0f}</div></div><div class="metric-icon">🛒</div></div>'
                    f'<div class="metric-card"><div><div class="metric-label">BASKET SIZE</div><div class="metric-value">TK {m_bv:,.0f}</div></div><div class="metric-icon">🛍️</div></div>'
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

    # ── Products Spotlight & SKU-Wise Report ──
    if top is not None and not top.empty:
        # v15.0: Calculate comparison top items for velocity indicators
        prev_top = None
        if st.session_state.get("wc_sync_mode") == "Operational Cycle":
            nav_mode = st.session_state.get("wc_nav_mode", "Today")
            comp_df = None
            if nav_mode == "Today":
                comp_df = st.session_state.get("wc_prev_df")
            elif nav_mode == "Prev":
                comp_df = st.session_state.get("wc_curr_df")
            
            if comp_df is not None and not comp_df.empty:
                from src.processing.data_processing import prepare_granular_data, aggregate_data
                comp_df_std, _ = prepare_granular_data(comp_df, wc_raw_mapping)
                if not comp_df_std.empty:
                    _, _, prev_top, _ = aggregate_data(comp_df_std, wc_raw_mapping)

        from src.pages.dashboard_charts import render_spotlight
        render_spotlight(top, color_map, prev_top=prev_top)
        st.divider()

        # Master SKU-Wise Product Sales Report Table
        st.subheader("📦 Product Sales Report (Master SKU Wise)")
        st.caption("Aggregated item count and revenue grouped by Master SKU / Clean Product Name.")
        
        top_df = top.copy()
        group_keys = ["SKU"]
        if "Clean_Product" in top_df.columns:
            group_keys.append("Clean_Product")
        else:
            group_keys.append("Product Name")

        report_df = (
            top_df.groupby(group_keys, as_index=False)
            .agg({
                "Total Qty": "sum",
                "Total Amount": "sum",
                "Category": "first"
            })
        )
        
        if "Clean_Product" in report_df.columns:
            report_df.rename(columns={"Clean_Product": "Product Name"}, inplace=True)
            
        report_df = report_df.sort_values("Total Qty", ascending=False).reset_index(drop=True)
        report_df.index = report_df.index + 1
        
        display_df = report_df.copy()
        
        search_q = st.text_input("🔍 Search Product Name or SKU in Report", key="sku_report_search").strip()
        if search_q:
            display_df = display_df[
                display_df["Product Name"].astype(str).str.contains(search_q, case=False, na=False) |
                display_df["SKU"].astype(str).str.contains(search_q, case=False, na=False)
            ]
            
        st.dataframe(
            display_df.style.format({
                "Total Qty": "{:,.0f}",
                "Total Amount": "৳{:,.0f}"
            }),
            use_container_width=True,
            column_config={
                "SKU": st.column_config.TextColumn("SKU", help="Master SKU identification key"),
                "Product Name": st.column_config.TextColumn("Product Name", help="Clean/Base product name"),
                "Category": st.column_config.TextColumn("Category", help="Product main category"),
                "Total Qty": st.column_config.NumberColumn("Quantity Sold", help="Total product item count sold"),
                "Total Amount": st.column_config.NumberColumn("Total Revenue", help="Total revenue generated from product style")
            }
        )
        st.divider()

    # ── Executive Briefing & Power BI Export ──
    is_operational = st.session_state.get("wc_sync_mode") == "Operational Cycle"
    
    if is_operational:
        st.subheader("📱 Executive Briefing")
        
    today_rev = summ['Total Amount'].sum() if summ is not None else 0
    today_qty = summ['Total Qty'].sum() if summ is not None else 0
    today_orders = basket.get('total_orders', 0) if basket else 0
    today_aov = basket.get('avg_customer_value', basket.get('avg_basket_value', 0)) if basket else 0
    
    if is_operational:
        dm = get_dispatch_metrics(active_df, today_orders)
        report_text = generate_executive_briefing(today_rev, today_qty, today_orders, today_aov, dm, top)
        
        # Create a stable fingerprint of current data to detect changes
        current_data_fingerprint = f"{today_rev}_{today_orders}_{dm.get('pathao_count', 0)}_{dm.get('other_count', 0)}"
        
        # If the underlying data changes, invalidate the cached AI text
        if st.session_state.get("last_ai_data_fingerprint", "") != current_data_fingerprint:
            st.session_state.pop("ai_report_text", None)
            
        final_report_text = st.session_state.get("ai_report_text", report_text)

    # Prepare data for centralized exporter
    export_data = {}
    if is_operational:
        export_data["Executive Briefing"] = pd.DataFrame({"Executive Summary": final_report_text.split('\n')})

    # Inject Core Metrics Sheet
    metrics_data = [
        {"Metric": "Total Revenue (TK)", "Value": today_rev},
        {"Metric": "Total Items Sold", "Value": today_qty},
        {"Metric": "Total Orders", "Value": today_orders},
        {"Metric": "Basket Size (TK)", "Value": today_aov},
    ]
    if is_operational and dm:
        metrics_data.extend([
            {"Metric": "Pending Dispatch", "Value": dm.get("pending", 0)},
            {"Metric": "Dispatched", "Value": dm.get("dispatched", 0)},
            {"Metric": "Dispatch Rate (%)", "Value": dm.get("dispatch_rate", 0)}
        ])
    export_data["Core Metrics"] = pd.DataFrame(metrics_data)

    if summ is not None and not summ.empty:
        export_data["Category Summary"] = summ
    if top is not None and not top.empty:
        export_data["Top Products"] = top
    if active_df is not None and not active_df.empty:
        export_data["Raw Shift Data"] = active_df

    excel_report_bytes = export_to_styled_excel(export_data)

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
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                st.markdown("##### 🤖 AI Executive Narrative")
            
            with c2:
                auto_gen = st.toggle("🤖 Auto-Generate AI", value=st.session_state.get("auto_gen_ai_dash", False), key="auto_gen_ai_dash")
                gen_clicked = st.button("✨ Generate Now", key="gen_ai_narrative_dash", use_container_width=True)
                
                data_changed = current_data_fingerprint != st.session_state.get("last_ai_data_fingerprint", "")
                
                if gen_clicked or (auto_gen and data_changed):
                    with st.spinner("🧠 AI Pilot is analyzing today's performance..."):
                        context_data = {
                            "sales_summary": summ,
                            "top_products": top,
                            "raw_sales_data": active_df,
                        }
                        
                        f_val = locals().get('forecast_val', 0)
                        forecast_str = ""
                        if f_val > 0:
                            forecast_str = f"🔮 *ML Forecast (Tomorrow):* ৳{f_val:,.0f}"

                        top_spotlight_str = ""
                        if top is not None and not top.empty:
                            top_5 = top.sort_values("Total Amount", ascending=False).head(5)
                            top_list = [f"{row.get('Product Name', 'Unknown')} ({row.get('Total Qty', 0)} units, ৳{row.get('Total Amount', 0):,.0f})" for _, row in top_5.iterrows()]
                            top_spotlight_str = "\nProduct Spotlight (Top 5 Revenue Generators):\n" + "\n".join([f"- {item}" for item in top_list])

                        prompt = f"""
                        Generate an executive briefing for today's e-commerce operations.
                        Today's key metrics:
                        - Revenue: ৳{today_rev:,.0f}
                        - Orders: {today_orders}
                        - Items Sold: {today_qty}
                        - Basket Size: ৳{today_aov:,.0f}

                        Dispatch Metrics:
                        - Shipped via Pathao: {dm.get('pathao_count', 0)}
                        - Shipped via Other: {dm.get('other_count', 0)}
                        {top_spotlight_str}

                        {forecast_str}

                        Based on the provided context data (sales_summary, top_products), write a concise, professional, and insightful narrative.
                        Highlight key trends, explicitly analyze and summarize the "Product Spotlight" to point out what is driving revenue, and provide a concluding remark on the day's performance.
                        The entire response should be a single block of text formatted for WhatsApp (using markdown like *bold* and _italic_).
                        """
                        
                        try:
                            from src.pages.data_pilot import AIDataAgent
                            import asyncio
                            
                            agent = AIDataAgent(context_dfs=context_data)
                            
                            placeholder = st.empty()
                            full_response = ""
                            
                            import queue
                            import threading
                            import time
                            
                            q = queue.Queue()
                            
                            async def fetch_stream():
                                try:
                                    async for chunk in agent.get_response_stream(prompt, history=[]):
                                        q.put({"chunk": chunk})
                                except Exception as e:
                                    q.put({"error": e})
                                finally:
                                    q.put({"done": True})
                                    
                            def thread_run():
                                new_loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(new_loop)
                                new_loop.run_until_complete(fetch_stream())
                                new_loop.close()
                                
                            t = threading.Thread(target=thread_run)
                            t.start()
                            
                            while True:
                                try:
                                    msg = q.get(timeout=0.1)
                                except queue.Empty:
                                    if not t.is_alive():
                                        break
                                    continue
                                    
                                if "done" in msg:
                                    break
                                if "error" in msg:
                                    st.error(f"AI Streaming Error: {msg['error']}")
                                    break
                                full_response += msg["chunk"]
                                
                                # Drain the queue to batch updates and prevent WebSocket flooding
                                done_flag = False
                                while not q.empty():
                                    try:
                                        next_msg = q.get_nowait()
                                        if "done" in next_msg:
                                            done_flag = True
                                            break
                                        if "error" in next_msg:
                                            st.error(f"AI Streaming Error: {next_msg['error']}")
                                            done_flag = True
                                            break
                                        full_response += next_msg["chunk"]
                                    except queue.Empty:
                                        break
                                        
                                placeholder.info(full_response + "▌")
                                
                                if done_flag:
                                    break
                                    
                                # Throttle UI updates to ~20 FPS to prevent mobile WebSocket flooding
                                time.sleep(0.05)
                            t.join()
                            placeholder.info(full_response)

                            st.session_state.ai_report_text = full_response
                            st.session_state.last_ai_data_fingerprint = current_data_fingerprint
                            st.rerun()
                        except Exception as e:
                            st.error(f"AI generation failed: {e}")

            with c3:
                render_copy_button(final_report_text, label="📋 Copy Briefing")
            
            st.info(final_report_text)
            
            if hasattr(st, "feedback"):
                st.markdown("<div style='margin-top: 10px; margin-bottom: -10px; font-size: 0.85rem; color: #94a3b8; font-weight: 600;'>Rate this AI Narrative:</div>", unsafe_allow_html=True)
                st.feedback("stars", key=f"ai_briefing_feedback_{current_data_fingerprint}")

    st.divider()

    # ── BOTTOM SECTION: Goals | History | Handover | WhatsApp | Export ──────────
    bottom_tabs = st.tabs([
        "🎯 Shift Goals",
        "📅 30-Day History",
        "📝 Shift Handover",
        "💬 WhatsApp Quick-Send",
    ])

    # Tab 1: Goal Setting (Feature #3)
    with bottom_tabs[0]:
        st.markdown("#### 🎯 Set Shift Targets")
        st.caption("Targets appear as progress bars on the Core Metrics KPI cards above.")
        goals = st.session_state.get("shift_goals", {})
        gc1, gc2, gc3 = st.columns(3)
        with gc1:
            rev_g = st.number_input(
                "💰 Revenue Goal (৳)",
                min_value=0, max_value=5_000_000,
                value=int(goals.get("revenue", 0)), step=5000,
                key="goal_revenue_input",
            )
        with gc2:
            ord_g = st.number_input(
                "🛒 Order Goal",
                min_value=0, max_value=5000,
                value=int(goals.get("orders", 0)), step=10,
                key="goal_orders_input",
            )
        with gc3:
            st.markdown('<div style="padding-top:28px;"></div>', unsafe_allow_html=True)
            if st.button("✅ Apply Goals", use_container_width=True, type="primary", key="apply_goals_btn"):
                st.session_state["shift_goals"] = {"revenue": rev_g, "orders": ord_g}
                st.session_state["_last_snap_key"] = ""  # force re-save snapshot
                st.success(f"Goals set — Revenue: ৳{rev_g:,} | Orders: {ord_g}")
                st.rerun()

    # Tab 2: 30-Day History (Feature #5)
    with bottom_tabs[1]:
        st.markdown("#### 📈 30-Day Revenue & Order Trend")
        hist_df = load_snapshot_history(30)
        if hist_df.empty:
            st.info("📂 No history snapshots yet. Metrics are saved automatically each time the dashboard loads with live data.")
        else:
            import plotly.graph_objects as go
            fig_hist = go.Figure()
            fig_hist.add_trace(go.Bar(
                x=hist_df["date"].dt.strftime("%d %b"),
                y=hist_df["revenue"],
                name="Revenue",
                marker_color="rgba(59,130,246,0.7)",
                hovertemplate="%{x}<br>Revenue: ৳%{y:,.0f}<extra></extra>",
            ))
            fig_hist.add_trace(go.Scatter(
                x=hist_df["date"].dt.strftime("%d %b"),
                y=hist_df["orders"],
                name="Orders",
                yaxis="y2",
                mode="lines+markers",
                line=dict(color="#10b981", width=2),
                marker=dict(size=5),
                hovertemplate="%{x}<br>Orders: %{y}<extra></extra>",
            ))
            fig_hist.update_layout(
                yaxis=dict(title="Revenue (৳)", showgrid=True, gridcolor="rgba(128,128,128,0.1)"),
                yaxis2=dict(title="Orders", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=1.05),
                margin=dict(l=10, r=10, t=30, b=10),
                height=320,
            )
            st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar": False})
            with st.expander("Raw History Table"):
                st.dataframe(
                    hist_df.rename(columns={"date": "Date", "revenue": "Revenue (৳)", "orders": "Orders", "qty": "Units"})
                    .assign(**{"Date": hist_df["date"].dt.strftime("%Y-%m-%d")})
                    .sort_values("Date", ascending=False),
                    use_container_width=True, hide_index=True,
                )

    # Tab 3: Shift Handover Report (Feature #8)
    with bottom_tabs[2]:
        st.markdown("#### 📝 Shift Handover Report")
        st.caption("Generate a formatted summary ready to share with the next shift or management.")
        if st.button("✨ Generate Handover Report", type="primary", use_container_width=True, key="gen_handover_btn"):
            dm_h = get_dispatch_metrics(active_df, today_orders) if active_df is not None and not active_df.empty else {}

            top_lines = ""
            if top is not None and not top.empty:
                name_col_h = "Product Name" if "Product Name" in top.columns else top.columns[0]
                amt_col_h = "Total Amount" if "Total Amount" in top.columns else None
                qty_col_h = "Total Qty" if "Total Qty" in top.columns else None
                for _, row in top.sort_values(amt_col_h, ascending=False).head(5).iterrows() if amt_col_h else []:
                    top_lines += f"  • {row.get(name_col_h, 'Unknown')} — {row.get(qty_col_h, 0):.0f} units | ৳{row.get(amt_col_h, 0):,.0f}\n"

            goals_h = st.session_state.get("shift_goals", {})
            rev_goal_h = goals_h.get("revenue", 0)
            rev_pct_h = f"{today_rev / rev_goal_h * 100:.0f}%" if rev_goal_h > 0 else "No target set"

            now_bd = datetime.now(timezone(timedelta(hours=6)))
            handover_text = (
                f"*🛡️ DEEN OPS — Shift Handover Report*\n"
                f"Generated: {now_bd.strftime('%d %b %Y, %I:%M %p')} (BD)\n\n"
                f"*📊 Shift Summary*\n"
                f"  Revenue: ৳{today_rev:,.0f}{f' ({rev_pct_h} of target)' if rev_goal_h else ''}\n"
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
            from src.components.clipboard import render_copy_button
            render_copy_button(st.session_state["shift_handover_text"], label="📋 Copy Handover")
            st.code(st.session_state["shift_handover_text"], language="text")

    # Tab 4: WhatsApp Quick-Send (Feature #4)
    with bottom_tabs[3]:
        st.markdown("#### 💬 WhatsApp Quick-Send")
        st.caption("Generate wa.me links for processing orders directly from today's live data — no file upload needed.")

        src_df = st.session_state.get("wc_curr_df")
        if src_df is None or src_df.empty:
            st.info("📡 No live data loaded. Sync the Live Dashboard first.")
        else:
            status_col_wp = "Order Status" if "Order Status" in src_df.columns else "Status" if "Status" in src_df.columns else None
            wp_df = src_df.copy()
            if status_col_wp:
                wp_df = wp_df[wp_df[status_col_wp].astype(str).str.lower() == "processing"]

            if wp_df.empty:
                st.warning("⚠️ No processing orders in the current live data to message.")
            else:
                st.success(f"⚡ Found {wp_df[status_col_wp].value_counts().get('processing', len(wp_df))} processing orders ready to message.")

                # Detect phone column
                phone_col = next(
                    (c for c in wp_df.columns if any(kw in str(c).lower() for kw in ["phone", "mobile", "contact"])),
                    None,
                )
                name_col_wp = next(
                    (c for c in wp_df.columns if any(kw in str(c).lower() for kw in ["billing name", "full name", "name"])),
                    None,
                )

                if not phone_col:
                    st.error("❌ Could not detect a phone number column in the data.")
                else:
                    custom_msg_wp = st.text_area(
                        "Message Template",
                        value="Assalamu Alaikum! Your DEEN order is being processed and will be dispatched shortly. Thank you for your order! 🙏",
                        height=80,
                        key="wp_quicksend_msg",
                    )

                    if st.button("📲 Generate Links", type="primary", use_container_width=True, key="wp_quicksend_btn"):
                        import urllib.parse
                        links = []
                        for _, row in wp_df.iterrows():
                            phone = str(row.get(phone_col, "")).strip().replace(" ", "").replace("-", "")
                            if not phone or phone.lower() in {"nan", "none"}:
                                continue
                            if phone.startswith("0"):
                                phone = "880" + phone[1:]
                            elif not phone.startswith("880"):
                                phone = "880" + phone
                            name_wp = str(row.get(name_col_wp, "Valued Customer")) if name_col_wp else "Valued Customer"
                            msg = custom_msg_wp.replace("{name}", name_wp.strip())
                            wa_link = f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"
                            links.append({"Name": name_wp, "Phone": phone, "WhatsApp Link": wa_link})

                        if links:
                            links_df_wp = pd.DataFrame(links)
                            st.session_state["wp_quicksend_links"] = links_df_wp
                            st.success(f"✅ Generated {len(links_df_wp)} WhatsApp links.")

                    ql_df = st.session_state.get("wp_quicksend_links")
                    if ql_df is not None and not ql_df.empty:
                        st.dataframe(ql_df.head(20), use_container_width=True, hide_index=True)
                        for _, row in ql_df.head(15).iterrows():
                            st.link_button(
                                f"📱 {row['Name']} ({row['Phone']})",
                                row["WhatsApp Link"],
                            )

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="💾 Export Full Analytics (Excel)",
            data=excel_report_bytes,
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
