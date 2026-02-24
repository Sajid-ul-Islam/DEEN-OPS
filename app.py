import streamlit as st
import pandas as pd
from processor import WhatsAppOrderProcessor  # Updated import

# Configuration
st.set_page_config(
    page_title="WhatsApp Order Verification",
    page_icon="✅",
    layout="wide"
)

# Custom Styles for WhatsApp Vibe
st.markdown("""
<style>
    /* WhatsApp Background */
    .stApp {
        background-color: #ECE5DD;
        background-image: url("https://user-images.githubusercontent.com/15075759/28719144-86dc0f70-73b1-11e7-911d-60d70fcded21.png");
        background-size: 300px;
        background-repeat: repeat; 
        background-blend-mode: overlay;
    }
    
    /* Header Style */
    .main-header {
        background-color: #075E54;
        padding: 1.5rem;
        color: white;
        border-radius: 0px 0px 10px 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        text-align: center;
        margin-bottom: 2rem;
    }
    
    /* Chat Bubble Container */
    .chat-bubble {
        background-color: white;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 1px 1px rgba(0,0,0,0.1);
        margin-bottom: 20px;
        border-left: 5px solid #25D366;
    }
    
    /* Button Styling */
    .stButton>button {
        background-color: #25D366;
        color: white;
        border: none;
        border-radius: 20px;
        padding: 10px 24px;
        font-weight: bold;
        box-shadow: 0 2px 2px rgba(0,0,0,0.1);
        transition: all 0.2s;
    }
    .stButton>button:hover {
        background-color: #128C7E;
        box-shadow: 0 4px 4px rgba(0,0,0,0.15);
        color: white;
    }

    /* Input/Select Styling */
    .stSelectbox > div > div {
        background-color: white !important;
        border-radius: 8px;
    }
    
    /* Headings */
    h1, h2, h3, h5 {
        color: #075E54 !important;
    }
</style>
""", unsafe_allow_html=True)

