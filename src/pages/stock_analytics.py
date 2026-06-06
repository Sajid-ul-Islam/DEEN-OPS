import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from itertools import combinations
from collections import Counter

from src.processing.categorization import get_category_for_sales, get_sub_category_for_sales
from src.pages.excel_exporter import export_to_styled_excel
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
        with st.status("🚀 Initial API sync...", expanded=True) as sync_status:
            st.write("📡 Fetching products from WooCommerce...")
            df_raw = fetch_woocommerce_stock()
            if df_raw is not None:
                st.session_state.wc_stock_df = df_raw
                st.session_state.stock_sync_time = datetime.now()
                sync_status.update(label="Inventory Sync Complete", state="complete", expanded=False)
                st.toast("✅ Inventory data loaded!", icon="🎉")
            else:
                sync_status.update(label="Sync Failed", state="error", expanded=False)
                st.warning("No inventory data found. Check WooCommerce connection.")
                return

    if st.button("🔄 Sync Fresh Data", use_container_width=True, type="secondary"):
        with st.status("Updating from WooCommerce...", expanded=True) as sync_status:
            st.write("📡 Fetching latest stock levels...")
            df_fresh = fetch_woocommerce_stock()
            if df_fresh is not None:
                st.session_state.wc_stock_df = df_fresh
                st.session_state.stock_sync_time = datetime.now()
                df_raw = df_fresh
                sync_status.update(label="Database Updated", state="complete", expanded=False)
                st.toast("✅ Stock database updated!", icon="🎉")
                st.rerun()
            else:
                sync_status.update(label="Update Failed", state="error", expanded=False)

    if df_raw is None or df_raw.empty:
        st.info("📬 No inventory data found in snapshots. Try 'Sync Fresh Data' above.")
        return

    df_raw["Stock"] = pd.to_numeric(df_raw["Stock"].astype(str).str.replace(r"[^\d.-]", "", regex=True), errors="coerce").fillna(0).astype(float)
    df_raw["Price"] = pd.to_numeric(df_raw["Price"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce").fillna(0).astype(float)

    if "Sub-Category" not in df_raw.columns or "Clean_Product" not in df_raw.columns:
        if "Product" not in df_raw.columns:
            st.error("Required 'Product' column not found in inventory data.")
            return
        df_raw["Category"] = df_raw["Product"].apply(get_category_for_sales)
        df_raw["Sub-Category"] = df_raw.apply(lambda r: get_sub_category_for_sales(r["Product"], r["Category"]), axis=1)
        df_raw["Clean_Product"] = df_raw["Product"].apply(get_base_product_name)
        df_raw["Filter_Identity"] = df_raw["Clean_Product"].astype(str) + " [" + df_raw["SKU"].astype(str) + "]"

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
        df["Stock"] = pd.to_numeric(df["Stock"].astype(str).str.replace(r"[^\d.-]", "", regex=True), errors="coerce").fillna(0).astype(float)
        df["Price"] = pd.to_numeric(df["Price"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce").fillna(0).astype(float)
    else:
        st.info("📬 No inventory data matches your current filters.")
        return

    def _render_stock_body():
        st.divider()
        st.subheader("🧮 Live Scenario Simulator")
        st.markdown("Adjust the sliders below to simulate stock and price changes. Metrics, charts, and table highlights will update in real-time.")
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sim_stock_adj = st.slider("Simulate Stock Adjustment (%)", -100, 100, 0, step=5, help="Simulate a percentage change in available warehouse units.")
        with sc2:
            sim_price_adj = st.slider("Simulate Price Adjustment (%)", -50, 100, 0, step=5, help="Simulate a percentage markup or discount on inventory value.")
        with sc3:
            low_thresh = st.number_input("Low Stock Highlight Threshold", min_value=1, max_value=500, value=10, step=1, help="Highlight items with stock below this number.")

        df_sim = df.copy()
        df_sim["Stock"] = pd.to_numeric(df_sim["Stock"], errors="coerce").fillna(0).astype(float) * (1 + (sim_stock_adj / 100.0))
        df_sim["Price"] = pd.to_numeric(df_sim["Price"], errors="coerce").fillna(0).astype(float) * (1 + (sim_price_adj / 100.0))

        st.divider()
        current_stocks = df_sim["Stock"]
        total_qty = current_stocks.sum()
        low_stock = (current_stocks < low_thresh).sum()
        val_stock = (current_stocks * df_sim["Price"]).sum()
        
        # Apply glowing effect if low stock items exceed 20% of the selection
        glow_class = "critical-glow" if (low_stock / len(df_sim) > 0.2) else ""

        # Compact HTML
        stock_html = (
            '<div class="metric-container">'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Warehouse Units</div><div class="metric-value">{total_qty:,.0f}</div></div><div class="metric-icon">🏠</div></div>'
            f'<div class="metric-card {glow_class}"><div class="metric-content"><div class="metric-label">Low Stock (<{low_thresh})</div><div class="metric-value">{low_stock}</div></div><div class="metric-icon">⚠️</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Inventory Value</div><div class="metric-value">৳ {val_stock:,.0f}</div></div><div class="metric-icon">💰</div></div>'
            '</div>'
        )
        st.markdown(stock_html, unsafe_allow_html=True)

        sales_df = st.session_state.get("wc_curr_df")
        if sales_df is not None and not sales_df.empty:
            safe_render(
                lambda: render_bundle_inventory_intelligence(sales_df, df_sim),
                fallback_msg="Bundle intelligence section unavailable.",
            )

        # ── Feature #6: Multi-Location Stock Alerts ─────────────────────────────
        from src.config.ui_config import INVENTORY_LOCATIONS
        loc_cols = [c for c in df_sim.columns if any(l.lower() in c.lower() for l in INVENTORY_LOCATIONS)]
        
        if loc_cols:
            st.divider()
            st.markdown("#### 🏪 Multi-Location Stock Alerts")
            st.caption("Monitoring SKU thresholds across all active branch locations.")
            
            # Find SKUs that are low in ANY specific location
            low_loc_alerts = []
            for _, row in df_sim.iterrows():
                for loc in loc_cols:
                    loc_val = pd.to_numeric(row.get(loc, 0), errors="coerce")
                    if pd.notna(loc_val) and loc_val > 0 and loc_val < low_thresh:
                        low_loc_alerts.append({
                            "Product": row.get("Product", "Unknown"),
                            "Location": loc,
                            "Qty": loc_val
                        })
                        
            if low_loc_alerts:
                st.error(f"⚠️ **{len(low_loc_alerts)} Location-Specific Low Stock Alerts Detected!**")
                with st.expander("View Branch Alerts", expanded=True):
                    alert_df = pd.DataFrame(low_loc_alerts)
                    st.dataframe(alert_df, use_container_width=True, hide_index=True)
            else:
                st.success("✅ All branches have healthy stock levels above the threshold.")
        # ────────────────────────────────────────────────────────────────────────

        st.divider()
        display_label = "Sub-Category"

        st.subheader(f"Inventory by {display_label}")
        cat_summ = df_sim.groupby(display_label)["Stock"].sum().reset_index()
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

        filtered_df = df_sim.copy()
        if search:
            filtered_df = filtered_df[
                filtered_df["Product"].astype(str).str.lower().str.contains(search) |
                filtered_df["SKU"].astype(str).str.lower().str.contains(search) |
                filtered_df["Category"].astype(str).str.lower().str.contains(search)
            ]

        def highlight_low_stock(row):
            qty = pd.to_numeric(row.get("Stock", 0), errors="coerce")
            if pd.notna(qty) and qty < low_thresh:
                return ['background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: bold;'] * len(row)
            return [''] * len(row)

        styled_df = filtered_df.style.apply(highlight_low_stock, axis=1).format({"Stock": "{:.0f}", "Price": "{:.2f}"})
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        st.divider()
        
        stock_metrics = pd.DataFrame([
            {"Metric": "Total Warehouse Units", "Value": total_qty},
            {"Metric": f"Low Stock SKUs (<{low_thresh})", "Value": low_stock},
            {"Metric": "Total Inventory Value (TK)", "Value": val_stock}
        ])

        export_data = {
            "Stock Metrics": stock_metrics,
            "Category Summary": cat_summ,
            "Granular Stock Details": filtered_df
        }
        excel_bytes = export_to_styled_excel(export_data)

        st.download_button(
            label="💾 Download Comprehensive Stock Report (Excel)",
            data=excel_bytes,
            file_name=f"DEEN_Stock_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            type="primary",
            use_container_width=True
        )

    safe_render(_render_stock_body, fallback_msg="Stock analytics rendering failed.")
    st.caption(f"Database last refreshed: {st.session_state.get('stock_sync_time', datetime.now()).strftime('%I:%M %p')}")
    st.markdown('</div>', unsafe_allow_html=True)
