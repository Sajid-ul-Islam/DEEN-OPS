import streamlit as st
import pandas as pd
import plotly.express as px
from src.services.pathao.status import get_pathao_order_status

def render_woocommerce_orders_tab():
    """Renders the WooCommerce Orders list module."""
    st.markdown("<h2 style='color: #6366f1;'>🛒 WooCommerce Orders List</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity: 0.8;'>Live synchronization view of your current WooCommerce operations.</p>", unsafe_allow_html=True)
    st.divider()

    # Fetch the WooCommerce Dataframe from session state
    df = st.session_state.get("wc_curr_df")

    if df is None or df.empty:
        st.warning("⚠️ No active WooCommerce order data found. Please trigger a sync from the **Live Dashboard** first.")
        return

    df_copy = df.copy()

    # Unique Order-Wise View Aggregation
    if "Order ID" in df_copy.columns:
        agg_funcs = {}
        for col in df_copy.columns:
            if col == "Item Name":
                pass 
            elif col == "Quantity":
                agg_funcs[col] = "sum"
            elif col in ["Total Amount", "Order Total Amount"]:
                agg_funcs[col] = "first" 
            elif col != "Order ID":
                agg_funcs[col] = "first"
                
        if "Item Name" in df_copy.columns and "Quantity" in df_copy.columns:
            df_copy["_Formatted_Item"] = df_copy.apply(lambda row: f"{row['Item Name']} (x{row['Quantity']})", axis=1)
            agg_funcs["_Formatted_Item"] = lambda x: " | ".join(x.dropna().astype(str))
        elif "Item Name" in df_copy.columns:
            agg_funcs["Item Name"] = lambda x: " | ".join(x.dropna().astype(str))

        display_df = df_copy.groupby("Order ID", as_index=False).agg(agg_funcs)
        
        if "_Formatted_Item" in display_df.columns:
            display_df.rename(columns={"_Formatted_Item": "Items"}, inplace=True)
            if "Item Name" in display_df.columns:
                display_df.drop(columns=["Item Name"], inplace=True)
    else:
        display_df = df_copy

    status_col = "Order Status" if "Order Status" in display_df.columns else "Status" if "Status" in display_df.columns else None
    amount_col = "Order Total Amount" if "Order Total Amount" in display_df.columns else "Total Amount" if "Total Amount" in display_df.columns else None
    date_col = "Order Date" if "Order Date" in display_df.columns else "Date" if "Date" in display_df.columns else None
    mod_date_col = "Order Date Modified" if "Order Date Modified" in display_df.columns else None

    # Advanced Multi-Column Filter Sidebar
    with st.sidebar:
        st.markdown("### 🎛️ Order Filters")
        
        # Search Filter
        search_query = st.text_input("🔍 Global Search:", help="Search by Name, Phone, ID, etc.")
        
        # Status Filter
        status_filter = []
        if status_col:
            statuses = display_df[status_col].dropna().unique().tolist()
            status_filter = st.multiselect("Status:", statuses, default=statuses)

        # Total Amount Range Filter
        amount_filter = None
        if amount_col:
            display_df[amount_col] = pd.to_numeric(display_df[amount_col], errors='coerce').fillna(0)
            min_amt = float(display_df[amount_col].min())
            max_amt = float(display_df[amount_col].max())
            if min_amt < max_amt:
                amount_filter = st.slider("Total Amount Range:", min_value=min_amt, max_value=max_amt, value=(min_amt, max_amt))

        st.divider()
        st.markdown("### 📦 Pathao Tracking")
        tracking_col_options = ["None"] + list(display_df.columns)
        guess_col = next((col for col in display_df.columns if any(kw in col.lower() for kw in ["tracking", "consignment", "pathao"])), "None")
        
        tracking_col = st.selectbox("Tracking ID Column", tracking_col_options, index=tracking_col_options.index(guess_col), help="Select the column containing Pathao Consignment IDs.")
        
        if tracking_col != "None":
            if st.button("Refresh Live Statuses", use_container_width=True, type="primary"):
                with st.spinner("Fetching live Pathao statuses..."):
                    live_statuses = dict(st.session_state.get("wc_pathao_statuses", {}))
                    unique_ids = []
                    seen_ids = set()
                    for cid in display_df[tracking_col]:
                        clean_cid = str(cid).strip()
                        if pd.notna(cid) and clean_cid and clean_cid.lower() != "nan" and clean_cid not in seen_ids:
                            unique_ids.append(clean_cid)
                            seen_ids.add(clean_cid)

                    if not unique_ids:
                        st.warning("No valid consignment IDs found in the selected column.")
                    else:
                        progress_bar = st.progress(0)
                        total = len(unique_ids)
                        
                        for i, clean_cid in enumerate(unique_ids):
                            res = get_pathao_order_status(clean_cid)
                            if "error" not in res:
                                live_statuses[clean_cid] = res.get("data", {}).get("order_status", "Unknown")
                            else:
                                live_statuses[clean_cid] = "API Error"
                                    
                            progress_bar.progress((i + 1) / total)
                            
                        st.session_state["wc_pathao_statuses"] = live_statuses
                        st.success(f"Pathao statuses refreshed for {len(unique_ids)} consignments.")

        if tracking_col != "None" and "wc_pathao_statuses" in st.session_state:
            display_df["Pathao Status"] = display_df[tracking_col].astype(str).str.strip().map(st.session_state["wc_pathao_statuses"]).fillna("Not Fetched")

    # Apply Filters
    if search_query:
        mask = display_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False, na=False)).any(axis=1)
        display_df = display_df[mask]
        
    if status_filter and status_col:
        display_df = display_df[display_df[status_col].isin(status_filter)]
        
    if amount_filter and amount_col:
        display_df = display_df[(display_df[amount_col] >= amount_filter[0]) & (display_df[amount_col] <= amount_filter[1])]

    # Top-level operational metrics
    total_orders = len(display_df)
    total_revenue = display_df[amount_col].sum() if amount_col else 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Filtered Orders", total_orders)
    c2.metric("Filtered Revenue", f"৳{total_revenue:,.0f}")
    
    if status_col:
        processing = len(display_df[display_df[status_col].astype(str).str.lower() == "processing"])
        c3.metric("Processing Orders", processing)
        completed = len(display_df[display_df[status_col].astype(str).str.lower() == "completed"])
        c4.metric("Completed Orders", completed)

    if "Pathao Status" in display_df.columns:
        valid_statuses = display_df[display_df["Pathao Status"] != "Not Fetched"]
        if not valid_statuses.empty:
            st.divider()
            st.markdown("### 📊 Pathao Status Breakdown")
            status_counts = valid_statuses["Pathao Status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            
            color_map = {}
            for status in status_counts["Status"]:
                s_lower = str(status).lower()
                if any(x in s_lower for x in ['return', 'failed', 'cancel', 'error']):
                    color_map[status] = '#ef4444'
                elif 'delivered' in s_lower:
                    color_map[status] = '#10b981'
                elif any(x in s_lower for x in ['transit', 'processing', 'assigned']):
                    color_map[status] = '#3b82f6'
                else:
                    color_map[status] = '#f59e0b'
                    
            c_chart, c_metric = st.columns([1, 1])
            with c_chart:
                fig = px.pie(status_counts, names="Status", values="Count", hole=0.5, color="Status", color_discrete_map=color_map)
                fig.update_traces(textposition='inside', textinfo='percent+label')
                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

            with c_metric:
                st.markdown("#### 🎯 Delivery Performance")
                delivered = status_counts[status_counts["Status"].str.lower().str.contains('delivered')]["Count"].sum()
                failed_returned = status_counts[status_counts["Status"].str.lower().str.contains('return|failed|cancel|error')]["Count"].sum()
                resolved = delivered + failed_returned
                
                success_rate = (delivered / resolved * 100) if resolved > 0 else 0
                
                c_m1, c_m2 = st.columns(2)
                c_m1.metric("Success Rate", f"{success_rate:.1f}%", help="Based on resolved orders (Delivered vs Returned/Failed/Cancelled).")
                c_m2.metric("Total Resolved", int(resolved))
                
                c_m3, c_m4 = st.columns(2)
                c_m3.metric("Delivered", int(delivered))
                c_m4.metric("Failed/Returned", int(failed_returned))
                
            if date_col:
                ts_df = valid_statuses.copy()
                ts_df["Day"] = pd.to_datetime(ts_df[date_col], errors='coerce').dt.date
                resolved_mask = ts_df["Pathao Status"].astype(str).str.lower().str.contains('delivered|return|failed|cancel|error')
                ts_resolved = ts_df[resolved_mask].copy()
                if not ts_resolved.empty:
                    ts_resolved['Is_Delivered'] = ts_resolved["Pathao Status"].astype(str).str.lower().str.contains('delivered')
                    daily_sr = ts_resolved.groupby("Day").agg(
                        Total_Resolved=("Is_Delivered", "count"),
                        Delivered=("Is_Delivered", "sum")
                    ).reset_index()
                    daily_sr["Success Rate (%)"] = (daily_sr["Delivered"] / daily_sr["Total_Resolved"] * 100).round(1)
                    daily_sr = daily_sr.sort_values("Day")
                    
                    fig_sr = px.line(
                        daily_sr, x="Day", y="Success Rate (%)", 
                        title="📈 Daily Success Rate Over Time", markers=True,
                        color_discrete_sequence=['#10b981'], hover_data={"Delivered": True, "Total_Resolved": True}
                    )
                    fig_sr.update_layout(yaxis_range=[0, 105], margin=dict(t=40, b=20, l=10, r=10))
                    st.plotly_chart(fig_sr, use_container_width=True)

            if date_col and mod_date_col:
                delivered_df = valid_statuses[valid_statuses["Pathao Status"].astype(str).str.lower().str.contains("delivered")].copy()
                if not delivered_df.empty:
                    st.divider()
                    st.markdown("### ⏱️ Delivery Transit Times")
                    
                    delivered_df["Transit Days"] = (pd.to_datetime(delivered_df[mod_date_col], errors='coerce') - pd.to_datetime(delivered_df[date_col], errors='coerce')).dt.days
                    delivered_df = delivered_df[(delivered_df["Transit Days"] >= 0) & (delivered_df["Transit Days"] < 60)]
                    
                    if not delivered_df.empty:
                        avg_transit = delivered_df["Transit Days"].mean()
                        st.metric("Average Transit Time", f"{avg_transit:.1f} Days", help="Average days from Order Creation to Delivery.")

                        transit_counts = delivered_df["Transit Days"].value_counts().reset_index()
                        transit_counts.columns = ["Transit Days", "Order Count"]
                        transit_counts = transit_counts.sort_values("Transit Days")
                        transit_counts["Transit Days Label"] = transit_counts["Transit Days"].astype(str) + " Days"
                        
                        fig_transit = px.bar(
                            transit_counts, 
                            x="Transit Days Label", 
                            y="Order Count", 
                            title="Transit Time Distribution (Delivered Orders)",
                            text_auto=True,
                            color_discrete_sequence=['#3b82f6']
                        )
                        fig_transit.update_layout(xaxis_title="Days from Order to Delivery", yaxis_title="Number of Orders", margin=dict(t=40, b=20, l=10, r=10))
                        st.plotly_chart(fig_transit, use_container_width=True)

    with st.expander("📦 Quick Pathao Track"):
        c_id, c_btn = st.columns([3, 1])
        with c_id:
            quick_cid = st.text_input("Consignment ID", placeholder="e.g., DD...", key="wc_quick_track")
        with c_btn:
            st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
            if st.button("Check Status", use_container_width=True, key="wc_quick_btn"):
                if quick_cid:
                    with st.spinner("Checking..."):
                        res = get_pathao_order_status(quick_cid.strip())
                        if "error" in res:
                            st.error(res["error"])
                        else:
                            data = res.get("data", {})
                            st.success(f"Live Status: **{data.get('order_status', 'Unknown')}** | Payment: **{data.get('payment_status', 'Unknown')}**")

    st.markdown("### 📋 Raw Order Data")
    
    # Configure specific column formats
    column_configuration = {}
    if date_col:
        display_df[date_col] = pd.to_datetime(display_df[date_col], errors='coerce')
        column_configuration[date_col] = st.column_config.DatetimeColumn(
            "Order Date",
            format="D MMM YYYY, h:mm a",
        )
        
    if mod_date_col:
        display_df[mod_date_col] = pd.to_datetime(display_df[mod_date_col], errors='coerce')
        column_configuration[mod_date_col] = st.column_config.DatetimeColumn(
            "Last Modified",
            format="D MMM YYYY, h:mm a",
        )
        
    if amount_col:
        column_configuration[amount_col] = st.column_config.NumberColumn(
            "Total Amount",
            help="Total order amount in BDT",
            format="৳ %.2f",
        )

    # Sort orders by Date descending
    if date_col in display_df.columns:
        display_df = display_df.sort_values(by=date_col, ascending=False)

    if "Pathao Status" in display_df.columns:
        def highlight_pathao_status(col):
            return [
                'background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 600;' 
                if any(x in str(v).lower() for x in ['return', 'failed', 'cancel', 'error'])
                else 'color: #10b981;' if 'delivered' in str(v).lower()
                else ''
                for v in col
            ]
        styled_df = display_df.style.apply(highlight_pathao_status, subset=['Pathao Status'])
        st.dataframe(styled_df, use_container_width=True, height=600, column_config=column_configuration)
    else:
        st.dataframe(
            display_df, 
            use_container_width=True, 
            height=600,
            column_config=column_configuration
        )
