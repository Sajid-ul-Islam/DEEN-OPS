import streamlit as st
import pandas as pd
import io
from datetime import datetime
from src.pages.excel_exporter import export_to_styled_excel

def render_excel_merger_tab():
    st.subheader("📑 Product Listing")
    st.markdown("Generate a consolidated product listing by merging unique items and summing their quantities.")
    
    source_opts = ["WooCommerce Orders", "Upload File"]
    if hasattr(st, "pills"):
        source_mode = st.pills("Select Source", source_opts, default=source_opts[0], selection_mode="single")
        if not source_mode: 
            source_mode = source_opts[0]
    else:
        source_mode = st.radio("Select Source", source_opts, horizontal=True)
    
    if source_mode == "WooCommerce Orders":
        c1, c2 = st.columns(2)
        with c1:
            status_options = ["processing", "on-hold", "pending", "completed", "shipped", "confirmed"]
            selected_statuses = st.multiselect("Order Statuses", status_options, default=["processing", "on-hold"])
        with c2:
            st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
            if st.button("🔗 Pull Orders", type="primary", use_container_width=True):
                wc_full = st.session_state.get("wc_full_df")
                if wc_full is not None and not wc_full.empty:
                    st.session_state.merger_df = wc_full[wc_full["Order Status"].astype(str).str.lower().isin(selected_statuses)].copy()
                    st.session_state.pop("merger_wc_stock_df", None)
                    st.success(f"Pulled {len(st.session_state.merger_df)} items from Live Dashboard cache.")
                else:
                    st.error("Live Dashboard data not found. Please wait for sync or visit the Live Dashboard first.")
    else:
        uploaded_file = st.file_uploader("Upload Excel or CSV File", type=["xlsx", "xls", "csv"])
        if uploaded_file is not None:
            file_id = f"{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.get("merger_file_id") != file_id:
                if uploaded_file.name.endswith('.csv'):
                    st.session_state.merger_df = pd.read_csv(uploaded_file)
                else:
                    st.session_state.merger_df = pd.read_excel(uploaded_file)
                st.session_state.merger_file_id = file_id
                st.session_state.pop("merger_wc_stock_df", None)
            st.success("File uploaded successfully!")
            
    df = st.session_state.get("merger_df")
            
    if df is not None and not df.empty:
        try:
            st.markdown("### Preview Original Data")
            st.dataframe(df.head())
            
            columns = df.columns.tolist()
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                item_name_idx = next((i for i, col in enumerate(columns) if "name" in str(col).lower() or "item" in str(col).lower() or "product" in str(col).lower()), 0)
                item_col = st.selectbox("Select Item Name Column", columns, index=item_name_idx)
                
            with col2:
                sku_idx = next((i + 1 for i, col in enumerate(columns) if "sku" in str(col).lower() or "code" in str(col).lower()), 0)
                sku_col = st.selectbox("Select SKU Column (Optional)", ["None"] + columns, index=sku_idx)
                
            with col3:
                qty_idx = next((i for i, col in enumerate(columns) if "qty" in str(col).lower() or "quantity" in str(col).lower() or "amount" in str(col).lower()), 0)
                qty_col = st.selectbox("Select Quantity Column", columns, index=qty_idx)
                
            with col4:
                order_idx = next((i + 1 for i, col in enumerate(columns) if "order" in str(col).lower() or "id" in str(col).lower()), 0)
                order_col = st.selectbox("Select Order Column (Optional)", ["None"] + columns, index=order_idx)
                
            st.divider()
            st.markdown("### 📋 Stock Count From Outlet")
            st.write("Generate a clean product list format for outlets to report their stock counts (Independent Option).")
            titles_all = []
            from src.inventory.core import item_name_to_title_size
            for item in df[item_col].dropna().unique():
                title, _ = item_name_to_title_size(str(item))
                if title:
                    titles_all.append(title.strip())
            unique_titles_all = sorted(list(set(titles_all)))
            all_csv_data = pd.DataFrame({"Products Name": unique_titles_all}).to_csv(index=False)
            
            c_prod1, _ = st.columns([1, 2])
            with c_prod1:
                st.download_button(
                    "📥 Download Stock Count Format (CSV)",
                    data=all_csv_data,
                    file_name=f"{datetime.now().strftime('%Y-%m-%d')}_stock_count_outlet.csv",
                    mime="text/csv",
                    use_container_width=True,
                    type="secondary"
                )
                
            st.divider()
            st.markdown("### Inventory Check Options")
            c_inv1, c_inv2 = st.columns(2)
            with c_inv1:
                check_web_stock = st.checkbox("Fetch WooCommerce Web Stock", value=False)
            with c_inv2:
                manual_outlet_file = st.file_uploader("Upload Manual Outlet Stock (Optional)", type=["xlsx", "xls", "csv"], key="outlet_stock_up")
                
            c_act1, c_act2 = st.columns(2)
            with c_act1:
                execute = st.button("Execute Merge & Check", type="primary", use_container_width=True)
            with c_act2:
                if st.button("Clear Source Data", use_container_width=True):
                    st.session_state.pop("merger_df", None)
                    st.session_state.pop("merger_wc_stock_df", None)
                    st.session_state.pop("merger_file_id", None)
                    st.rerun()
                    
            if execute:
                with st.spinner("Processing..."):
                    # Ensure the quantity column is numeric
                    df[qty_col] = pd.to_numeric(df[qty_col], errors='coerce').fillna(0)
                    
                    # Group by Item Name (and SKU if selected) and sum Quantity
                    if sku_col != "None":
                        merged_df = df.groupby([item_col, sku_col], as_index=False)[qty_col].sum()
                    else:
                        merged_df = df.groupby(item_col, as_index=False)[qty_col].sum()
                    
                    # Sort by item name ascending for easier product listing verification
                    merged_df = merged_df.sort_values(by=item_col, ascending=True).reset_index(drop=True)
                    
                    # --- Inventory Checking ---
                    if check_web_stock:
                        wocom_df = st.session_state.get("wc_stock_df")
                        
                        if wocom_df is None or wocom_df.empty:
                            wocom_df = st.session_state.get("merger_wc_stock_df")
                            
                        if wocom_df is None or wocom_df.empty:
                            from src.services.woocommerce.stock import fetch_woocommerce_stock
                            from src.inventory.core import item_name_to_title_size
                            
                            t_skus = set(merged_df[sku_col].dropna().astype(str).unique()) if sku_col != "None" else None
                            t_titles = set()
                            for item in merged_df[item_col].dropna():
                                title, _ = item_name_to_title_size(str(item))
                                if title: t_titles.add(title.strip().lower())
                                
                            wocom_df = fetch_woocommerce_stock(filter_skus=t_skus, filter_titles=t_titles)
                            st.session_state.merger_wc_stock_df = wocom_df
                        
                        if wocom_df is not None and not wocom_df.empty:
                            wocom_df = wocom_df.copy()
                            if sku_col != "None" and "SKU" in wocom_df.columns:
                                wc_stock_map = wocom_df.groupby("SKU")["Stock"].sum().to_dict()
                                merged_df["Web Stock"] = merged_df[sku_col].astype(str).map(wc_stock_map).fillna(0)
                            else:
                                from src.utils.product import get_base_product_name
                                if "Clean_Product" not in wocom_df.columns:
                                    wocom_df["Clean_Product"] = wocom_df["Product"].apply(get_base_product_name)
                                wc_stock_map = wocom_df.groupby("Product")["Stock"].sum().to_dict()
                                wc_clean_map = wocom_df.groupby("Clean_Product")["Stock"].sum().to_dict()
                                
                                def get_wc_stock(name):
                                    if name in wc_stock_map: return wc_stock_map[name]
                                    clean_name = get_base_product_name(str(name))
                                    return wc_clean_map.get(clean_name, 0)
                                    
                                merged_df["Web Stock"] = merged_df[item_col].apply(get_wc_stock)
                                
                    if manual_outlet_file is not None:
                        if manual_outlet_file.name.endswith('.csv'):
                            outlet_df = pd.read_csv(manual_outlet_file)
                        else:
                            outlet_df = pd.read_excel(manual_outlet_file)
                            
                        from src.inventory.core import identify_columns
                        _, _, t_col, s_col = identify_columns(outlet_df)
                        
                        q_col = next((c for c in outlet_df.columns if "qty" in str(c).lower() or "quantity" in str(c).lower() or "stock" in str(c).lower()), None)
                        if not q_col:
                            q_col = outlet_df.columns[-1]
                            
                        outlet_df["Stock"] = pd.to_numeric(outlet_df[q_col], errors='coerce').fillna(0)
                        
                        if sku_col != "None" and s_col:
                            outlet_map = outlet_df.groupby(s_col)["Stock"].sum().to_dict()
                            merged_df["Outlet Stock"] = merged_df[sku_col].astype(str).map(outlet_map).fillna(0)
                        elif t_col:
                            outlet_map = outlet_df.groupby(t_col)["Stock"].sum().to_dict()
                            merged_df["Outlet Stock"] = merged_df[item_col].map(outlet_map).fillna(0)
                    # --- Global Inventory (From Distribution Tab) ---
                    global_inv_map = st.session_state.get("inv_inventory_map")
                    global_locs = st.session_state.get("inv_active_l", [])
                    added_global_locs = []
                    
                    if global_inv_map and global_locs:
                        from src.inventory.core import build_title_size_key, item_name_to_title_size, normalize_sku
                        
                        for loc in global_locs:
                            col_name = f"Inv: {loc}"
                            merged_df[col_name] = 0
                            added_global_locs.append(col_name)
                            
                        sku_inv_map = st.session_state.get("inv_sku_map", {})
                        
                        for idx, row in merged_df.iterrows():
                            pl_sku = normalize_sku(str(row[sku_col])) if sku_col != "None" else ""
                            title, size = item_name_to_title_size(str(row[item_col]))
                            pl_key = build_title_size_key(title, size)
                            
                            inv_key = None
                            sku_size_key = f"SKU:{pl_sku}_SZ:{size}" if (pl_sku and pl_sku != "0") else ""
                            
                            if sku_size_key and sku_size_key in global_inv_map:
                                inv_key = sku_size_key
                            elif pl_key and pl_key in global_inv_map:
                                inv_key = pl_key
                            elif pl_sku and pl_sku != "0":
                                if pl_sku in sku_inv_map and sku_inv_map[pl_sku] in global_inv_map:
                                    inv_key = sku_inv_map[pl_sku]
                                elif pl_sku in global_inv_map:
                                    inv_key = pl_sku
                            
                            if inv_key and inv_key in global_inv_map:
                                for loc in global_locs:
                                    merged_df.at[idx, f"Inv: {loc}"] = global_inv_map[inv_key].get(loc, 0)

                    # --- Bottom Row / Totals ---
                    current_date = datetime.now().strftime("%d %b %Y")
                    remarks = f"(Date: {current_date}"
                    
                    if order_col != "None":
                        unique_orders = df[order_col].nunique()
                        try:
                            numeric_orders = pd.to_numeric(df[order_col].astype(str).str.extract(r'(\d+)', expand=False), errors='coerce')
                            if numeric_orders.notna().any():
                                max_idx = numeric_orders.idxmax()
                                latest_order = str(df.loc[max_idx, order_col])
                            else:
                                latest_order = str(df[order_col].dropna().max())
                        except Exception:
                            latest_order = str(df[order_col].dropna().max())
                        
                        remarks += f" | Total Orders: {unique_orders} | Latest Order: {latest_order}"
                        
                    remarks += ")"
                    
                    bottom_row = {item_col: remarks, qty_col: merged_df[qty_col].sum()}
                    if sku_col != "None": bottom_row[sku_col] = ""
                    if "Web Stock" in merged_df.columns: bottom_row["Web Stock"] = ""
                    if "Outlet Stock" in merged_df.columns: bottom_row["Outlet Stock"] = ""
                    for loc_col in added_global_locs:
                        if loc_col in merged_df.columns: bottom_row[loc_col] = ""
                    
                    merged_df = pd.concat([merged_df, pd.DataFrame([bottom_row])], ignore_index=True)
                    num_bottom_rows = 1
                    
                    try:
                        # Apply distinct light colors to different SKUs/Items
                        def apply_sku_colors(data_df):
                            styles = pd.DataFrame('border: 1px solid #000000;', index=data_df.index, columns=data_df.columns)
                            if len(data_df) <= num_bottom_rows: return styles
                            
                            import colorsys
                            color_col = sku_col if sku_col != "None" else item_col
                            unique_vals = data_df[color_col].iloc[:-num_bottom_rows].unique()
                            
                            color_dict = {}
                            for i, val in enumerate(unique_vals):
                                hue = (i * 0.618033988749895) % 1.0
                                rgb = colorsys.hls_to_rgb(hue, 0.92, 0.5)
                                hex_color = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
                                color_dict[val] = hex_color
                                
                            for idx, row in data_df.iloc[:-num_bottom_rows].iterrows():
                                val = row[color_col]
                                hex_color = color_dict.get(val, '#ffffff')
                                styles.loc[idx, :] = f'background-color: {hex_color}; color: #000000; border: 1px solid #000000;'
                                
                                req_qty = pd.to_numeric(row.get(qty_col, 0), errors='coerce')
                                tot_stock = 0
                                has_stock_data = False
                                if "Web Stock" in row: 
                                    tot_stock += pd.to_numeric(row["Web Stock"], errors='coerce')
                                    has_stock_data = True
                                if "Outlet Stock" in row: 
                                    tot_stock += pd.to_numeric(row["Outlet Stock"], errors='coerce')
                                    has_stock_data = True
                                for loc_col in added_global_locs:
                                    if loc_col in row:
                                        tot_stock += pd.to_numeric(row[loc_col], errors='coerce')
                                        has_stock_data = True
                                        
                                if has_stock_data and req_qty > tot_stock:
                                    styles.loc[idx, qty_col] = f'background-color: {hex_color}; color: #ef4444; font-weight: bold; border: 1px solid #000000;'
                                    
                            return styles
                            
                        styled_df = merged_df.style.apply(apply_sku_colors, axis=None)
                    except Exception as style_err:
                        styled_df = merged_df.style.set_properties(**{'border': '1px solid #000000'})
                        st.warning(f"Row coloring omitted: {str(style_err)}")
                    
                    def highlight_bottom_rows(row):
                        if row.name >= len(merged_df) - num_bottom_rows:
                            return ['font-weight: bold; background-color: #e2e8f0; color: #0f172a; border: 1px solid #000000;'] * len(row)
                        return [''] * len(row)
                        
                    styled_df = styled_df.apply(highlight_bottom_rows, axis=1)
                    
                    st.markdown("### Merged Data")
                    calc_height = min(800, max(400, len(merged_df) * 35 + 43))
                    st.dataframe(styled_df, use_container_width=True, height=calc_height)
                    
                    # Export using centralized utility with alternating colors based on SKU or Item
                    group_col_for_export = sku_col if sku_col != "None" else item_col
                    excel_bytes = export_to_styled_excel({"Product Listing": merged_df}, group_by_col=group_col_for_export)
                    
                    st.download_button(
                        label="📥 Download Merged Excel",
                        data=excel_bytes,
                        file_name=f"product_listing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        except Exception as e:
            st.error(f"Error processing data: {str(e)}")
