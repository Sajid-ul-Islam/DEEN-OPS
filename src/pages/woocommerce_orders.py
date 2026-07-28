import streamlit as st
import pandas as pd
import plotly.express as px
import re
from src.pages.excel_exporter import export_to_styled_excel
from requests.auth import HTTPBasicAuth

from src.config.settings import get_woocommerce_config
from src.services.pathao.status import get_pathao_order_status
from src.utils.http import request_with_backoff

def extract_base_order_id(merchant_id):
    """Extracts base WooCommerce order ID from Pathao merchant ID variations."""
    text = str(merchant_id).strip()
    if text.lower() in ["nan", "none", ""]:
        return ""
    match = re.search(r'(?:M-|D-)?(\d+)(?:\s*[cws])?', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return text

def _update_wc_status(order_id, status):
    """Update WooCommerce order status via API."""
    wc_info = get_woocommerce_config(required=False)
    wc_url = wc_info.get("store_url")
    wc_key = wc_info.get("consumer_key")
    wc_secret = wc_info.get("consumer_secret")
    if not all([wc_url, wc_key, wc_secret]):
        return False
    url = f"{wc_url.rstrip('/')}/wp-json/wc/v3/orders/{order_id}"
    try:
        res = request_with_backoff(
            "PUT",
            url,
            json={"status": status},
            auth=HTTPBasicAuth(wc_key, wc_secret),
            timeout=10,
        )
        return res.status_code in [200, 201]
    except Exception:
        return False

def _render_live_orders_view():
    from src.components.ui_components import render_premium_header, render_metric_grid, apply_standard_dataframe
    render_premium_header("Order Tracking & Logistics Terminal", "Live sync with WooCommerce and Pathao Courier", "🛒")
    
    from datetime import datetime
    today = datetime.now().date()
    
    c_date, c_fetch, c_search = st.columns([1.5, 1, 2.5])
    
    with c_date:
        date_range = st.date_input("📅 WooCommerce Date Range", value=(today, today), help="Select dates to fetch orders")
        
    with c_fetch:
        st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
        if st.button("📥 Fetch Orders", use_container_width=True, type="primary"):
            from src.services.woocommerce.client import load_from_woocommerce
            st.session_state["wc_sync_mode"] = "Custom Range"
            if isinstance(date_range, tuple) and len(date_range) == 2:
                st.session_state["wc_sync_start_date"] = date_range[0]
                st.session_state["wc_sync_end_date"] = date_range[1]
            elif isinstance(date_range, tuple) and len(date_range) == 1:
                st.session_state["wc_sync_start_date"] = date_range[0]
                st.session_state["wc_sync_end_date"] = date_range[0]
            else:
                st.session_state["wc_sync_start_date"] = date_range
                st.session_state["wc_sync_end_date"] = date_range
                
            from datetime import time
            st.session_state["wc_sync_start_time"] = time(0, 0, 0)
            st.session_state["wc_sync_end_time"] = time(23, 59, 59)
            
            with st.spinner("Fetching orders from WooCommerce API..."):
                load_from_woocommerce.clear()
                res = load_from_woocommerce()
                st.session_state["wc_tracking_df"] = res.get("df_to_return")
                st.session_state["wc_pathao_statuses"] = {} # clear pathao cache for new orders
                
    df = st.session_state.get("wc_tracking_df")
    if df is None or df.empty:
        # Fallback to wc_curr_df if available
        df = st.session_state.get("wc_curr_df")
        if df is None or df.empty:
            st.info("👆 Please select a date range and click 'Fetch Orders' to load data.")
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
            from src.processing.categorization import get_category_for_sales
            from src.utils.product import is_bundle_or_combo
            df_copy["_Category"] = df_copy["Item Name"].apply(get_category_for_sales)
            df_copy["_CatQty"] = df_copy.apply(
                lambda r: (
                    r["_Category"], 
                    r["Quantity"], 
                    is_bundle_or_combo(r.get("Item Name"), r.get("SKU"), r.get("_Category"))
                ), 
                axis=1
            )
            
            def cat_agg(tuples_series):
                counts = {}
                bundle_found = False
                for cat, qty, is_bundle in tuples_series:
                    if is_bundle:
                        bundle_found = True
                        continue
                    try:
                        q = int(qty)
                    except:
                        q = 1
                    counts[cat] = counts.get(cat, 0) + q
                if not counts:
                    return "Bundle Offer" if bundle_found else "0 Items"
                return ", ".join([f"{q} {c}" for c, q in counts.items()])
                
            agg_funcs["_CatQty"] = cat_agg
            
        elif "Item Name" in df_copy.columns:
            agg_funcs["Item Name"] = lambda x: " | ".join(x.dropna().astype(str))

        display_df = df_copy.groupby("Order ID", as_index=False).agg(agg_funcs)
        
        if "_CatQty" in display_df.columns:
            display_df.rename(columns={"_CatQty": "Items"}, inplace=True)
            if "Item Name" in display_df.columns:
                display_df.drop(columns=["Item Name"], inplace=True)
    else:
        display_df = df_copy

    status_col = "Order Status" if "Order Status" in display_df.columns else "Status" if "Status" in display_df.columns else None
    amount_col = "Order Total Amount" if "Order Total Amount" in display_df.columns else "Total Amount" if "Total Amount" in display_df.columns else None
    if amount_col:
        display_df[amount_col] = pd.to_numeric(display_df[amount_col], errors="coerce").fillna(0).astype(int)
        
    date_col = "Order Date" if "Order Date" in display_df.columns else "Date" if "Date" in display_df.columns else None
    mod_date_col = "Order Date Modified" if "Order Date Modified" in display_df.columns else None

    search_query = ""
    status_filter = []
    
    if date_col:
        c_search, c_status, c_refresh = st.columns([1, 1.5, 0.8])
        
        with c_search:
            search_query = st.text_input("🔍 Global Search:", help="Search by Name, Phone, ID, etc.")
            
        with c_status:
            if status_col:
                statuses = display_df[status_col].dropna().unique().tolist()
                default_statuses = [s for s in statuses if str(s).lower() in ["processing", "shipped", "completed"]]
                if not default_statuses:
                    default_statuses = statuses
                status_filter = st.multiselect("Status:", statuses, default=default_statuses)

        # Pathao Tracking logic
        guess_col = next((col for col in display_df.columns if any(kw in col.lower() for kw in ["tracking", "consignment", "pathao"])), "None")
        tracking_col = guess_col
        max_sync = 15
        
        if tracking_col != "None":
            needs_auto_sync = "wc_pathao_statuses" not in st.session_state or not st.session_state["wc_pathao_statuses"]
            
            with c_refresh:
                st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
                if st.button(f"🔄 Sync Pathao", use_container_width=True, type="primary") or needs_auto_sync:
                    with st.spinner("Fetching live Pathao statuses..."):
                        live_statuses = dict(st.session_state.get("wc_pathao_statuses", {}))
                        unique_ids = []
                        seen_ids = set()
                        for cid in display_df[tracking_col]:
                            if len(unique_ids) >= max_sync:
                                break
                            clean_cid = str(cid).strip()
                            if pd.notna(cid) and clean_cid and clean_cid.lower() != "nan" and clean_cid not in seen_ids:
                                unique_ids.append(clean_cid)
                                seen_ids.add(clean_cid)
    
                        if not unique_ids:
                            st.warning("No valid consignment IDs found in the current filtered view.")
                        else:
                            progress_bar = st.progress(0)
                            total = len(unique_ids)
                            
                            for i, clean_cid in enumerate(unique_ids):
                                from src.services.pathao.status import get_pathao_order_status
                                res = get_pathao_order_status(clean_cid)
                                if "error" not in res:
                                    live_statuses[clean_cid] = res.get("data", {}).get("order_status", "Unknown")
                                else:
                                    live_statuses[clean_cid] = "API Error"
                                        
                                progress_bar.progress((i + 1) / total)
                                
                            st.session_state["wc_pathao_statuses"] = live_statuses
                            st.toast(f"🔍 Pathao statuses refreshed for {len(unique_ids)} consignments.")

    # --- APPLY FILTERS ---
    if search_query:
        mask = display_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False, na=False)).any(axis=1)
        display_df = display_df[mask]
        
    if status_filter and status_col:
        display_df = display_df[display_df[status_col].isin(status_filter)]

    if tracking_col != "None" and "wc_pathao_statuses" in st.session_state:

            display_df["Pathao Status"] = display_df[tracking_col].astype(str).str.strip().map(st.session_state["wc_pathao_statuses"]).fillna("Not Fetched")

    # Top-level operational metrics
    total_orders = len(display_df)
    total_revenue = display_df[amount_col].sum() if amount_col else 0
    processing = 0
    completed = 0
    if status_col:
        processing = len(display_df[display_df[status_col].astype(str).str.lower().str.contains("processing")])
        completed = len(display_df[display_df[status_col].astype(str).str.lower().str.contains("completed")])
        
    metrics_html = (
        '<div class="metric-container">'
        f'<div class="metric-card"><div><div class="metric-label">FILTERED ORDERS</div><div class="metric-value">{total_orders:,.0f}</div></div><div class="metric-icon">📦</div></div>'
        f'<div class="metric-card"><div><div class="metric-label">FILTERED REVENUE</div><div class="metric-value">TK {total_revenue:,.0f}</div></div><div class="metric-icon">৳</div></div>'
        f'<div class="metric-card"><div><div class="metric-label">PROCESSING</div><div class="metric-value">{processing:,.0f}</div></div><div class="metric-icon">⏳</div></div>'
        f'<div class="metric-card"><div><div class="metric-label">COMPLETED</div><div class="metric-value">{completed:,.0f}</div></div><div class="metric-icon">✅</div></div>'
        '</div>'
    )
    st.markdown(metrics_html, unsafe_allow_html=True)

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
                
                
                perf_html = (
                    '<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-top: 1rem;">'
                    f'<div style="background: rgba(16, 185, 129, 0.1); padding: 1rem; border-radius: 0.5rem; border: 1px solid rgba(16, 185, 129, 0.2);"><div style="font-size: 0.8rem; color: #9ca3af; font-weight: 600;">SUCCESS RATE</div><div style="font-size: 1.5rem; font-weight: 700; color: #10b981;">{success_rate:.1f}%</div></div>'
                    f'<div style="background: rgba(59, 130, 246, 0.1); padding: 1rem; border-radius: 0.5rem; border: 1px solid rgba(59, 130, 246, 0.2);"><div style="font-size: 0.8rem; color: #9ca3af; font-weight: 600;">DELIVERED</div><div style="font-size: 1.5rem; font-weight: 700; color: #3b82f6;">{int(delivered)}</div></div>'
                    f'<div style="background: rgba(245, 158, 11, 0.1); padding: 1rem; border-radius: 0.5rem; border: 1px solid rgba(245, 158, 11, 0.2);"><div style="font-size: 0.8rem; color: #9ca3af; font-weight: 600;">RESOLVED</div><div style="font-size: 1.5rem; font-weight: 700; color: #f59e0b;">{int(resolved)}</div></div>'
                    f'<div style="background: rgba(239, 68, 68, 0.1); padding: 1rem; border-radius: 0.5rem; border: 1px solid rgba(239, 68, 68, 0.2);"><div style="font-size: 0.8rem; color: #9ca3af; font-weight: 600;">FAILED / RETURNED</div><div style="font-size: 1.5rem; font-weight: 700; color: #ef4444;">{int(failed_returned)}</div></div>'
                    '</div>'
                )
                st.markdown(perf_html, unsafe_allow_html=True)
                
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
                        from src.components.ui_components import render_metric_grid
                        render_metric_grid([{"label": "Average Transit Time", "value": f"{avg_transit:.1f} Days", "icon": "🚚"}])

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
                            st.toast(f"Live Status: **{data.get('order_status', 'Unknown')}** | Payment: **{data.get('payment_status', 'Unknown')}**")

    st.markdown("### 📋 Raw Order Data", help="You can click on column headers to sort, or hover over the top right of the table to download as CSV/Excel or view fullscreen.")
    
    # Pre-process columns to add emojis for instant visual recognition
    if status_col and status_col in display_df.columns:
        def add_wc_emoji(status):
            s = str(status).lower()
            if any(x in s for x in ['completed', 'shipped', 'confirmed']): return f"🟢 {status}"
            if 'processing' in s: return f"🔵 {status}"
            if any(x in s for x in ['on-hold', 'pending', 'waiting']): return f"🟡 {status}"
            if any(x in s for x in ['cancel', 'fail', 'refund', 'trash']): return f"🔴 {status}"
            return status
        display_df[status_col] = display_df[status_col].apply(add_wc_emoji)

    if "Pathao Status" in display_df.columns:
        def add_pathao_emoji(status):
            s = str(status).lower()
            if 'delivered' in s: return f"🟢 {status}"
            if any(x in s for x in ['return', 'failed', 'cancel', 'error']): return f"🔴 {status}"
            if any(x in s for x in ['transit', 'processing', 'assigned']): return f"🔵 {status}"
            if 'not fetched' in s: return f"⚪ {status}"
            return f"🟡 {status}"
        display_df["Pathao Status"] = display_df["Pathao Status"].apply(add_pathao_emoji)

    # Configure specific column formats
    column_configuration = {}
    if date_col:
        display_df[date_col] = pd.to_datetime(display_df[date_col], errors='coerce')
        column_configuration[date_col] = st.column_config.DatetimeColumn(
            "📅 Order Date",
            format="D MMM YYYY, h:mm a",
        )
        
    if mod_date_col:
        display_df[mod_date_col] = pd.to_datetime(display_df[mod_date_col], errors='coerce')
        column_configuration[mod_date_col] = st.column_config.DatetimeColumn(
            "🔄 Last Modified",
            format="D MMM YYYY, h:mm a",
        )
        
    if amount_col:
        # Cast to integer safely before formatting to prevent Streamlit float rendering bugs
        display_df[amount_col] = pd.to_numeric(display_df[amount_col], errors="coerce").fillna(0).astype(int)
        column_configuration[amount_col] = st.column_config.NumberColumn(
            "💰 Total Amount",
            help="Total order amount in BDT",
            format="৳ %d",
        )
        
    column_configuration["Order Number"] = None
    column_configuration["Pathao Consignment ID"] = st.column_config.TextColumn(
        "📦 Consignment ID",
    )

    # Sort orders by Date descending
    if date_col in display_df.columns:
        display_df = display_df.sort_values(by=date_col, ascending=False)

    # Drop unnecessary address and internal columns
    cols_to_drop = [
        "Shipping Address 1", "Shipping City", "State Name (Billing)", 
        "Payment Method Title", "dt_parsed", "mod_dt_parsed", "SKU", "Item Cost"
    ]
    display_df = display_df.drop(columns=[c for c in cols_to_drop if c in display_df.columns])

    # Reorder to put Pathao Consignment ID right after Order ID
    if "Order ID" in display_df.columns and "Pathao Consignment ID" in display_df.columns:
        cols = list(display_df.columns)
        cols.remove("Pathao Consignment ID")
        if "Pathao Status" in cols:
            cols.remove("Pathao Status")
            
        order_idx = cols.index("Order ID")
        cols.insert(order_idx + 1, "Pathao Consignment ID")
        if "Pathao Status" in display_df.columns:
            cols.insert(order_idx + 2, "Pathao Status")
            
        display_df = display_df[cols]

    styled_df = display_df.style

    if "Pathao Status" in display_df.columns:
        def highlight_pathao_status(col):
            return [
                'background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 600;' 
                if '🔴' in str(v)
                else 'background-color: rgba(16, 185, 129, 0.15); color: #10b981; font-weight: 600;' if '🟢' in str(v)
                else 'color: #3b82f6; font-weight: 500;' if '🔵' in str(v)
                else 'color: rgba(255,255,255,0.5); font-style: italic;' if '⚪' in str(v)
                else 'color: #f59e0b; font-weight: 500;'
                for v in col
            ]
        styled_df = styled_df.apply(highlight_pathao_status, subset=['Pathao Status'])
        
    if status_col and status_col in display_df.columns:
        def highlight_wc_status(col):
            return [
                'background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 600;' 
                if '🔴' in str(v)
                else 'background-color: rgba(16, 185, 129, 0.15); color: #10b981; font-weight: 600;' if '🟢' in str(v)
                else 'color: #3b82f6; font-weight: 500;' if '🔵' in str(v)
                else 'color: #f59e0b; font-weight: 500;' if '🟡' in str(v)
                else ''
                for v in col
            ]
        styled_df = styled_df.apply(highlight_wc_status, subset=[status_col])

    st.dataframe(
        styled_df, 
        use_container_width=False, 
        height=600, 
        column_config=column_configuration,
        hide_index=True
    )