def main():
    st.markdown('<div class="main-header"><h1>WhatsApp Order Verification Tool 💬</h1></div>', unsafe_allow_html=True)
    
    # Instructions in a "Chat Bubble"
    st.markdown("""
    <div class="chat-bubble">
        <h5>👋 Welcome! Follow these steps:</h5>
        <ol>
            <li><b>Upload</b> your order Excel file 📂</li>
            <li><b>Verify Columns</b> (we've auto-detected them for you) 🔍</li>
            <li><b>Process</b> to generate verification links 🚀</li>
            <li><b>Download</b> the result and start messaging! 📥</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Upload Excel File", type=['xlsx', 'xls'])
    
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            df.columns = [str(col).strip() for col in df.columns]
            
            # Data Preview
            with st.expander("👀 View Uploaded Data"):
                st.dataframe(df.head(3), use_container_width=True)
            
            st.markdown("### ⚙️ Column Mapping")
            
            # Expanded Intelligent Defaults
            mapping = {
                'required': {
                    'phone_col': [
                        'phone (billing)', 'billing phone', 'phone', 'mobile', 'contact', 'cell', 'whatsapp', 
                        'tel', 'mobile no', 'phone number'
                    ],
                    'name_col': [
                        'first name (shipping)', 'shipping name', 'full name (billing)', 'billing name', 
                        'customer name', 'receiver', 'full name', 'name', 'customer', 'client'
                    ],
                    'order_id_col': [
                        'order id', 'order no', 'invoice', 'invoice no', 'id', 'order number', '#'
                    ],
                    'product_col': [
                        'product name (main)', 'product name', 'product', 'item', 'item name', 'goods', 
                        'description', 'particulars'
                    ],
                    'quantity_col': [
                        'quantity', 'qty', 'count', 'units', 'pieces', 'amount'
                    ],
                    'price_col': [
                        'item cost', 'unit price', 'rate', 'price', 'cost', 'amount', 'value', 
                        'order line subtotal'
                    ],
                    'order_total_col': [
                        'order total amount', 'grand total', 'total amount', 'total', 'net total', 
                        'payable', 'bill amount'
                    ],
                },
                'optional': {
                    'address_col': [
                        'address 1&2 (billing)', 'billing address', 'address', 'shipping address', 
                        'street', 'location', 'delivery address'
                    ],
                    'sku_col': [
                        'sku', 'product code', 'item code', 'code', 'stock keeping unit'
                    ],
                    'payment_method_col': [
                        'payment method title', 'payment method', 'payment', 'gateway', 'method', 
                        'transaction type'
                    ],
                    'city_col': [
                        'city, state, zip (billing)', 'city', 'district', 'town', 'area', 'region', 
                        'state'
                    ]
                }
            }

            config = {}
            
            # Improved detection logic
            def find_best_match(options, keywords):
                options_lower = [str(o).lower() for o in options]
                
                # 1. Exact match
                for k in keywords:
                    if k in options_lower:
                        return options_lower.index(k)
                
                # 2. Starts with (e.g. "Phone Number" matches "phone")
                for k in keywords:
                    for i, opt in enumerate(options_lower):
                        if opt.startswith(k):
                            return i
                            
                # 3. Contains (e.g. "Billing Phone" matches "phone")
                for k in keywords:
                    for i, opt in enumerate(options_lower):
                        if k in opt:
                            return i
                
                return 0

            # 2-Column Layout for Mapping
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("##### 📌 Required Fields")
                for key, keywords in mapping['required'].items():
                    idx = find_best_match(df.columns, keywords)
                    config[key] = st.selectbox(
                        f"{key.replace('_col', '').replace('_', ' ').title()}",
                        options=df.columns,
                        index=idx,
                        key=key,
                        help=f"Select the column for {key.replace('_col', '')}"
                    )
            
            with col2:
                st.markdown("##### 🔧 Optional Fields")
                opts = ["None"] + list(df.columns)
                for key, keywords in mapping['optional'].items():
                    # Adjust index for "None" being at 0
                    match_idx = find_best_match(df.columns, keywords)
                    # If match found in df.columns (which is 0+), in our opts list it is match_idx + 1
                    # However, find_best_match returns 0 if no match. 
                    # We need to check if it actually matched or just defaulted.
                    
                    # Let's perform a check to see if the default 0 was a real match or fallback
                    # Check if finding 'None' is better? No.
                    
                    # Re-run logic for finding index in the options list which includes None
                    # We need to match against df.columns, then map that index to opts
                    
                    # Simplification: Just use the smart finder on df.columns
                    # If the smart finder returns a valid match, we select it (+1 because of None)
                    # If it defaults to 0, we verify if 0 is a good match. If not, we might want to default to None.
                    
                    # For optional, we default to "None" if no strong match found? 
                    # The previous logic just picked index 0. Let's stick to picking a calculated index.
                    
                    # Let's verify if the 0-th column is actually a match for optional
                    best_idx = find_best_match(df.columns, keywords)
                    
                    # Check if the column at best_idx actually contains one of the keywords
                    col_name = df.columns[best_idx].lower()
                    is_match = any(k in col_name for k in keywords)
                    
                    if is_match:
                        default_idx = best_idx + 1
                    else:
                        default_idx = 0 # "None"
                        
                    val = st.selectbox(
                        f"{key.replace('_col', '').replace('_', ' ').title()}",
                        options=opts,
                        index=default_idx,
                        key=key
                    )
                    if val != "None":
                        config[key] = val

            st.write("") # Spacer
            
            if st.button("🚀 Process Orders", use_container_width=True):
                with st.spinner("Generating WhatsApp links..."):
                    processor = WhatsAppOrderProcessor(config=config)
                    # Process
                    processed_df = processor.process_orders(df)
                    final_df = processor.create_whatsapp_links(processed_df)
                    excel_data = processor.generate_excel_bytes(final_df)
                    
                    st.success(f"✅ Successfully processed {len(final_df)} orders!")
                    
                    st.markdown("### 📊 Processed Data Preview")
                    
                    # Reorder columns for better preview (WhatsApp link first)
                    cols = final_df.columns.tolist()
                    if 'whatsapp_link' in cols:
                        cols.insert(0, cols.pop(cols.index('whatsapp_link')))
                    
                    # Display the final dataframe with link configuration
                    st.dataframe(
                        final_df[cols],
                        column_config={
                            "whatsapp_link": st.column_config.LinkColumn(
                                "Quick Action",
                                help="Click to open WhatsApp chat",
                                validate="^https://wa\.me/.*",
                                display_text="Send Message 💬"
                            ),
                            "whatsapp_link_raw": None, # Hide raw link if it exists
                        },
                        use_container_width=True,
                        hide_index=True
                    )

                    # Message Preview
                    if not final_df.empty and 'whatsapp_link' in final_df.columns:
                        import urllib.parse
                        first_link = final_df.iloc[0]['whatsapp_link']
                        if 'text=' in first_link:
                            msg_encoded = first_link.split('text=')[1]
                            msg_decoded = urllib.parse.unquote(msg_encoded)
                            with st.expander("💬 View Sample Message Content"):
                                st.code(msg_decoded, language=None)
                    
                    st.write("") # Spacer
                    st.download_button(
                        label="📥 Download WhatsApp Verification File",
                        data=excel_data,
                        file_name="whatsapp_orders.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                    
        except Exception as e:
            st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
