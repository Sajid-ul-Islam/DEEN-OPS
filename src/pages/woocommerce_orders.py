import streamlit as st
import pandas as pd

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

    st.markdown("### 📋 Raw Order Data")
    
    # Configure specific column formats
    column_configuration = {}
    if date_col:
        display_df[date_col] = pd.to_datetime(display_df[date_col], errors='coerce')
        column_configuration[date_col] = st.column_config.DatetimeColumn(
            "Order Date",
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

    st.dataframe(
        display_df, 
        use_container_width=True, 
        height=600,
        column_config=column_configuration
    )