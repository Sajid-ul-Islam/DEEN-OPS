import streamlit as st
import pandas as pd
import io
from datetime import datetime

def render_excel_merger_tab():
    st.header("📑 Product Listing")
    st.markdown("Upload an Excel file to generate a consolidated product listing by merging unique items and summing their quantities.")
    
    uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])
    
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success("File uploaded successfully!")
            
            st.markdown("### Preview Original Data")
            st.dataframe(df.head())
            
            columns = df.columns.tolist()
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                # Try to guess item name column
                item_name_idx = 0
                for i, col in enumerate(columns):
                    if "name" in str(col).lower() or "item" in str(col).lower() or "product" in str(col).lower():
                        item_name_idx = i
                        break
                item_col = st.selectbox("Select Item Name Column", columns, index=item_name_idx)
                
            with col2:
                # Try to guess SKU column
                sku_idx = 0
                sku_options = ["None"] + columns
                for i, col in enumerate(columns):
                    if "sku" in str(col).lower() or "code" in str(col).lower():
                        sku_idx = i + 1
                        break
                sku_col = st.selectbox("Select SKU Column (Optional)", sku_options, index=sku_idx)
                
            with col3:
                # Try to guess quantity column
                qty_idx = 0
                for i, col in enumerate(columns):
                    if "qty" in str(col).lower() or "quantity" in str(col).lower() or "amount" in str(col).lower():
                        qty_idx = i
                        break
                qty_col = st.selectbox("Select Quantity Column", columns, index=qty_idx)
                
            with col4:
                # Try to guess order number column
                order_idx = 0
                order_options = ["None"] + columns
                for i, col in enumerate(columns):
                    if "order" in str(col).lower() or "id" in str(col).lower():
                        order_idx = i + 1
                        break
                order_col = st.selectbox("Select Order Column (Optional)", order_options, index=order_idx)
                
            if st.button("Execute Merge", type="primary"):
                # Ensure the quantity column is numeric
                df[qty_col] = pd.to_numeric(df[qty_col], errors='coerce').fillna(0)
                
                # Group by Item Name (and SKU if selected) and sum Quantity
                if sku_col != "None":
                    merged_df = df.groupby([item_col, sku_col], as_index=False)[qty_col].sum()
                else:
                    merged_df = df.groupby(item_col, as_index=False)[qty_col].sum()
                
                # Sort by quantity descending for better visibility
                merged_df = merged_df.sort_values(by=qty_col, ascending=False).reset_index(drop=True)
                
                current_date = datetime.now().strftime("%d %b %Y")
                remarks = f"(Date: {current_date}"
                
                if order_col != "None":
                    unique_orders = df[order_col].nunique()
                    
                    try:
                        # Safely find the max order number by finding the max numeric value inside the string
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
                if sku_col != "None":
                    bottom_row[sku_col] = ""
                
                merged_df = pd.concat([merged_df, pd.DataFrame([bottom_row])], ignore_index=True)
                num_bottom_rows = 1
                
                try:
                    # Apply distinct light colors to different SKUs/Items
                    def apply_sku_colors(data_df):
                        # Initialize all cells with a border
                        styles = pd.DataFrame('border: 1px solid #000000;', index=data_df.index, columns=data_df.columns)
                        
                        if len(data_df) <= num_bottom_rows:
                            return styles
                            
                        import colorsys
                        
                        color_col = sku_col if sku_col != "None" else item_col
                        unique_vals = data_df[color_col].iloc[:-num_bottom_rows].unique()
                        
                        color_dict = {}
                        for i, val in enumerate(unique_vals):
                            # Golden ratio to spread hues evenly
                            hue = (i * 0.618033988749895) % 1.0
                            # High lightness (0.92) and moderate saturation (0.5) for very light pastel colors
                            rgb = colorsys.hls_to_rgb(hue, 0.92, 0.5)
                            hex_color = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
                            color_dict[val] = hex_color
                            
                        for idx, row in data_df.iloc[:-num_bottom_rows].iterrows():
                            val = row[color_col]
                            hex_color = color_dict.get(val, '#ffffff')
                            styles.loc[idx, :] = f'background-color: {hex_color}; color: #000000; border: 1px solid #000000;'
                            
                        return styles
                        
                    styled_df = merged_df.style.apply(apply_sku_colors, axis=None)
                except Exception as style_err:
                    styled_df = merged_df.style.set_properties(**{'border': '1px solid #000000'})
                    st.warning(f"Row coloring omitted: {str(style_err)}")
                
                # Highlight the bottom rows
                def highlight_bottom_rows(row):
                    if row.name >= len(merged_df) - num_bottom_rows:
                        return ['font-weight: bold; background-color: #e2e8f0; color: #0f172a; border: 1px solid #000000;'] * len(row)
                    return [''] * len(row)
                    
                styled_df = styled_df.apply(highlight_bottom_rows, axis=1)
                
                st.markdown("### Merged Data")
                st.dataframe(styled_df, use_container_width=True)
                
                # Download button
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    styled_df.to_excel(writer, index=False, sheet_name='Product Listing')
                    
                    workbook = writer.book
                    worksheet = writer.sheets['Product Listing']
                    header_format = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
                    
                    for idx, col in enumerate(merged_df.columns):
                        worksheet.write(0, idx, str(col), header_format)
                        max_len = max(merged_df[col].astype(str).map(len).max(), len(str(col))) + 2
                        worksheet.set_column(idx, idx, min(max_len, 50))
                
                st.download_button(
                    label="📥 Download Merged Excel",
                    data=output.getvalue(),
                    file_name=f"product_listing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
