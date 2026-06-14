import streamlit as st
import pandas as pd
from src.utils.safe_ops import safe_render

def render_return_analytics_tab():
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📉 Return Analytics")
    
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
                    selected_dates = st.date_input(
                        "Select Time Range", 
                        value=(min_date, max_date),
                        min_value=min_date,
                        max_value=max_date,
                        help="Filter the Google Sheet returns by date before matching.",
                        on_change=clear_enrichment
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
                            
                            with st.spinner("Fetching data from WooCommerce and Pathao (this runs in the background)..."):
                                from src.services.woocommerce.client import fetch_specific_woocommerce_orders
                                from src.services.pathao.status import get_pathao_order_status
                                from concurrent.futures import ThreadPoolExecutor
                                
                                try:
                                    # 1. Fetch WooCommerce Orders
                                    wc_orders = fetch_specific_woocommerce_orders(order_ids_to_fetch)
                                    wc_df = pd.DataFrame(wc_orders)
                                    
                                    # 2. Fetch Pathao Statuses
                                    pathao_statuses = {}
                                    if "Courier ID" in df_to_match.columns:
                                        courier_ids = df_to_match["Courier ID"].dropna().unique().tolist()
                                        
                                        def fetch_p_status(cid):
                                            res = get_pathao_order_status(cid)
                                            if "data" in res and "order_status" in res["data"]:
                                                return cid, res["data"]["order_status"]
                                            return cid, "Status Not Found"
                                        
                                        with ThreadPoolExecutor(max_workers=8) as executor:
                                            futures = [executor.submit(fetch_p_status, cid) for cid in courier_ids]
                                            for future in futures:
                                                cid, status = future.result()
                                                pathao_statuses[cid] = status
                                                
                                    # Append Pathao Status to df_to_match
                                    if pathao_statuses:
                                        df_to_match["Live Pathao Status"] = df_to_match["Courier ID"].map(pathao_statuses)
                                    else:
                                        df_to_match["Live Pathao Status"] = "N/A"
                                    
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
                        enriched_df = st.session_state["enriched_returns"]
                        full_df = st.session_state["full_enriched_returns"]
                        
                        st.divider()
                        
                        # Show some quick stats on the enriched data
                        st.markdown(
                            '<div class="metric-container">'
                            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Successful Matches</div><div class="metric-value">{len(enriched_df)}</div></div><div class="metric-icon">✅</div></div>'
                            '</div>',
                            unsafe_allow_html=True
                        )
                        
                        st.dataframe(
                            enriched_df, 
                            use_container_width=True, 
                            hide_index=True,
                            column_config={
                                "Live Pathao Status": st.column_config.TextColumn(
                                    "Pathao Status",
                                    help="Live tracking status from Pathao",
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
