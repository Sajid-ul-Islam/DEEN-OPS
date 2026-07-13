import streamlit as st
from src.components.ui_components import render_premium_header, render_metric_grid, apply_standard_dataframe
import pandas as pd
import plotly.express as px
from datetime import datetime
from itertools import combinations
from collections import Counter
import os
import io

from src.inventory import core as inv_core
from src.processing.categorization import get_category_for_sales, get_sub_category_for_sales
from src.processing.stock_categorization import map_to_csv_category
from src.pages.excel_exporter import export_to_styled_excel
from src.services.woocommerce.stock import fetch_woocommerce_stock
from src.utils.product import get_base_product_name, get_size_from_name
from src.utils.snapshots import load_stock_snapshot
from src.utils.display import truncate_label
from src.utils.safe_ops import safe_filter, safe_render
from src.config.constants import COMMON_CATS, OFFER_KEYWORDS


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

    # Compute product dependency score: ratio of paired items that co-occur in >1 order
    dependency_score = (len([p for p, c in top_pairs if c > 1]) / total_bundles) if total_bundles > 0 else 0.0

    # Compact HTML
    bundle_html = (
        '<div class="metric-container">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Bundle Fulfillment</div><div class="metric-value">{fulfillment_rate:.0f}%</div></div><div class="metric-icon">🚀</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Orphan Stock Rate</div><div class="metric-value">{orphan_pct:.1f}%</div></div><div class="metric-icon">⚠️</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Co-buy Rate</div><div class="metric-value">{dependency_score:.0%}</div></div><div class="metric-icon">🔗</div></div>'
        '</div>'
    )
    st.markdown(bundle_html, unsafe_allow_html=True)

    if fulfillment_rate < 50:
         st.error("⚠️ Fulfillment Critical: Lost sales due to bundle imbalance.")

    with st.expander("🔍 Strategic Reorder Intelligence (Component Dependency)"):
        st.write("🛠️ **ML Suggestion**: These items are heavily grouped; reorder only in pairs to avoid Orphan Stock.")
        for pair, count in top_pairs:
            st.caption(f"🤝 **High Correlation**: {pair[0]} ↔ {pair[1]} (Sales Frequency: {count})")


def render_woocommerce_stock_tab():
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

    st.markdown("#### 🔄 Data Sync & Upload")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("📡 Sync Fresh Data from WooCommerce", use_container_width=True, type="secondary"):
            st.cache_data.clear()
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

    with col2:
        manual_file = st.file_uploader("📤 Upload Manual Stock File (.csv, .xlsx)", type=["csv", "xlsx"], key="manual_wc_upload")
        if manual_file and st.button("✅ Apply Uploaded File", use_container_width=True, type="primary"):
            try:
                if manual_file.name.endswith('.csv'):
                    df_manual = pd.read_csv(manual_file)
                else:
                    df_manual = pd.read_excel(manual_file)
                    
                col_map = {
                    "Item Name": "Product", "name": "Product", "Title": "Product", 
                    "Quantity": "Stock", "item_stock": "Stock", "Inventory": "Stock", "Current Stock": "Stock"
                }
                df_manual = df_manual.rename(columns={k: v for k, v in col_map.items() if k in df_manual.columns})
                
                if "Product" in df_manual.columns and "Stock" in df_manual.columns:
                    st.session_state.wc_stock_df = df_manual
                    st.session_state.stock_sync_time = datetime.now()
                    st.toast("✅ Manual stock file loaded!", icon="🎉")
                    st.rerun()
                else:
                    st.error("Uploaded file must contain 'Product' and 'Stock' columns.")
            except Exception as e:
                st.error(f"Failed to read file: {e}")

    if df_raw is None or df_raw.empty:
        st.info("📬 No inventory data found in snapshots. Try syncing or uploading.")
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
            show_instock_only = st.toggle("Show In-Stock Only", value=False, key="stock_filter_instock_only")

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

        if show_instock_only:
            df_cat = df_cat[df_cat["Stock"] > 0]

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
            use_container_width=True,
            key="wc_stock_report_download"
        )

    safe_render(_render_stock_body, fallback_msg="Stock analytics rendering failed.")
    st.caption(f"Database last refreshed: {st.session_state.get('stock_sync_time', datetime.now()).strftime('%I:%M %p')}")


