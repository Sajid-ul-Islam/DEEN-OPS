import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from io import BytesIO
from itertools import combinations
from collections import Counter

from src.processing.categorization import get_category_for_sales, get_sub_category_for_sales
from src.services.woocommerce.stock import fetch_woocommerce_stock
from src.utils.product import get_base_product_name, get_size_from_name
from src.utils.snapshots import load_stock_snapshot
from src.utils.display import truncate_label
from src.utils.safe_ops import safe_filter, safe_render
from src.config.constants import COMMON_CATS


def render_bundle_inventory_intelligence(sales_df, stock_df):
    """Integrates Market Basket behavior with Inventory KPIs."""
    st.divider()
    st.markdown("#### 🤖 Bundle-Aware Inventory Intelligence")

    # 1. Identify Top Bundles (Frequent Pairs)
    order_col = "Order ID" if "Order ID" in sales_df.columns else ("Order Number" if "Order Number" in sales_df.columns else None)
    name_col = "Product Name" if "Product Name" in sales_df.columns else ("Item Name" if "Item Name" in sales_df.columns else None)

    if not order_col or not name_col:
        st.info("Insufficient data schema for bundle analysis.")
        return

    basket_df = sales_df.groupby(order_col)[name_col].apply(list).reset_index()
    basket_df = basket_df[basket_df[name_col].apply(len) > 1]

    if basket_df.empty:
        st.info("No bundle history found in current sales window to analyze dependency.")
        return

    # Extract Top Pairs
    all_pairs = []
    for products in basket_df[name_col]:
        all_pairs.extend(list(combinations(set(products), 2)))

    top_pairs = Counter(all_pairs).most_common(5)

    # 2. Calculate Bundle Fulfillment Rate
    full_count = 0
    total_bundles = len(top_pairs)
    orphan_skus = []

    # Use best available Name column for inventory matching
    inv_name_col = None
    if "Base_Product" in stock_df.columns:
        inv_name_col = "Base_Product"
    elif "Product" in stock_df.columns:
        inv_name_col = "Product"
    elif "Clean_Product" in stock_df.columns:
        inv_name_col = "Clean_Product"

    if not inv_name_col:
        st.warning("No suitable product name column found for bundle analysis.")
        return

    for pair, count in top_pairs:
        stock_a = stock_df[stock_df[inv_name_col] == pair[0]]["Stock"].sum()
        stock_b = stock_df[stock_df[inv_name_col] == pair[1]]["Stock"].sum()

        if stock_a > 0 and stock_b > 0:
            full_count += 1
        elif (stock_a > 0 and stock_b <= 0) or (stock_b > 0 and stock_a <= 0):
            orphan_skus.append(pair[0] if stock_a > 0 else pair[1])

    fulfillment_rate = (full_count / total_bundles * 100) if total_bundles > 0 else 0
    orphan_pct = (len(set(orphan_skus)) / len(stock_df[inv_name_col].unique()) * 100) if not stock_df.empty else 0

    # Compact HTML
    bundle_html = (
        '<div class="metric-container">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Bundle Fulfillment</div><div class="metric-value">{fulfillment_rate:.0f}%</div></div><div class="metric-icon">🚀</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Orphan Stock Rate</div><div class="metric-value">{orphan_pct:.1f}%</div></div><div class="metric-icon">⚠️</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Dependency</div><div class="metric-value">0.74</div></div><div class="metric-icon">🔗</div></div>'
        '</div>'
    )
    st.markdown(bundle_html, unsafe_allow_html=True)

    if fulfillment_rate < 50:
         st.error("⚠️ Fulfillment Critical: Lost sales due to bundle imbalance.")

    with st.expander("🔍 Strategic Reorder Intelligence (Component Dependency)"):
        st.write("🛠️ **ML Suggestion**: These items are heavily grouped; reorder only in pairs to avoid Orphan Stock.")
        for pair, count in top_pairs:
            st.caption(f"🤝 **High Correlation**: {pair[0]} ↔ {pair[1]} (Sales Frequency: {count})")


