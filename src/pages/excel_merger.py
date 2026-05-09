import streamlit as st
import pandas as pd
import io

def render_excel_merger_tab():
    st.header("📑 Excel Quantity Merger")
    st.markdown("Upload an Excel file to merge unique products and sum their quantities.")
    
    uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])
    
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success("File uploaded successfully!")
            
            st.markdown("### Preview Original Data")
            st.dataframe(df.head())
            
            columns = df.columns.tolist()
            
            col1, col2 = st.columns(2)
            with col1:
                # Try to guess item name column
                item_name_idx = 0
                for i, col in enumerate(columns):
                    if "name" in str(col).lower() or "item" in str(col).lower() or "product" in str(col).lower():
                        item_name_idx = i
                        break
                item_col = st.selectbox("Select Item Name Column", columns, index=item_name_idx)
                
            with col2:
                # Try to guess quantity column
                qty_idx = 0
                for i, col in enumerate(columns):
                    if "qty" in str(col).lower() or "quantity" in str(col).lower() or "amount" in str(col).lower():
                        qty_idx = i
                        break
                qty_col = st.selectbox("Select Quantity Column", columns, index=qty_idx)
                
            if st.button("Merge & Sum Quantities", type="primary"):
                # Ensure the quantity column is numeric
                df[qty_col] = pd.to_numeric(df[qty_col], errors='coerce').fillna(0)
                
                # Group by Item Name and sum Quantity
                merged_df = df.groupby(item_col, as_index=False)[qty_col].sum()
                
                st.markdown("### Merged Data")
                st.dataframe(merged_df)
                
                # Download button
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    merged_df.to_excel(writer, index=False, sheet_name='Merged Quantities')
                
                st.download_button(
                    label="📥 Download Merged Excel",
                    data=output.getvalue(),
                    file_name="merged_quantities.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
