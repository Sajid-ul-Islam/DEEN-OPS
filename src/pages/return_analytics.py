import streamlit as st
from src.components.ui_components import render_premium_header, render_metric_grid, apply_standard_dataframe
import pandas as pd

def render_return_analytics_tab():
    render_premium_header("Return Analytics", "Track, analyze, and resolve order returns", "📉")
    
    # We replace /pubhtml? with /pub?output=csv& for easy parsing by pandas
    sheet_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4j3i94IWVlVYI5gErxzfmmaYNiirGqnrncRKrDCbHvmLYpzH9l4_etjYmfCoDj_Gv-_mps2gnufXE/pub?output=csv&gid=0&single=true"
    
    with st.spinner("Fetching return data from Google Sheets..."):
        try:
            from src.utils.http import request_with_backoff
            import io
            
            r = request_with_backoff("GET", sheet_url, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            
            if "Date" in df.columns:
                df["Parsed_Date"] = pd.to_datetime(df["Date"], errors="coerce")
                valid_dates = df["Parsed_Date"].dropna()
                
                if not valid_dates.empty:
                    min_date = valid_dates.min().date()
                    max_date = valid_dates.max().date()
                    
                    def clear_enrichment():
                        if "enriched_returns" in st.session_state:
                            del st.session_state["enriched_returns"]
                        if "full_enriched_returns" in st.session_state:
                            del st.session_state["full_enriched_returns"]
                    
                    st.markdown("### 📅 Filter Returns by Date")
                    col1, col2 = st.columns([1.5, 1])
                    
                    with col1:
                        time_opts = ["All Time", "Last Day", "Last 7 Days", "Last 15 Days", "Last Month"]
                        has_pills = hasattr(st, "pills")
                        
                        if has_pills:
                            selected_time = st.pills("Quick Range", time_opts, default="All Time", label_visibility="collapsed")
                        else:
                            selected_time = st.radio("Quick Range", time_opts, index=0, horizontal=True, label_visibility="collapsed")
                            
                    with col2:
                        # Determine date range based on quick filter so the Date picker visually matches
                        default_range = (min_date, max_date)
                        if selected_time == "Last Day":
                            default_range = (max_date - pd.Timedelta(days=1), max_date)
                        elif selected_time == "Last 7 Days":
                            default_range = (max_date - pd.Timedelta(days=7), max_date)
                        elif selected_time == "Last 15 Days":
                            default_range = (max_date - pd.Timedelta(days=15), max_date)
                        elif selected_time == "Last Month":
                            default_range = (max_date - pd.Timedelta(days=30), max_date)
                            
                        selected_dates = st.date_input(
                            "Select Time Range", 
                            value=default_range,
                            min_value=min_date,
                            max_value=max_date,
                            help="Filter the Google Sheet returns by date before matching.",
                            label_visibility="collapsed"
                        )
                    
                    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                        start_d, end_d = selected_dates
                        df = df[(df["Parsed_Date"].dt.date >= start_d) & (df["Parsed_Date"].dt.date <= end_d)]
            
            # Basic stats
            total_returns = len(df)
            
            st.markdown(
                '<div class="metric-container">'
                f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Filtered Returns</div><div class="metric-value">{total_returns}</div></div><div class="metric-icon">📦</div></div>'
                '</div>',
                unsafe_allow_html=True
            )
            
            st.divider()
            
            tab_enrich, tab_raw = st.tabs(["🚀 Enriched Matches (WC & Pathao)", "📄 Raw Google Sheet Data"])
            
            with tab_raw:
                st.markdown("#### 📋 Loaded Google Sheet Data")
                st.dataframe(df, use_container_width=True, hide_index=True)
            
            with tab_enrich:
                st.markdown("#### 🔄 Real-Time Return Tracking")
                
                if "Order ID" in df.columns:
                    enable_pathao = st.toggle("Enable Pathao Fetching", value=True, help="Turn off to skip Pathao tracking status and only fetch WooCommerce data. Useful if Pathao API is slow or rate-limiting.")
                    
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.info("Click the button to fetch live order details from WooCommerce and tracking statuses from Pathao.")
                    with col2:
                        if st.button("⚡ Fetch & Enrich Data", use_container_width=True, type="primary"):
                            # Force a clear when clicked manually too
                            clear_enrichment()
                            
                            df_to_match = df.copy()
                            # Clean Order ID for matching
                            df_to_match["Order ID"] = pd.to_numeric(df_to_match["Order ID"], errors="coerce")
                            df_to_match = df_to_match.dropna(subset=["Order ID"])
                            order_ids_to_fetch = df_to_match["Order ID"].astype(int).unique().tolist()
                            
                            with st.spinner("Fetching external data (this runs in the background)..."):
                                from src.services.woocommerce.client import fetch_specific_woocommerce_orders
                                from src.services.pathao.status import get_pathao_order_status
                                from concurrent.futures import ThreadPoolExecutor
                                
                                try:
                                    # 1. Fetch WooCommerce Orders
                                    wc_orders = fetch_specific_woocommerce_orders(order_ids_to_fetch)
                                    wc_df = pd.DataFrame(wc_orders)
                                    
                                    # 2. Fetch Pathao Statuses
                                    pathao_statuses = {}
                                    if enable_pathao and "Courier ID" in df_to_match.columns:
                                        courier_ids = df_to_match["Courier ID"].dropna().unique().tolist()
                                        
                                        def fetch_p_status(cid):
                                            res = get_pathao_order_status(cid)
                                            if "data" in res and "order_status" in res["data"]:
                                                return cid, res["data"]["order_status"]
                                            return cid, "Status Not Found"
                                        
                                        with ThreadPoolExecutor(max_workers=3) as executor:
                                            futures = [executor.submit(fetch_p_status, cid) for cid in courier_ids]
                                            for future in futures:
                                                cid, status = future.result()
                                                pathao_statuses[cid] = status
                                                
                                    # Append Pathao Status to df_to_match
                                    if pathao_statuses:
                                        df_to_match["Live Pathao Status"] = df_to_match["Courier ID"].map(pathao_statuses)
                                    else:
                                        df_to_match["Live Pathao Status"] = "N/A (Skipped)" if not enable_pathao else "N/A"
                                    
                                    if not wc_df.empty and "Order Number" in wc_df.columns:
                                        wc_df["Order Number_Num"] = pd.to_numeric(wc_df["Order Number"], errors="coerce")
                                        
                                        # Merge Return Data with WooCommerce Data
                                        merged_df = pd.merge(
                                            df_to_match, 
                                            wc_df, 
                                            left_on="Order ID", 
                                            right_on="Order Number_Num", 
                                            how="inner"
                                        )
                                        
                                        if merged_df.empty:
                                            st.warning("No matching WooCommerce orders found for these returns.")
                                        else:
                                            # Select useful columns for overview
                                            merged_df = merged_df.rename(columns={"Order ID_x": "GSheet Order ID", "Order ID_y": "WC Internal ID"})
                                            overview_cols = ["Order Number", "Courier ID", "Live Pathao Status", "Delivery Issue", "Item Name", "Order Status", "Full Name (Billing)", "Phone (Billing)", "Order Date", "Item Cost", "Quantity"]
                                            existing_cols = [c for c in overview_cols if c in merged_df.columns]
                                            
                                            # Save to session state
                                            st.session_state["enriched_returns"] = merged_df[existing_cols].copy()
                                            st.session_state["full_enriched_returns"] = merged_df.copy()
                                    else:
                                        st.warning("WooCommerce failed to return data for these order IDs.")
                                        
                                except Exception as match_err:
                                    st.error(f"Failed to load external data: {match_err}")
                    
                    # Display cached enriched data if it exists
                    if "enriched_returns" in st.session_state:
                        enriched_df = st.session_state["enriched_returns"].copy()
                        full_df = st.session_state["full_enriched_returns"].copy()
                        
                        # Apply Quick Filter to the enriched data instantly
                        if selected_time and selected_time != "All Time" and "Order Date" in enriched_df.columns:
                            enriched_df["Parsed_Order_Date"] = pd.to_datetime(enriched_df["Order Date"], errors="coerce")
                            max_dt = enriched_df["Parsed_Order_Date"].max()
                            
                            if pd.notna(max_dt):
                                if selected_time == "Last Day":
                                    cutoff = max_dt - pd.Timedelta(days=1)
                                elif selected_time == "Last 7 Days":
                                    cutoff = max_dt - pd.Timedelta(days=7)
                                elif selected_time == "Last 15 Days":
                                    cutoff = max_dt - pd.Timedelta(days=15)
                                elif selected_time == "Last Month":
                                    cutoff = max_dt - pd.Timedelta(days=30)
                                    
                                enriched_df = enriched_df[enriched_df["Parsed_Order_Date"] >= cutoff]
                                if "Order Date" in full_df.columns:
                                    full_df["Parsed_Order_Date"] = pd.to_datetime(full_df["Order Date"], errors="coerce")
                                    full_df = full_df[full_df["Parsed_Order_Date"] >= cutoff]
                                    
                        st.divider()
                        
                        # Determine Outlet from Order Number
                        if "Order Number" in enriched_df.columns:
                            enriched_df["Order Number Str"] = enriched_df["Order Number"].astype(str).str.lower().str.strip()
                            enriched_df["Outlet"] = "Main/Online"
                            enriched_df.loc[enriched_df["Order Number Str"].str.contains(r"[- ]?c$", regex=True, na=False), "Outlet"] = "Central (C)"
                            enriched_df.loc[enriched_df["Order Number Str"].str.contains(r"[- ]?w$", regex=True, na=False), "Outlet"] = "Warehouse (W)"
                            enriched_df.loc[enriched_df["Order Number Str"].str.contains(r"[- ]?s$", regex=True, na=False), "Outlet"] = "Sylhet/Savar (S)"

                        # Fetch Shipped Count from WooCommerce for Return Rate
                        total_shipped = 0
                        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                            try:
                                from datetime import datetime
                                start_iso = datetime.combine(selected_dates[0], datetime.min.time()).isoformat()
                                end_iso = datetime.combine(selected_dates[1], datetime.max.time()).isoformat()
                                from src.services.woocommerce.client import get_woocommerce_shipped_orders_count
                                total_shipped = get_woocommerce_shipped_orders_count(start_iso, end_iso)
                            except Exception as e:
                                st.warning(f"Could not fetch total shipped orders for return rate: {e}")

                        # Compute Advanced KPIs
                        total_matches = len(enriched_df)
                        return_rate = (total_matches / total_shipped * 100) if total_shipped > 0 else 0
                        
                        financial_impact = 0
                        if "Item Cost" in enriched_df.columns:
                            financial_impact = pd.to_numeric(enriched_df["Item Cost"], errors="coerce").sum()
                                
                        pending_returns = 0
                        if "Live Pathao Status" in enriched_df.columns:
                            pending_returns = len(enriched_df[~enriched_df["Live Pathao Status"].astype(str).str.contains("Return", case=False, na=True)])
                            
                        # Render Modern KPIs
                        st.markdown('<div class="metric-container">', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Total Shipped</div><div class="metric-value">{total_shipped}</div></div><div class="metric-icon">📦</div></div>'
                            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Matched Returns</div><div class="metric-value">{total_matches}</div></div><div class="metric-icon">🔁</div></div>'
                            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Return Rate</div><div class="metric-value">{return_rate:.1f}%</div></div><div class="metric-icon">📉</div></div>'
                            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Financial Impact</div><div class="metric-value">৳ {financial_impact:,.0f}</div></div><div class="metric-icon">💰</div></div>'
                            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Pending Res.</div><div class="metric-value">{pending_returns}</div></div><div class="metric-icon">⏳</div></div>',
                            unsafe_allow_html=True
                        )
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                        st.divider()
                        
                        # Render Charts
                        import plotly.express as px
                        import plotly.graph_objects as go
                        
                        col_chart1, col_chart2 = st.columns(2)
                        
                        with col_chart1:
                            st.markdown("##### 🍩 Return Reasons Breakdown")
                            if "Delivery Issue" in enriched_df.columns and not enriched_df["Delivery Issue"].isna().all():
                                fig_issues = px.pie(
                                    enriched_df, 
                                    names="Delivery Issue", 
                                    hole=0.6,
                                    color_discrete_sequence=px.colors.qualitative.Pastel
                                )
                                fig_issues.update_layout(
                                    margin=dict(t=10, b=10, l=10, r=10),
                                    showlegend=True,
                                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)"
                                )
                                st.plotly_chart(fig_issues, use_container_width=True, config={'displayModeBar': False})
                            else:
                                st.info("No Return Reason data available.")
                                
                        with col_chart2:
                            st.markdown("##### 📈 Return Volume over Time")
                            if "Order Date" in enriched_df.columns:
                                try:
                                    df_dates = enriched_df.copy()
                                    df_dates["Order Date"] = pd.to_datetime(df_dates["Order Date"], errors="coerce").dt.date
                                    date_counts = df_dates["Order Date"].value_counts().reset_index()
                                    date_counts.columns = ["Date", "Count"]
                                    date_counts = date_counts.sort_values("Date")
                                    
                                    if not date_counts.empty:
                                        fig_trend = px.bar(
                                            date_counts,
                                            x="Date",
                                            y="Count",
                                            color_discrete_sequence=["#3b82f6"]
                                        )
                                        fig_trend.update_layout(
                                            margin=dict(t=10, b=10, l=10, r=10),
                                            xaxis_title=None,
                                            yaxis_title="Returned Orders",
                                            paper_bgcolor="rgba(0,0,0,0)",
                                            plot_bgcolor="rgba(0,0,0,0)"
                                        )
                                        st.plotly_chart(fig_trend, use_container_width=True, config={'displayModeBar': False})
                                    else:
                                        st.info("No valid dates to chart.")
                                except Exception as e:
                                    st.warning(f"Could not chart trends: {e}")
                            else:
                                st.info("No Order Date data available.")
                                
                        st.markdown("<br>", unsafe_allow_html=True)
                        col_chart3, col_chart4 = st.columns(2)
                        
                        with col_chart3:
                            st.markdown("##### ⚖️ Shipped vs Returned Volume")
                            if total_shipped > 0:
                                fig_comp = go.Figure(data=[
                                    go.Bar(name='Total Shipped', x=['Volume'], y=[total_shipped], marker_color='#10b981', text=[total_shipped], textposition='auto'),
                                    go.Bar(name='Returned', x=['Volume'], y=[total_matches], marker_color='#ef4444', text=[total_matches], textposition='auto')
                                ])
                                fig_comp.update_layout(
                                    barmode='group',
                                    margin=dict(t=10, b=10, l=10, r=10),
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)",
                                    yaxis_title="Order Count"
                                )
                                st.plotly_chart(fig_comp, use_container_width=True, config={'displayModeBar': False})
                            else:
                                st.info("Shipped volume data not available for this range.")
                                
                        with col_chart4:
                            st.markdown("##### 🏢 Outlet Wise Dispatch Returns")
                            if "Outlet" in enriched_df.columns:
                                outlet_counts = enriched_df["Outlet"].value_counts().reset_index()
                                outlet_counts.columns = ["Outlet", "Count"]
                                
                                fig_outlet = px.pie(
                                    outlet_counts, 
                                    names="Outlet", 
                                    values="Count",
                                    hole=0.4,
                                    color_discrete_sequence=px.colors.qualitative.Set3
                                )
                                fig_outlet.update_layout(
                                    margin=dict(t=10, b=10, l=10, r=10),
                                    showlegend=True,
                                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)"
                                )
                                st.plotly_chart(fig_outlet, use_container_width=True, config={'displayModeBar': False})
                            else:
                                st.info("No Outlet data available.")
                        
                        st.divider()
                        st.markdown("##### 📋 Matched Records")
                        st.dataframe(
                            enriched_df, 
                            use_container_width=True, 
                            hide_index=True,
                            column_config={
                                "Live Pathao Status": st.column_config.TextColumn(
                                    "Pathao Status",
                                    help="Live tracking status from Pathao",
                                ),
                                "Item Cost": st.column_config.NumberColumn(
                                    "Item Cost",
                                    format="৳ %d"
                                )
                            }
                        )
                        
                        # Export Report Option
                        import io
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                            full_df.to_excel(writer, index=False, sheet_name='Matched Returns')
                        excel_data = output.getvalue()
                        
                        st.download_button(
                            label="📥 Download Detailed Report (Excel)",
                            data=excel_data,
                            file_name="return_analytics_report.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary"
                        )
                        
                else:
                    st.warning("Could not find 'Order ID' in the Google Sheet.")
            
        except Exception as e:
            st.error(f"Failed to fetch or parse Return Analytics data from the provided URL. Error: {e}")


    st.markdown('</div>', unsafe_allow_html=True)