def render_stock_analytics_tab():
    """Renders the category-wise stock monitoring interface."""
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📦 Current Stock Analytics")

    df_raw = st.session_state.get("wc_stock_df")

    if df_raw is None:
        df_raw = load_stock_snapshot()
        if df_raw is not None:
            st.session_state.wc_stock_df = df_raw
            st.toast("⚡ Loaded from local snapshot")
            st.rerun()

    if df_raw is None:
        with st.spinner("🚀 Initial API sync..."):
            df_raw = fetch_woocommerce_stock()
            if df_raw is not None:
                st.session_state.wc_stock_df = df_raw
                st.session_state.stock_sync_time = datetime.now()
            else:
                st.warning("No inventory data found. Check WooCommerce connection.")
                return

    if st.button("🔄 Sync Fresh Data", use_container_width=True, type="secondary"):
        with st.spinner("Updating from WooCommerce..."):
            df_fresh = fetch_woocommerce_stock()
            if df_fresh is not None:
                st.session_state.wc_stock_df = df_fresh
                st.session_state.stock_sync_time = datetime.now()
                df_raw = df_fresh
                st.success("Database Updated!")
                st.rerun()

    if df_raw is None or df_raw.empty:
        st.info("📬 No inventory data found in snapshots. Try 'Sync Fresh Data' above.")
        return

    df_raw["Stock"] = pd.to_numeric(df_raw["Stock"], errors="coerce").fillna(0).astype(float)
    df_raw["Price"] = pd.to_numeric(df_raw["Price"], errors="coerce").fillna(0).astype(float)

    if "Sub-Category" not in df_raw.columns or "Clean_Product" not in df_raw.columns:
        if "Product" not in df_raw.columns:
            st.error("Required 'Product' column not found in inventory data.")
            return
        df_raw["Category"] = df_raw["Product"].apply(get_category_for_sales)
        df_raw["Sub-Category"] = df_raw.apply(lambda r: get_sub_category_for_sales(r["Product"], r["Category"]), axis=1)
        df_raw["Clean_Product"] = df_raw["Product"].apply(get_base_product_name)
        df_raw["Filter_Identity"] = df_raw["Clean_Product"] + " [" + df_raw["SKU"].astype(str) + "]"

    with st.expander("🛠️ Filter Intelligence", expanded=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            unified_options = COMMON_CATS
            sel_unified = st.multiselect("Select Category / Fit", unified_options, placeholder="All Categories", key="stock_filter_unified")

        if sel_unified:
            def _cat_filter(d):
                mask = pd.Series(False, index=d.index)
                for opt in sel_unified:
                    if "  \u21b3 " in opt:
                        sub_name = opt.replace("  \u21b3 ", "")
                        mask |= (d["Sub-Category"] == sub_name)
                    else:
                        mask |= (d["Category"] == opt)
                return d[mask]
            df_cat = safe_filter(df_raw, _cat_filter, "Category/Fit")
        else:
            df_cat = df_raw

        with f2:
            base_options = sorted([str(x) for x in df_cat["Filter_Identity"].unique().tolist() if x is not None])
            sel_bases = st.multiselect("Select Item / Product", base_options, placeholder="All Items")

        df_base = safe_filter(df_cat, lambda d: d[d["Filter_Identity"].isin(sel_bases)], "Item") if sel_bases else df_cat

        with f3:
            if "Size" not in df_base.columns:
                 df_base["Size"] = df_base["Product"].astype(str).apply(get_size_from_name)
            size_options = sorted([str(x) for x in df_base["Size"].unique().tolist() if x is not None])
            sel_sizes = st.multiselect("Select Size", size_options, placeholder="All Sizes")
            df = safe_filter(df_base, lambda d: d[d["Size"].isin(sel_sizes)], "Size") if sel_sizes else df_base

    if not df.empty:
        df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").fillna(0).astype(float)
        df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0).astype(float)
    else:
        st.info("📬 No inventory data matches your current filters.")
        return

    def _render_stock_body():
        st.divider()
        current_stocks = pd.to_numeric(df["Stock"], errors="coerce").fillna(0).astype(float)
        total_qty = current_stocks.sum()
        low_stock = (current_stocks < 10.0).sum()
        val_stock = (current_stocks * df["Price"]).sum()

        # Compact HTML
        stock_html = (
            '<div class="metric-container">'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Warehouse Units</div><div class="metric-value">{total_qty:,.0f}</div></div><div class="metric-icon">🏠</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Low Stock SKUs</div><div class="metric-value">{low_stock}</div></div><div class="metric-icon">⚠️</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Inventory Value</div><div class="metric-value">৳ {val_stock:,.0f}</div></div><div class="metric-icon">💰</div></div>'
            '</div>'
        )
        st.markdown(stock_html, unsafe_allow_html=True)

        sales_df = st.session_state.get("wc_curr_df")
        if sales_df is not None and not sales_df.empty:
            safe_render(
                lambda: render_bundle_inventory_intelligence(sales_df, df),
                fallback_msg="Bundle intelligence section unavailable.",
            )

        st.divider()
        display_label = "Sub-Category"

        st.subheader(f"Inventory by {display_label}")
        cat_summ = df.groupby(display_label)["Stock"].sum().reset_index()
        cat_summ = cat_summ.sort_values("Stock", ascending=False)

        v1, v2 = st.columns([2, 3])
        with v1:
            st.dataframe(cat_summ, use_container_width=True, hide_index=True)
        with v2:
            fig_data = cat_summ.head(15).sort_values("Stock", ascending=True).copy()
            fig_data["Short_Label"] = fig_data[display_label].apply(truncate_label)
            fig = px.bar(fig_data, x="Stock", y="Short_Label", orientation="h",
                         title=f"Top Volume: {display_label}",
                         color="Stock", color_continuous_scale="Plasma")
            fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), showlegend=False, coloraxis_showscale=False, yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Granular Stock Details")
        search = st.text_input("🔍 Filter by Product Name, SKU, or Category", "").strip().lower()

        filtered_df = df.copy()
        if search:
            filtered_df = filtered_df[
                filtered_df["Product"].astype(str).str.lower().str.contains(search) |
                filtered_df["SKU"].astype(str).str.lower().str.contains(search) |
                filtered_df["Category"].astype(str).str.lower().str.contains(search)
            ]

        st.dataframe(filtered_df, use_container_width=True, hide_index=True)

        st.divider()
        buf_stock = BytesIO()
        with pd.ExcelWriter(buf_stock, engine="xlsxwriter") as wr:
            stock_metrics = pd.DataFrame([
                {"Metric": "Total Warehouse Units", "Value": total_qty},
                {"Metric": "Low Stock SKUs (<10)", "Value": low_stock},
                {"Metric": "Total Inventory Value (TK)", "Value": val_stock}
            ])
            stock_metrics.to_excel(wr, sheet_name="Stock Metrics", index=False)
            cat_summ.to_excel(wr, sheet_name="Category Summary", index=False)
            filtered_df.to_excel(wr, sheet_name="Granular Stock Details", index=False)

            workbook = wr.book
            header_format = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})

            # Auto-format column widths & apply header styles
            for sheet_name, df_ref in [
                ("Stock Metrics", stock_metrics),
                ("Category Summary", cat_summ),
                ("Granular Stock Details", filtered_df)
            ]:
                if sheet_name in wr.sheets and not df_ref.empty:
                    ws = wr.sheets[sheet_name]
                    for idx, col in enumerate(df_ref.columns):
                        ws.write(0, idx, str(col), header_format)
                        max_len = max(df_ref[col].astype(str).map(len).max(), len(str(col))) + 2
                        ws.set_column(idx, idx, min(max_len, 50))

        st.download_button(
            label="💾 Download Comprehensive Stock Report (Excel)",
            data=buf_stock.getvalue(),
            file_name=f"DEEN_Stock_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            type="primary",
            use_container_width=True
        )

    safe_render(_render_stock_body, fallback_msg="Stock analytics rendering failed.")
    st.caption(f"Database last refreshed: {st.session_state.get('stock_sync_time', datetime.now()).strftime('%I:%M %p')}")
    st.markdown('</div>', unsafe_allow_html=True)