def compile_outlet_stock(loc_files):
    try:
        inv_map, warnings, enriched_dfs, sku_to_title_size = inv_core.load_inventory_from_uploads(loc_files)
        
        # Show any warnings from inv_core
        if warnings:
            for warning in warnings:
                st.warning(warning)
                
        # Build Title-Size to SKU lookup from enriched dataframes
        title_size_to_sku = {}
        for loc, df in enriched_dfs.items():
            _, _, _, sku_col = inv_core.identify_columns(df)
            if sku_col and sku_col in df.columns:
                for _, row in df.iterrows():
                    ts_val = str(row.get("Title - Size", "")).strip().casefold()
                    sku_val = str(row.get(sku_col, "")).strip()
                    if ts_val and sku_val and sku_val not in ["nan", "0", "N/A", "N/A"]:
                        title_size_to_sku[ts_val] = sku_val

        # Build WooCommerce SKU -> Product Name map
        wc_sku_to_name = {}
        wc_stock = st.session_state.get("wc_stock_df")
        if wc_stock is None:
            wc_stock = load_stock_snapshot()
        if wc_stock is not None and "SKU" in wc_stock.columns and ("Product" in wc_stock.columns or "Product Name" in wc_stock.columns):
            name_col = "Product" if "Product" in wc_stock.columns else "Product Name"
            for _, row in wc_stock.iterrows():
                sku_val = inv_core.normalize_sku(row.get("SKU", ""))
                prod_name = str(row.get(name_col, "")).strip()
                if sku_val and sku_val != "0" and prod_name:
                    wc_sku_to_name[sku_val] = prod_name

        # Determine active locations dynamically based on uploaded/passed files
        all_ordered = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet"]
        active_locs = [loc for loc in all_ordered if loc in loc_files]
        
        cat_aggregates = {}
        mapping_rows = []
        for k, locs in inv_map.items():
            if str(k).upper().startswith("SKU:"): continue
            if k in sku_to_title_size: continue
            # Skip promotional offers (combo/bundle/buy any)
            if any(kw in str(k).lower() for kw in OFFER_KEYWORDS): continue
            
            display_cat = None
            resolved_via_wc = False
            raw_sku = title_size_to_sku.get(k)
            if raw_sku:
                norm_sku = inv_core.normalize_sku(raw_sku)
                wc_name = wc_sku_to_name.get(norm_sku)
                if wc_name:
                    # Also skip if WooCommerce name is an offer
                    if any(kw in wc_name.lower() for kw in OFFER_KEYWORDS): continue
                    display_cat = map_to_csv_category(wc_name)
                    resolved_via_wc = True
            
            if not display_cat:
                display_cat = map_to_csv_category(k)
            
            row_dict = {
                "Product Name": str(k).title(), 
                "SKU": raw_sku if raw_sku else "N/A",
                "Assigned Category": display_cat,
                "Resolved via WooCommerce": "Yes" if resolved_via_wc else "No"
            }
            total_stock = 0
            for loc in active_locs:
                qty = locs.get(loc, 0)
                row_dict[loc] = qty
                if loc != "Ecom":
                    total_stock += qty
            row_dict["Total Outlet Stock"] = total_stock
            
            mapping_rows.append(row_dict)
            
            if display_cat not in cat_aggregates:
                cat_aggregates[display_cat] = {loc: 0 for loc in active_locs}
                cat_aggregates[display_cat]["Total Outlet Stock"] = 0
                
            for loc in active_locs:
                qty = locs.get(loc, 0)
                cat_aggregates[display_cat][loc] += qty
                if loc in ["Mirpur", "Wari", "Cumilla", "Sylhet"]:
                    cat_aggregates[display_cat]["Total Outlet Stock"] += qty
         
        rows = []
        for cat_name, counts in cat_aggregates.items():
            row = {"Products Name": cat_name}
            if "Ecom" in counts:
                row["Ecom"] = counts["Ecom"]
            for loc in ["Mirpur", "Wari", "Cumilla", "Sylhet"]:
                if loc in counts:
                    row[loc] = counts[loc]
            if "Total Outlet Stock" in counts:
                row["Total Outlet Stock"] = counts["Total Outlet Stock"]
                
            if "Ecom" in counts:
                outlet_sum = counts.get("Total Outlet Stock", 0)
                row["Outlet > Ecom?"] = "Yes" if outlet_sum > counts["Ecom"] else "No"
                row["Stock Difference (Outlet - Ecom)"] = outlet_sum - counts["Ecom"]
            rows.append(row)
        
        # Build SKU verification report
        verification_rows = []
        verified_skus = set()
        for k, locs in inv_map.items():
            if str(k).upper().startswith("SKU:"): continue
            if k in sku_to_title_size: continue
            if any(kw in str(k).lower() for kw in OFFER_KEYWORDS): continue
            
            raw_sku = title_size_to_sku.get(k)
            if raw_sku:
                norm_sku = inv_core.normalize_sku(raw_sku)
                if norm_sku and norm_sku != "0" and norm_sku not in verified_skus:
                    wc_name = wc_sku_to_name.get(norm_sku)
                    if wc_name:
                        base_outlet = get_base_product_name(k).strip().lower()
                        base_wc = get_base_product_name(wc_name).strip().lower()
                        
                        base_outlet_clean = base_outlet.replace("-", "").replace("–", "").replace(" ", "")
                        base_wc_clean = base_wc.replace("-", "").replace("–", "").replace(" ", "")
                        
                        is_match = base_outlet_clean == base_wc_clean
                        match_status = "Match" if is_match else "Mismatch"
                        
                        verification_rows.append({
                            "SKU": raw_sku,
                            "Outlet Product Name": k.title(),
                            "Ecom Product Name": wc_name.title(),
                            "Status": match_status
                        })
                        verified_skus.add(norm_sku)
                        
        verification_df = pd.DataFrame(verification_rows).sort_values(["Status", "SKU"]) if verification_rows else pd.DataFrame(columns=["SKU", "Outlet Product Name", "Ecom Product Name", "Status"])

        if rows:
            out_df = pd.DataFrame(rows).sort_values("Products Name")
            mapping_df = pd.DataFrame(mapping_rows).sort_values(["Assigned Category", "Product Name"])
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                out_df.to_excel(writer, sheet_name='Stock by Category', index=False)
                mapping_df.to_excel(writer, sheet_name='Product Mapping', index=False)
                verification_df.to_excel(writer, sheet_name='SKU Verification', index=False)
            excel_data = output.getvalue()
            
            st.session_state.outlet_stock_report_excel = excel_data
            st.session_state.outlet_stock_mapping_df = mapping_df
            st.session_state.outlet_stock_summary_df = out_df
            st.session_state.outlet_sku_verification_df = verification_df
            return True
        else:
            st.session_state.outlet_stock_report_excel = None
            st.session_state.outlet_stock_mapping_df = None
            st.session_state.outlet_stock_summary_df = None
            st.session_state.outlet_sku_verification_df = None
            return False
    except Exception as e:
        st.error(f"Failed to generate report: {e}")
        return False