def render_woocommerce_orders_tab():
    """Renders the WooCommerce Operations module."""
    st.markdown("<h2 style='color: #6366f1;'>🛒 WooCommerce Operations</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity: 0.8;'>Live synchronization view and tracking for WooCommerce operations.</p>", unsafe_allow_html=True)
    st.divider()

    _render_live_orders_view()

    st.markdown("<div style='margin-top: 50px;'></div>", unsafe_allow_html=True)
    st.divider()
    st.markdown("### :material/local_shipping: WooCommerce × Pathao Bulk Status Sync")
    st.markdown("Match WooCommerce orders with a Pathao CSV/Excel export and update statuses directly.")

    wc_df = st.session_state.get("wc_full_df")
    if wc_df is None or wc_df.empty:
        wc_df = st.session_state.get("wc_curr_df")

    if wc_df is None or wc_df.empty:
        st.warning("⚠️ No active WooCommerce order data found. Please trigger a sync from the **Live Dashboard** first.")
        return

    c1, c2 = st.columns([1, 2])
    with c1:
        st.info(f"Loaded {wc_df['Order ID'].nunique()} WooCommerce Orders from session cache.")

    with c2:
        pathao_file = st.file_uploader("Upload Pathao Export (CSV/Excel)", type=["csv", "xlsx"], key="wc_pathao_up")

        # Create WC Base
        track_df = wc_df[["Order ID", "Order Status"]].copy().drop_duplicates(subset=["Order ID"])
        track_df.rename(columns={"Order ID": "Order Number", "Order Status": "WC Status"}, inplace=True)
        track_df["Order Number"] = track_df["Order Number"].astype(str)

        if pathao_file is not None:
            try:
                if pathao_file.name.endswith(".csv"):
                    pathao_df = pd.read_csv(pathao_file)
                else:
                    pathao_df = pd.read_excel(pathao_file)

                # Identify columns
                cols = [str(c) for c in pathao_df.columns]
                merchant_col = next((c for c in cols if "merchant" in c.lower() and "order" in c.lower()), None)
                if not merchant_col:
                    merchant_col = next((c for c in cols if "order" in c.lower() or "merchant" in c.lower()), cols[0])

                consignment_col = next((c for c in cols if "consignment" in c.lower() or "tracking" in c.lower()), None)
                if not consignment_col:
                    consignment_col = cols[1] if len(cols) > 1 else cols[0]

                p_status_col = next((c for c in cols if "status" in c.lower() and "payment" not in c.lower()), None)
                if not p_status_col:
                    p_status_col = cols[2] if len(cols) > 2 else cols[0]

                pathao_df["Base_WC_ID"] = pathao_df[merchant_col].apply(extract_base_order_id)
                pathao_df["Base_WC_ID"] = pathao_df["Base_WC_ID"].astype(str)

                # Merge
                merged_df = pd.merge(track_df, pathao_df, left_on="Order Number", right_on="Base_WC_ID", how="left")

                display_df = merged_df[["Order Number", "WC Status", merchant_col, consignment_col, p_status_col]].copy()
                display_df.rename(columns={
                    merchant_col: "Pathao ID",
                    consignment_col: "Consignment",
                    p_status_col: "Pathao Status"
                }, inplace=True)
                display_df.fillna("Not Found", inplace=True)

            except Exception as e:
                st.error(f"Error processing Pathao file: {e}")
                display_df = None
        else:
            display_df = track_df.copy()
            display_df["Pathao ID"] = "Pending Upload"
            display_df["Consignment"] = "Pending Upload"
            display_df["Pathao Status"] = "Pending Upload"

        if display_df is not None:
            c_info, c_action = st.columns([2, 1])
            with c_info:
                st.write("Edit the **WC Status** column to apply changes to WooCommerce.")
                
            if pathao_file is not None:
                unmatched_df = display_df[display_df["Pathao ID"] == "Not Found"].copy()
                if not unmatched_df.empty:
                    with c_action:
                        excel_bytes = export_to_styled_excel({"Unmatched Orders": unmatched_df})
                        st.download_button(
                            label=f"📥 Download {len(unmatched_df)} Unmatched Orders",
                            data=excel_bytes,
                            file_name="Unmatched_WC_Orders.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )

            status_options = ["processing", "on-hold", "pending", "waiting", "completed", "shipped", "confirmed", "cancelled", "refunded", "failed"]
            display_df["WC Status"] = display_df["WC Status"].astype(str).str.lower()

            edited_df = st.data_editor(
                display_df,
                column_config={
                    "Order Number": st.column_config.TextColumn("Order Number", disabled=True),
                    "WC Status": st.column_config.SelectboxColumn("WC Status", options=status_options, required=True),
                    "Pathao ID": st.column_config.TextColumn("Pathao ID", disabled=True),
                    "Consignment": st.column_config.TextColumn("Consignment", disabled=True),
                    "Pathao Status": st.column_config.TextColumn("Pathao Status", disabled=True),
                },
                disabled=["Order Number", "Pathao ID", "Consignment", "Pathao Status"],
                use_container_width=True,
                key="wc_pathao_tracker_editor",
                height=600,
                hide_index=False
            )

            changes = st.session_state.get("wc_pathao_tracker_editor", {}).get("edited_rows", {})
            if changes:
                st.warning(f"You have {len(changes)} pending status updates.")
                if st.button("Apply Status Changes to WooCommerce", type="primary", key="apply_wc_status_changes"):
                    with st.spinner("Updating WooCommerce..."):
                        success_count = 0
                        for row_idx, col_changes in changes.items():
                            if "WC Status" in col_changes:
                                new_status = col_changes["WC Status"]
                                order_id = display_df.iloc[row_idx]["Order Number"]
                                if _update_wc_status(order_id, new_status):
                                    success_count += 1

                        st.toast(f"✅ Successfully applied {success_count} updates!")