def render_outlet_stock_analysis_tab():
    st.markdown("### 🏪 Outlet Stock Compiler")
    st.write("Consolidate stock levels across all physical outlet locations (Mirpur, Wari, Cumilla, Sylhet) and optionally include Ecom stock from WooCommerce.")


    default_files = {
        "Mirpur": "Mir.xlsx",
        "Wari": "War.xlsx",
        "Cumilla": "Cum.xlsx",
        "Sylhet": "Syl.xlsx"
    }

    st.markdown("---")
    include_ecom = st.toggle("Include Live Ecom Web Stock (WooCommerce)", value=True, help="Turn on to automatically fetch/pull WooCommerce web stock and include it in Ecom location.")
    
    # Track toggle changes in session state
    if "prev_include_ecom" not in st.session_state:
        st.session_state.prev_include_ecom = True # default
        
    if include_ecom != st.session_state.prev_include_ecom:
        st.session_state.prev_include_ecom = include_ecom
        st.session_state.outlet_stock_summary_df = None  # Force recompilation
        st.session_state.outlet_stock_cleared = False
        st.rerun()

    # Auto-compile on load using defaults if summary doesn't exist and wasn't explicitly cleared
    if st.session_state.get("outlet_stock_summary_df") is None and not st.session_state.get("outlet_stock_cleared", False):
        init_loc_files = {}
        for loc in ["Mirpur", "Wari", "Cumilla", "Sylhet"]:
            default_path = os.path.join("src", "inventory", default_files[loc])
            if os.path.exists(default_path):
                with open(default_path, "rb") as f:
                    file_bytes = f.read()
                default_obj = io.BytesIO(file_bytes)
                default_obj.name = default_files[loc]
                init_loc_files[loc] = default_obj
                
        if include_ecom:
            ecom_df = st.session_state.get("wc_stock_df")
            if ecom_df is None:
                ecom_df = load_stock_snapshot()
            if ecom_df is not None:
                init_loc_files["Ecom"] = ecom_df
                
        if init_loc_files:
            compile_outlet_stock(init_loc_files)

    # Show 4 file uploaders
    st.markdown("#### 📤 Upload Outlet Stock Lists")
    cols = st.columns(4)
    loc_files = {}

    for i, loc in enumerate(["Mirpur", "Wari", "Cumilla", "Sylhet"]):
        with cols[i]:
            uploaded = st.file_uploader(f"{loc} (.xlsx)", type=["xlsx", "csv"], key=f"outlet_file_{loc}")
            if uploaded:
                loc_files[loc] = uploaded
            elif loc in default_files:
                default_path = os.path.join("src", "inventory", default_files[loc])
                if os.path.exists(default_path):
                    with open(default_path, "rb") as f:
                        file_bytes = f.read()
                    default_obj = io.BytesIO(file_bytes)
                    default_obj.name = default_files[loc]
                    loc_files[loc] = default_obj
                    st.caption(f"✅ Default: {default_files[loc]}")
                else:
                    st.caption("ℹ️ No default file found")

    st.markdown('<div style="margin-top: 20px;"></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        generate_clicked = st.button("📊 Generate Outlet Stock Report", type="primary", use_container_width=True)
    with c2:
        if st.button("🧹 Clear Compilation Results", use_container_width=True):
            st.session_state.outlet_stock_report_excel = None
            st.session_state.outlet_stock_mapping_df = None
            st.session_state.outlet_stock_summary_df = None
            st.session_state.outlet_stock_cleared = True
            st.toast("Cleared compilation results.")
            st.rerun()

    if generate_clicked:
        st.session_state.outlet_stock_cleared = False
        
        if include_ecom:
            with st.spinner("Fetching Live Ecom Stock..."):
                ecom_df = st.session_state.get("wc_stock_df")
                if ecom_df is None:
                    ecom_df = load_stock_snapshot()
                    if ecom_df is None:
                        ecom_df = fetch_woocommerce_stock()
                        if ecom_df is not None:
                            st.session_state.wc_stock_df = ecom_df
                if ecom_df is not None:
                    loc_files["Ecom"] = ecom_df
                else:
                    st.warning("⚠️ Could not fetch WooCommerce stock. Proceeding without Ecom.")
                    
        with st.spinner("Compiling stock data..."):
            if compile_outlet_stock(loc_files):
                st.toast("✅ Report generated successfully!", icon="🎉")

    # Display compiled results if they exist
    out_df = st.session_state.get("outlet_stock_summary_df")
    excel_data = st.session_state.get("outlet_stock_report_excel")
    mapping_df = st.session_state.get("outlet_stock_mapping_df")

    if out_df is not None and not out_df.empty:
        st.divider()
        
        # Display high level metrics
        total_units = out_df["Total Outlet Stock"].sum()
        total_categories = len(out_df)
        
        # Premium Metric layout
        st.markdown(
            '<div class="metric-container">'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Total Outlet Units</div><div class="metric-value">{total_units:,.0f}</div></div><div class="metric-icon">🏪</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Product Categories</div><div class="metric-value">{total_categories}</div></div><div class="metric-icon">🏷️</div></div>'
            '</div>',
            unsafe_allow_html=True
        )
        
        st.divider()
        
        v1, v2 = st.columns([1, 1], gap="large")
        with v1:
            st.markdown("#### 📋 Stock by Category Summary")
            st.dataframe(out_df, use_container_width=True, hide_index=True)
            
        with v2:
            st.markdown("#### 📊 Stock Distribution by Category")
            
            # Find available outlet columns
            available_outlets = [col for col in ["Mirpur", "Wari", "Cumilla", "Sylhet", "Ecom"] if col in out_df.columns]
            
            if available_outlets:
                selected_outlets = st.pills(
                    "Filter by Outlet",
                    options=available_outlets,
                    default=available_outlets,
                    selection_mode="multi",
                    label_visibility="collapsed",
                    key="chart_outlet_filter"
                )
            else:
                selected_outlets = []
                
            if not selected_outlets:
                st.info("Please select at least one outlet to view the chart.")
            else:
                chart_df = out_df.copy()
                chart_df["Selected Stock"] = chart_df[selected_outlets].fillna(0).sum(axis=1)
                chart_df = chart_df[chart_df["Selected Stock"] > 0]
                
                fig = px.bar(
                    chart_df,
                    x="Selected Stock",
                    y="Products Name",
                    orientation="h",
                    color="Selected Stock",
                    color_continuous_scale="Viridis",
                    labels={"Products Name": "Category", "Selected Stock": "Units"}
                )
                fig.update_layout(
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=False,
                    coloraxis_showscale=False,
                    yaxis_title="",
                    xaxis_title="Units"
                )
                st.plotly_chart(fig, use_container_width=True)
            
        st.divider()
        
        # Download Button
        st.download_button(
            "📥 Download Consolidated Outlet Stock Excel",
            data=excel_data,
            file_name=f"{datetime.now().strftime('%Y-%m-%d')}_outlet_stock.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary"
        )
        
        # Mapping Details & SKU Verification Report
        c_map, c_ver = st.columns(2)
        with c_map:
            with st.expander("🔍 Show Product-to-Category Mapping Detail"):
                st.caption("Products that didn't match any keyword are categorized as 'Others'.")
                if mapping_df is not None:
                    st.dataframe(mapping_df, use_container_width=True)
                    
        with c_ver:
            verification_df = st.session_state.get("outlet_sku_verification_df")
            with st.expander("🛡️ Show SKU Name Verification Report"):
                if verification_df is not None and not verification_df.empty:
                    mismatches = verification_df[verification_df["Status"] == "Mismatch"]
                    if not mismatches.empty:
                        st.warning(f"⚠️ Found {len(mismatches)} product name mismatches between Outlets and Ecom (WooCommerce)!")
                    else:
                        st.success("✅ All checked SKU product names match perfectly between Outlets and Ecom!")
                    st.dataframe(verification_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No SKU data verified. Make sure live WooCommerce web stock is included.")


def render_stock_analytics_tab():
    """Renders the category-wise stock monitoring interface."""
    # Ensure navigation lock is in place
    if "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = "📦 Current Stock Analytics"

    # Initialize session state for outlet stock report
    if "outlet_stock_report_excel" not in st.session_state:
        st.session_state.outlet_stock_report_excel = None
    if "outlet_stock_mapping_df" not in st.session_state:
        st.session_state.outlet_stock_mapping_df = None
    if "outlet_stock_summary_df" not in st.session_state:
        st.session_state.outlet_stock_summary_df = None
    if "outlet_sku_verification_df" not in st.session_state:
        st.session_state.outlet_sku_verification_df = None

    render_premium_header("Current Stock Analytics", "Monitor and analyze inventory across all locations and WooCommerce", "📦")

    # Define tabs
    tab_web, tab_outlet = st.tabs([":material/database: WooCommerce Stock", ":material/storefront: Outlet Stock Analysis"])

    with tab_web:
        render_woocommerce_stock_tab()

    with tab_outlet:
        render_outlet_stock_analysis_tab()
        
    st.markdown('</div>', unsafe_allow_html=True)
