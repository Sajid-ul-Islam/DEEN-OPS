import io
import os
from collections import Counter
from itertools import combinations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.components.ui.ui_components import render_premium_header
from src.config.constants import COMMON_CATS, OFFER_KEYWORDS, bd_now, bd_today
from src.inventory import core as inv_core
from src.processing.categorization import (
    get_category_for_sales,
    get_sub_category_for_sales,
)
from src.processing.sip_outlet_processor import (
    parse_stock_report,
    pivot_stock_report,
)
from src.processing.stock_categorization import map_to_csv_category
from src.services.exports.excel_exporter import export_to_styled_excel
from src.services.woocommerce.stock import fetch_woocommerce_stock
from src.utils.display import truncate_label
from src.utils.product import get_base_product_name, get_size_from_name
from src.utils.safe_ops import safe_filter, safe_render

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _normalize_stock_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce Stock / Price to clean numerics in place (returns same frame)."""
    if "Stock" in df.columns:
        df["Stock"] = pd.to_numeric(
            df["Stock"].astype(str).str.replace(r"[^\d.-]", "", regex=True),
            errors="coerce",
        ).astype(float)
    if "Price" in df.columns:
        df["Price"] = (
            pd.to_numeric(
                df["Price"].astype(str).str.replace(r"[^\d.]", "", regex=True),
                errors="coerce",
            )
            .fillna(0)
            .astype(float)
        )
    return df


def _render_kpi_strip(metrics: list) -> None:
    """Render a row of premium metric cards via the shared component."""
    from src.components.ui.ui_components import render_metric_grid

    render_metric_grid(metrics)


def _load_wc_stock() -> pd.DataFrame | None:
    """Load WooCommerce stock from session, snapshot, or live API."""
    df = st.session_state.get("wc_stock_df")
    if df is not None:
        return df
    df = load_snapshot_quiet()
    if df is not None:
        st.session_state.wc_stock_df = df
    return df


def load_snapshot_quiet() -> pd.DataFrame | None:
    """Snapshot loader guarded so a missing file never raises."""
    from src.utils.snapshots import load_stock_snapshot

    try:
        return load_stock_snapshot()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tab 1: WooCommerce Stock
# ---------------------------------------------------------------------------


def render_bundle_inventory_intelligence(sales_df, stock_df):
    """Integrates Market Basket behavior with Inventory KPIs."""
    st.divider()
    st.markdown("#### 🤖 Bundle-Aware Inventory Intelligence")

    order_col = (
        "Order ID"
        if "Order ID" in sales_df.columns
        else ("Order Number" if "Order Number" in sales_df.columns else None)
    )
    name_col = (
        "Product Name"
        if "Product Name" in sales_df.columns
        else ("Item Name" if "Item Name" in sales_df.columns else None)
    )

    if not order_col or not name_col:
        st.info("Insufficient data schema for bundle analysis.")
        return

    basket_df = sales_df.groupby(order_col)[name_col].apply(list).reset_index()
    basket_df = basket_df[basket_df[name_col].apply(len) > 1]

    if basket_df.empty:
        st.info(
            "No bundle history found in current sales window to analyze dependency."
        )
        return

    all_pairs = []
    for products in basket_df[name_col]:
        all_pairs.extend(list(combinations(set(products), 2)))

    top_pairs = Counter(all_pairs).most_common(5)

    full_count = 0
    total_bundles = len(top_pairs)
    orphan_skus = []

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

    stock_col = (
        "Stock"
        if "Stock" in stock_df.columns
        else "Quantity"
        if "Quantity" in stock_df.columns
        else None
    )
    if not stock_col:
        return

    for pair, _count in top_pairs:
        stock_a = stock_df[stock_df[inv_name_col] == pair[0]][stock_col].sum()
        stock_b = stock_df[stock_df[inv_name_col] == pair[1]][stock_col].sum()

        if stock_a > 0 and stock_b > 0:
            full_count += 1
        elif (stock_a > 0 and stock_b <= 0) or (stock_b > 0 and stock_a <= 0):
            orphan_skus.append(pair[0] if stock_a > 0 else pair[1])

    fulfillment_rate = (full_count / total_bundles * 100) if total_bundles > 0 else 0
    orphan_pct = (
        (len(set(orphan_skus)) / len(stock_df[inv_name_col].unique()) * 100)
        if not stock_df.empty
        else 0
    )

    dependency_score = (
        (len([p for p, c in top_pairs if c > 1]) / total_bundles)
        if total_bundles > 0
        else 0.0
    )

    bundle_html = (
        '<div class="metric-container">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Bundle Fulfillment</div><div class="metric-value">{fulfillment_rate:.0f}%</div></div><div class="metric-icon">🚀</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Orphan Stock Rate</div><div class="metric-value">{orphan_pct:.1f}%</div></div><div class="metric-icon">⚠️</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Co-buy Rate</div><div class="metric-value">{dependency_score:.0%}</div></div><div class="metric-icon">🔗</div></div>'
        "</div>"
    )
    st.markdown(bundle_html, unsafe_allow_html=True)

    if fulfillment_rate < 50:
        st.error("⚠️ Fulfillment Critical: Lost sales due to bundle imbalance.")

    with st.expander("🔍 Strategic Reorder Intelligence (Component Dependency)"):
        st.write(
            "🛠️ **ML Suggestion**: These items are heavily grouped; reorder only in pairs to avoid Orphan Stock."
        )
        for pair, count in top_pairs:
            st.caption(
                f"🤝 **High Correlation**: {pair[0]} ↔ {pair[1]} (Sales Frequency: {count})"
            )


def _wc_stock_sync_row(df_raw) -> None:
    """Sync / upload controls for the WooCommerce stock tab."""
    st.markdown("#### 🔄 Data Sync & Upload")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            "📡 Sync Fresh Data from WooCommerce",
            use_container_width=True,
            type="secondary",
        ):
            st.cache_data.clear()
            with st.status(
                "Updating from WooCommerce...", expanded=True
            ) as sync_status:
                st.write("📡 Fetching latest stock levels...")
                df_fresh = fetch_woocommerce_stock()
                if df_fresh is not None:
                    st.session_state.wc_stock_df = df_fresh
                    st.session_state.stock_sync_time = bd_now()
                    sync_status.update(
                        label="Database Updated", state="complete", expanded=False
                    )
                    st.toast("✅ Stock database updated!", icon="🎉")
                    st.rerun()
                else:
                    sync_status.update(
                        label="Update Failed", state="error", expanded=False
                    )

    with col2:
        manual_file = st.file_uploader(
            "📤 Upload Manual Stock File (.csv, .xlsx)",
            type=["csv", "xlsx"],
            key="manual_wc_upload",
        )
        if manual_file and st.button(
            "✅ Apply Uploaded File", use_container_width=True, type="primary"
        ):
            try:
                if manual_file.name.endswith(".csv"):
                    df_manual = pd.read_csv(manual_file)
                else:
                    df_manual = pd.read_excel(manual_file)

                col_map = {
                    "Item Name": "Product",
                    "name": "Product",
                    "Title": "Product",
                    "Quantity": "Stock",
                    "item_stock": "Stock",
                    "Inventory": "Stock",
                    "Current Stock": "Stock",
                }
                df_manual = df_manual.rename(
                    columns={k: v for k, v in col_map.items() if k in df_manual.columns}
                )

                if "Product" in df_manual.columns and "Stock" in df_manual.columns:
                    st.session_state.wc_stock_df = df_manual
                    st.session_state.stock_sync_time = bd_now()
                    st.toast("✅ Manual stock file loaded!", icon="🎉")
                    st.rerun()
                else:
                    st.error(
                        "Uploaded file must contain 'Product' and 'Stock' columns."
                    )
            except Exception as e:
                st.error(f"Failed to read file: {e}")


def render_woocommerce_stock_tab():
    """WooCommerce web stock: sync, scenario simulator, category breakdown."""
    df_raw = _load_wc_stock()

    if df_raw is None:
        with st.status("🚀 Initial API sync...", expanded=True) as sync_status:
            st.write("📡 Fetching products from WooCommerce...")
            df_raw = fetch_woocommerce_stock()
            if df_raw is not None:
                st.session_state.wc_stock_df = df_raw
                st.session_state.stock_sync_time = bd_now()
                sync_status.update(
                    label="Inventory Sync Complete", state="complete", expanded=False
                )
                st.toast("✅ Inventory data loaded!", icon="🎉")
            else:
                sync_status.update(label="Sync Failed", state="error", expanded=False)
                st.warning("No inventory data found. Check WooCommerce connection.")
                return

    _wc_stock_sync_row(df_raw)

    if df_raw is None or df_raw.empty:
        st.info("📬 No inventory data found in snapshots. Try syncing or uploading.")
        return

    _normalize_stock_columns(df_raw)

    if "Sub-Category" not in df_raw.columns or "Clean_Product" not in df_raw.columns:
        if "Product" not in df_raw.columns:
            st.error("Required 'Product' column not found in inventory data.")
            return
        df_raw["Category"] = df_raw["Product"].apply(get_category_for_sales)
        df_raw["Sub-Category"] = df_raw.apply(
            lambda r: get_sub_category_for_sales(r["Product"], r["Category"]), axis=1
        )
        df_raw["Clean_Product"] = df_raw["Product"].apply(get_base_product_name)
        df_raw["Filter_Identity"] = (
            df_raw["Clean_Product"].astype(str) + " [" + df_raw["SKU"].astype(str) + "]"
        )

    with st.expander("🛠️ Filter Intelligence", expanded=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            unified_options = COMMON_CATS
            sel_unified = st.multiselect(
                "Select Category / Fit",
                unified_options,
                placeholder="All Categories",
                key="stock_filter_unified",
            )
            show_instock_only = st.toggle(
                "Show In-Stock Only", value=False, key="stock_filter_instock_only"
            )

        if sel_unified:

            def _cat_filter(d):
                mask = pd.Series(False, index=d.index)
                for opt in sel_unified:
                    if "  \u21b3 " in opt:
                        sub_name = opt.replace("  \u21b3 ", "")
                        mask |= d["Sub-Category"] == sub_name
                    else:
                        mask |= d["Category"] == opt
                return d[mask]

            df_cat = safe_filter(df_raw, _cat_filter, "Category/Fit")
        else:
            df_cat = df_raw

        if show_instock_only:
            df_cat = df_cat[df_cat["Stock"] > 0]

        with f2:
            base_options = sorted(
                [
                    str(x)
                    for x in df_cat["Filter_Identity"].unique().tolist()
                    if x is not None
                ]
            )
            sel_bases = st.multiselect(
                "Select Item / Product", base_options, placeholder="All Items"
            )

        df_base = (
            safe_filter(
                df_cat, lambda d: d[d["Filter_Identity"].isin(sel_bases)], "Item"
            )
            if sel_bases
            else df_cat
        )

        with f3:
            if "Size" not in df_base.columns:
                df_base["Size"] = (
                    df_base["Product"].astype(str).apply(get_size_from_name)
                )
            size_options = sorted(
                [str(x) for x in df_base["Size"].unique().tolist() if x is not None]
            )
            sel_sizes = st.multiselect(
                "Select Size", size_options, placeholder="All Sizes"
            )
            df = (
                safe_filter(df_base, lambda d: d[d["Size"].isin(sel_sizes)], "Size")
                if sel_sizes
                else df_base
            )

    if df.empty:
        st.info("📬 No inventory data matches your current filters.")
        return

    df = _normalize_stock_columns(df.copy())
    _render_stock_body(df)


def _render_stock_body(df: pd.DataFrame) -> None:
    """Scenario simulator + charts + table + export for filtered WC stock."""
    st.divider()
    st.subheader("🧮 Live Scenario Simulator")
    st.markdown(
        "Adjust the sliders below to simulate stock and price changes. Metrics, charts, and table highlights will update in real-time."
    )
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        sim_stock_adj = st.slider(
            "Simulate Stock Adjustment (%)",
            -100,
            100,
            0,
            step=5,
            help="Simulate a percentage change in available warehouse units.",
        )
    with sc2:
        sim_price_adj = st.slider(
            "Simulate Price Adjustment (%)",
            -50,
            100,
            0,
            step=5,
            help="Simulate a percentage markup or discount on inventory value.",
        )
    with sc3:
        low_thresh = st.number_input(
            "Low Stock Highlight Threshold",
            min_value=1,
            max_value=500,
            value=10,
            step=1,
            help="Highlight items with stock below this number.",
        )

    df_sim = df.copy()
    df_sim["Stock"] = pd.to_numeric(df_sim["Stock"], errors="coerce").fillna(
        0
    ).astype(float) * (1 + (sim_stock_adj / 100.0))
    df_sim["Price"] = pd.to_numeric(df_sim["Price"], errors="coerce").fillna(
        0
    ).astype(float) * (1 + (sim_price_adj / 100.0))

    st.divider()
    current_stocks = df_sim["Stock"]
    total_qty = current_stocks.sum()
    low_stock = (current_stocks < low_thresh).sum()
    val_stock = (current_stocks * df_sim["Price"]).sum()
    out_of_stock = (current_stocks <= 0).sum()
    sku_count = len(df_sim)

    glow_class = "critical-glow" if (low_stock / len(df_sim) > 0.2) else ""

    stock_html = (
        '<div class="metric-container">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Warehouse Units</div><div class="metric-value">{total_qty:,.0f}</div></div><div class="metric-icon">🏠</div></div>'
        f'<div class="metric-card {glow_class}"><div class="metric-content"><div class="metric-label">Low Stock (<{low_thresh})</div><div class="metric-value">{low_stock}</div></div><div class="metric-icon">⚠️</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Out of Stock</div><div class="metric-value">{out_of_stock}</div></div><div class="metric-icon">🚫</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Inventory Value</div><div class="metric-value">৳ {val_stock:,.0f}</div></div><div class="metric-icon">💰</div></div>'
        "</div>"
    )
    st.markdown(stock_html, unsafe_allow_html=True)

    sales_df = st.session_state.get("wc_curr_df")
    if sales_df is not None and not sales_df.empty:
        safe_render(
            lambda: render_bundle_inventory_intelligence(sales_df, df_sim),
            fallback_msg="Bundle intelligence section unavailable.",
        )

    # ── Multi-Location Stock Alerts ─────────────────────────────────────────
    from src.config.ui_config import INVENTORY_LOCATIONS

    loc_cols = [
        c
        for c in df_sim.columns
        if any(loc_name.lower() in c.lower() for loc_name in INVENTORY_LOCATIONS)
    ]

    if loc_cols:
        st.divider()
        st.markdown("#### 🏪 Multi-Location Stock Alerts")
        st.caption("Monitoring SKU thresholds across all active branch locations.")

        low_loc_alerts = []
        for _, row in df_sim.iterrows():
            for loc in loc_cols:
                loc_val = pd.to_numeric(row.get(loc, 0), errors="coerce")
                if pd.notna(loc_val) and loc_val > 0 and loc_val < low_thresh:
                    low_loc_alerts.append(
                        {
                            "Product": row.get("Product", "Unknown"),
                            "Location": loc,
                            "Qty": loc_val,
                        }
                    )

        if low_loc_alerts:
            st.error(
                f"⚠️ **{len(low_loc_alerts)} Location-Specific Low Stock Alerts Detected!**"
            )
            with st.expander("View Branch Alerts", expanded=True):
                alert_df = pd.DataFrame(low_loc_alerts)
                st.dataframe(alert_df, use_container_width=True, hide_index=True)
        else:
            st.success(
                "✅ All branches have healthy stock levels above the threshold."
            )
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
        fig = px.bar(
            fig_data,
            x="Stock",
            y="Short_Label",
            orientation="h",
            title=f"Top Volume: {display_label}",
            color="Stock",
            color_continuous_scale="Plasma",
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=30, b=0),
            showlegend=False,
            coloraxis_showscale=False,
            yaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Granular Stock Details")
    search = (
        st.text_input("🔍 Filter by Product Name, SKU, or Category", "")
        .strip()
        .lower()
    )

    filtered_df = df_sim.copy()
    if search:
        filtered_df = filtered_df[
            filtered_df["Product"].astype(str).str.lower().str.contains(search)
            | filtered_df["SKU"].astype(str).str.lower().str.contains(search)
            | filtered_df["Category"].astype(str).str.lower().str.contains(search)
        ]

    def highlight_low_stock(row):
        qty = pd.to_numeric(row.get("Stock", 0), errors="coerce")
        if pd.notna(qty) and qty < low_thresh:
            return [
                "background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: bold;"
            ] * len(row)
        return [""] * len(row)

    styled_df = filtered_df.style.apply(highlight_low_stock, axis=1).format(
        {"Stock": "{:.0f}", "Price": "{:.2f}"}
    )
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    st.divider()

    stock_metrics = pd.DataFrame(
        [
            {"Metric": "Total Warehouse Units", "Value": total_qty},
            {"Metric": f"Low Stock SKUs (<{low_thresh})", "Value": low_stock},
            {"Metric": "Total Inventory Value (TK)", "Value": val_stock},
        ]
    )

    export_data = {
        "Stock Metrics": stock_metrics,
        "Category Summary": cat_summ,
        "Granular Stock Details": filtered_df,
    }
    excel_bytes = export_to_styled_excel(export_data)

    st.download_button(
        label="💾 Download Comprehensive Stock Report (Excel)",
        data=excel_bytes,
        file_name=f"DEEN_Stock_Report_{bd_today().strftime('%Y%m%d')}.xlsx",
        type="primary",
        use_container_width=True,
        key="wc_stock_report_download",
    )


# ---------------------------------------------------------------------------
# Tab 2: Outlet Stock Compiler
# ---------------------------------------------------------------------------


def compile_outlet_stock(loc_files):
    try:
        inv_map, warnings, enriched_dfs, sku_to_title_size = (
            inv_core.load_inventory_from_uploads(loc_files)
        )

        if warnings:
            for warning in warnings:
                st.warning(warning)

        title_size_to_sku = {}
        for _, df in enriched_dfs.items():
            _, _, _, sku_col = inv_core.identify_columns(df)
            if sku_col and sku_col in df.columns:
                for _, row in df.iterrows():
                    ts_val = str(row.get("Title - Size", "")).strip().casefold()
                    sku_val = str(row.get(sku_col, "")).strip()
                    if ts_val and sku_val and sku_val not in ["nan", "0", "N/A", "N/A"]:
                        title_size_to_sku[ts_val] = sku_val

        wc_sku_to_name = {}
        wc_stock = st.session_state.get("wc_stock_df")
        if wc_stock is None:
            wc_stock = load_snapshot_quiet()
        if (
            wc_stock is not None
            and "SKU" in wc_stock.columns
            and ("Product" in wc_stock.columns or "Product Name" in wc_stock.columns)
        ):
            name_col = "Product" if "Product" in wc_stock.columns else "Product Name"
            for _, row in wc_stock.iterrows():
                sku_val = inv_core.normalize_sku(row.get("SKU", ""))
                prod_name = str(row.get(name_col, "")).strip()
                if sku_val and sku_val != "0" and prod_name:
                    wc_sku_to_name[sku_val] = prod_name

        all_ordered = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet"]
        active_locs = [loc for loc in all_ordered if loc in loc_files]

        cat_aggregates = {}
        mapping_rows = []
        for k, locs in inv_map.items():
            if str(k).upper().startswith("SKU:"):
                continue
            if k in sku_to_title_size:
                continue
            if any(kw in str(k).lower() for kw in OFFER_KEYWORDS):
                continue

            display_cat = None
            resolved_via_wc = False
            raw_sku = title_size_to_sku.get(str(k).strip().casefold())
            if raw_sku:
                norm_sku = inv_core.normalize_sku(raw_sku)
                wc_name = wc_sku_to_name.get(norm_sku)
                if wc_name:
                    if any(kw in wc_name.lower() for kw in OFFER_KEYWORDS):
                        continue
                    display_cat = map_to_csv_category(wc_name)
                    resolved_via_wc = True

            if not display_cat:
                display_cat = map_to_csv_category(k)

            row_dict = {
                "Product Name": str(k).title(),
                "SKU": raw_sku if raw_sku else "N/A",
                "Assigned Category": display_cat,
                "Resolved via WooCommerce": "Yes" if resolved_via_wc else "No",
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

        verification_rows = []
        verified_skus = set()
        for k, _ in inv_map.items():
            if str(k).upper().startswith("SKU:"):
                continue
            if k in sku_to_title_size:
                continue
            if any(kw in str(k).lower() for kw in OFFER_KEYWORDS):
                continue

            raw_sku = title_size_to_sku.get(str(k).strip().casefold())
            if raw_sku:
                norm_sku = inv_core.normalize_sku(raw_sku)
                if norm_sku and norm_sku != "0" and norm_sku not in verified_skus:
                    wc_name = wc_sku_to_name.get(norm_sku)
                    if wc_name:
                        base_outlet = get_base_product_name(k).strip().lower()
                        base_wc = get_base_product_name(wc_name).strip().lower()

                        base_outlet_clean = (
                            base_outlet.replace("-", "")
                            .replace("–", "")
                            .replace(" ", "")
                        )
                        base_wc_clean = (
                            base_wc.replace("-", "").replace("–", "").replace(" ", "")
                        )

                        is_match = base_outlet_clean == base_wc_clean
                        match_status = "Match" if is_match else "Mismatch"

                        verification_rows.append(
                            {
                                "SKU": raw_sku,
                                "Outlet Product Name": k.title(),
                                "Ecom Product Name": wc_name.title(),
                                "Status": match_status,
                            }
                        )
                        verified_skus.add(norm_sku)

        verification_df = (
            pd.DataFrame(verification_rows).sort_values(["Status", "SKU"])
            if verification_rows
            else pd.DataFrame(
                columns=["SKU", "Outlet Product Name", "Ecom Product Name", "Status"]
            )
        )

        if rows:
            out_df = pd.DataFrame(rows).sort_values("Products Name")
            mapping_df = pd.DataFrame(mapping_rows).sort_values(
                ["Assigned Category", "Product Name"]
            )

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                out_df.to_excel(writer, sheet_name="Stock by Category", index=False)
                mapping_df.to_excel(writer, sheet_name="Product Mapping", index=False)
                verification_df.to_excel(
                    writer, sheet_name="SKU Verification", index=False
                )
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


def _outlet_default_file(loc: str, default_files: dict) -> io.BytesIO | None:
    """Load the default outlet file for a location, if present."""
    default_path = os.path.join("src", "inventory", default_files[loc])
    if not os.path.exists(default_path):
        return None
    with open(default_path, "rb") as f:
        file_bytes = f.read()
    obj = io.BytesIO(file_bytes)
    obj.name = default_files[loc]
    return obj


def render_outlet_stock_analysis_tab():
    st.markdown("### 🏪 Outlet Stock Compiler")
    st.write(
        "Consolidate stock levels across all physical outlet locations (Mirpur, Wari, Cumilla, Sylhet) and optionally include Ecom stock from WooCommerce."
    )

    c_info, c_jump = st.columns([3, 1])
    with c_info:
        st.info(
            "💡 **Looking for customer order outlet fulfillment, picking lists, or Pathao bulk consignments?** "
            "Go to **Outlet Dispatch & Product Listing** in **🛒 Orders & Fulfillment**."
        )
    with c_jump:
        if st.button(
            "🏬 Open Outlet Dispatch",
            key="jump_to_outlet_extractor_btn",
            use_container_width=True,
            help="Navigate directly to Outlet Dispatch & Product Listing (Manager, Picking & Pathao Bulk)",
        ):
            st.session_state["selected_nav"] = "🛒 Orders & Fulfillment"
            st.session_state["sidebar_nav"] = "🛒 Orders & Fulfillment"
            st.session_state["orders_sub_feature"] = "Outlet Dispatch & Product Listing"
            st.rerun()

    default_files = {
        "Mirpur": "Mir.xlsx",
        "Wari": "War.xlsx",
        "Cumilla": "Cum.xlsx",
        "Sylhet": "Syl.xlsx",
    }

    st.markdown("---")
    include_ecom = st.toggle(
        "Include Live Ecom Web Stock (WooCommerce)",
        value=True,
        help="Turn on to automatically fetch/pull WooCommerce web stock and include it in Ecom location.",
    )

    if "prev_include_ecom" not in st.session_state:
        st.session_state.prev_include_ecom = True

    if include_ecom != st.session_state.prev_include_ecom:
        st.session_state.prev_include_ecom = include_ecom
        st.session_state.outlet_stock_summary_df = None
        st.session_state.outlet_stock_cleared = False
        st.rerun()

    if st.session_state.get(
        "outlet_stock_summary_df"
    ) is None and not st.session_state.get("outlet_stock_cleared", False):
        init_loc_files = {}
        for loc in ["Mirpur", "Wari", "Cumilla", "Sylhet"]:
            obj = _outlet_default_file(loc, default_files)
            if obj is not None:
                init_loc_files[loc] = obj

        if include_ecom:
            ecom_df = st.session_state.get("wc_stock_df")
            if ecom_df is None:
                ecom_df = load_snapshot_quiet()
            if ecom_df is not None:
                init_loc_files["Ecom"] = ecom_df

        if init_loc_files:
            compile_outlet_stock(init_loc_files)

    st.markdown("#### 📤 Upload Outlet Stock Lists")
    cols = st.columns(4)
    loc_files = {}

    for i, loc in enumerate(["Mirpur", "Wari", "Cumilla", "Sylhet"]):
        with cols[i]:
            uploaded = st.file_uploader(
                f"{loc} (.xlsx)", type=["xlsx", "csv"], key=f"outlet_file_{loc}"
            )
            if uploaded:
                loc_files[loc] = uploaded
            else:
                obj = _outlet_default_file(loc, default_files)
                if obj is not None:
                    loc_files[loc] = obj
                    st.caption(f"✅ Default: {default_files[loc]}")
                else:
                    st.caption("ℹ️ No default file found")

    st.markdown('<div style="margin-top: 20px;"></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        generate_clicked = st.button(
            "📊 Generate Outlet Stock Report", type="primary", use_container_width=True
        )
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
                    ecom_df = load_snapshot_quiet()
                    if ecom_df is None:
                        ecom_df = fetch_woocommerce_stock()
                        if ecom_df is not None:
                            st.session_state.wc_stock_df = ecom_df
                if ecom_df is not None:
                    loc_files["Ecom"] = ecom_df
                else:
                    st.warning(
                        "⚠️ Could not fetch WooCommerce stock. Proceeding without Ecom."
                    )

        with st.spinner("Compiling stock data..."):
            if compile_outlet_stock(loc_files):
                st.toast("✅ Report generated successfully!", icon="🎉")

    out_df = st.session_state.get("outlet_stock_summary_df")
    excel_data = st.session_state.get("outlet_stock_report_excel")
    mapping_df = st.session_state.get("outlet_stock_mapping_df")

    if out_df is not None and not out_df.empty:
        st.divider()

        total_units = out_df["Total Outlet Stock"].sum()
        total_categories = len(out_df)

        _render_kpi_strip(
            [
                {"label": "Total Outlet Units", "value": f"{total_units:,.0f}", "icon": "🏪"},
                {"label": "Product Categories", "value": str(total_categories), "icon": "🏷️"},
            ]
        )

        st.divider()

        v1, v2 = st.columns([1, 1], gap="large")
        with v1:
            st.markdown("#### 📋 Stock by Category Summary")
            st.dataframe(out_df, use_container_width=True, hide_index=True)

        with v2:
            st.markdown("#### 📊 Stock Distribution by Category")

            available_outlets = [
                col
                for col in ["Mirpur", "Wari", "Cumilla", "Sylhet", "Ecom"]
                if col in out_df.columns
            ]

            if available_outlets:
                selected_outlets = st.pills(
                    "Filter by Outlet",
                    options=available_outlets,
                    default=available_outlets,
                    selection_mode="multi",
                    label_visibility="collapsed",
                    key="chart_outlet_filter",
                )
            else:
                selected_outlets = []

            if not selected_outlets:
                st.info("Please select at least one outlet to view the chart.")
            else:
                chart_df = out_df.copy()
                chart_df["Selected Stock"] = (
                    chart_df[selected_outlets].fillna(0).sum(axis=1)
                )
                chart_df = chart_df[chart_df["Selected Stock"] > 0]

                fig = px.bar(
                    chart_df,
                    x="Selected Stock",
                    y="Products Name",
                    orientation="h",
                    color="Selected Stock",
                    color_continuous_scale="Viridis",
                    labels={"Products Name": "Category", "Selected Stock": "Units"},
                )
                fig.update_layout(
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=False,
                    coloraxis_showscale=False,
                    yaxis_title="",
                    xaxis_title="Units",
                )
                st.plotly_chart(fig, use_container_width=True)

        st.divider()

        st.download_button(
            "📥 Download Consolidated Outlet Stock Excel",
            data=excel_data,
            file_name=f"{bd_today().strftime('%Y-%m-%d')}_outlet_stock.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )

        c_map, c_ver = st.columns(2)
        with c_map:
            with st.expander("🔍 Show Product-to-Category Mapping Detail"):
                st.caption(
                    "Products that didn't match any keyword are categorized as 'Others'."
                )
                if mapping_df is not None:
                    st.dataframe(mapping_df, use_container_width=True)

        with c_ver:
            verification_df = st.session_state.get("outlet_sku_verification_df")
            with st.expander("🛡️ Show SKU Name Verification Report"):
                if verification_df is not None and not verification_df.empty:
                    mismatches = verification_df[
                        verification_df["Status"] == "Mismatch"
                    ]
                    if not mismatches.empty:
                        st.warning(
                            f"⚠️ Found {len(mismatches)} product name mismatches between Outlets and Ecom (WooCommerce)!"
                        )
                    else:
                        st.success(
                            "✅ All checked SKU product names match perfectly between Outlets and Ecom!"
                        )
                    st.dataframe(
                        verification_df, use_container_width=True, hide_index=True
                    )
                else:
                    st.info(
                        "No SKU data verified. Make sure live WooCommerce web stock is included."
                    )


# ---------------------------------------------------------------------------
# Tab 3: SIP Live Stock (Smart Inventory with POS)
# ---------------------------------------------------------------------------


def _sip_kpi_strip(pivot_df: pd.DataFrame, source_label: str) -> None:
    """KPI cards for the SIP tab from a pivoted stock frame."""
    total_units = int(pivot_df["Total"].sum())
    wh_units = int(pivot_df["Warehouse"].sum()) if "Warehouse" in pivot_df.columns else 0
    outlet_units = total_units - wh_units
    total_skus = len(pivot_df)
    zero_skus = int((pivot_df["Total"] <= 0).sum())

    _render_kpi_strip(
        [
            {"label": "Total Units", "value": f"{total_units:,}", "icon": "\U0001F4E6"},
            {"label": "Warehouse Units", "value": f"{wh_units:,}", "icon": "\U0001F3E0"},
            {"label": "Outlet Units", "value": f"{outlet_units:,}", "icon": "\U0001F3EA"},
            {"label": "Unique SKUs", "value": f"{total_skus:,}", "icon": "\U0001F522"},
            {"label": "Zero-Stock SKUs", "value": f"{zero_skus:,}", "icon": "\U0001F6AB"},
            {"label": "Source", "value": source_label, "icon": "\U0001F552"},
        ]
    )


def _sip_warehouse_view(pivot_df: pd.DataFrame) -> None:
    """Warehouse lens: central stock health and transfer candidates."""
    if "Warehouse" not in pivot_df.columns:
        st.info("No Warehouse rows in this stock report.")
        return

    wh = pivot_df[pivot_df["Warehouse"] > 0].sort_values("Warehouse", ascending=False)
    wh_units = int(pivot_df["Warehouse"].sum())
    only_outlet = int(((pivot_df["Warehouse"] <= 0) & (pivot_df["Total"] > 0)).sum())

    _render_kpi_strip(
        [
            {"label": "Warehouse Units", "value": f"{wh_units:,}", "icon": "\U0001F3E0"},
            {"label": "SKUs In Stock", "value": f"{len(wh):,}", "icon": "\u2705"},
            {"label": "SKUs Only At Outlets", "value": f"{only_outlet:,}", "icon": "\U0001F3EC"},
        ]
    )

    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("#### \U0001F3E0 Top Warehouse Stock")
        if wh.empty:
            st.info("Warehouse has no stock in this report.")
        else:
            top = wh.head(20).copy()
            top["Label"] = top["Product"].astype(str)
            if "Size" in top.columns:
                top["Label"] = top["Product"].astype(str) + " - " + top["Size"].astype(str)
            fig = px.bar(
                top.sort_values("Warehouse", ascending=True),
                x="Warehouse",
                y="Label",
                orientation="h",
                color="Warehouse",
                color_continuous_scale="Tealgrn",
                labels={"Warehouse": "Units", "Label": ""},
            )
            fig.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                showlegend=False,
                coloraxis_showscale=False,
                height=520,
                yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("#### \u26A0\uFE0F Zero-Warehouse (Stock Only At Outlets)")
        st.caption(
            "Web orders ship only after a transfer back to the warehouse - review these for transfer or de-listing."
        )
        zero_wh = pivot_df[(pivot_df["Warehouse"] <= 0) & (pivot_df["Total"] > 0)].sort_values(
            "Total", ascending=False
        )
        st.dataframe(
            zero_wh[["Product", "Size", "SKU", "Total"]]
            if not zero_wh.empty
            else pd.DataFrame(columns=["Product", "Size", "SKU", "Total"]),
            use_container_width=True,
            hide_index=True,
            height=520,
        )


def _sip_outlet_view(pivot_df: pd.DataFrame, outlets: list) -> None:
    """Outlet lens: distribution across branches with a compare chart."""
    outlet_cols = [c for c in outlets if c != "Warehouse"]
    if not outlet_cols:
        st.info("No outlet (non-warehouse) columns in this stock report.")
        return

    outlet_totals = (
        pivot_df[outlet_cols].sum().sort_values(ascending=False).reset_index()
    )
    outlet_totals.columns = ["Outlet", "Units"]
    active = outlet_totals[outlet_totals["Units"] > 0]

    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("#### \U0001F3EA Units by Outlet")
        if active.empty:
            st.info("No units recorded in any outlet.")
        else:
            fig = px.pie(
                active,
                names="Outlet",
                values="Units",
                hole=0.55,
                color_discrete_sequence=px.colors.qualitative.Plotly,
            )
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340)
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(outlet_totals, use_container_width=True, hide_index=True)

    with c2:
        st.markdown("#### \U0001F7EA Outlet Comparison")
        selected = st.pills(
            "Compare outlets",
            options=outlet_cols,
            default=outlet_cols[:4],
            selection_mode="multi",
            key="sip_outlet_compare",
        )
        if not selected:
            st.info("Select outlets to compare.")
        else:
            comp = pivot_df.groupby("Product")[selected].sum().reset_index()
            comp = comp[comp[selected].sum(axis=1) > 0]
            comp["Total"] = comp[selected].sum(axis=1)
            comp = comp.sort_values("Total", ascending=False).head(15)
            if comp.empty:
                st.info("No stock in the selected outlets.")
            else:
                fig = px.bar(
                    comp,
                    x="Total",
                    y="Product",
                    color_discrete_sequence=["#6366f1"],
                    orientation="h",
                    labels={"Total": "Units (selected outlets)", "Product": ""},
                )
                fig.update_layout(
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=False,
                    height=460,
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Top 15 products by units across the selected outlets.")


def render_sip_live_stock_tab():
    """SIP Stock tab: upload the plugin's Current Stock Report (CSV/Excel)
    or, once deployed, pull the same data live from the REST endpoint."""
    from src.services.woocommerce.outlet_stock import (
        SIP_STOCK_ENDPOINT,
        fetch_live_sip_stock,
    )

    st.markdown("### \U0001F4E1 SIP Stock - Smart Inventory with POS")
    st.caption(
        "Upload the plugin's **Current Stock Report** export, or pull the same data "
        f"live from `{SIP_STOCK_ENDPOINT}` once the endpoint is deployed."
    )

    uploaded = st.file_uploader(
        "\U0001F4E4 Upload Current Stock Report (.csv / .xlsx)",
        type=["csv", "xlsx"],
        key="sip_stock_report_upload",
    )

    report_df = None
    source_label = ""
    if uploaded is not None:
        try:
            raw = (
                pd.read_csv(uploaded)
                if uploaded.name.lower().endswith(".csv")
                else pd.read_excel(uploaded)
            )
            report_df = parse_stock_report(raw)
            source_label = uploaded.name
            st.session_state["sip_report_df"] = report_df
            st.session_state["sip_report_source"] = source_label
            st.success(
                f"Loaded {len(report_df):,} stock rows across "
                f"{report_df['Outlet'].nunique()} outlets from {uploaded.name}."
            )
        except Exception as e:
            st.error(f"Failed to parse stock report: {e}")
            return
    else:
        cached = st.session_state.get("sip_report_df")
        if cached is not None and not cached.empty:
            report_df = cached
            source_label = st.session_state.get("sip_report_source", "previous upload")
        else:
            try:
                live_df = fetch_live_sip_stock()
            except Exception:
                live_df = None
            if live_df is not None and not live_df.empty:
                # Live endpoint returns a pivoted frame; melt back to long form
                id_cols = [c for c in ["SKU", "Product", "Size"] if c in live_df.columns]
                outlet_cols = [c for c in live_df.columns if c not in id_cols]
                report_df = live_df.melt(
                    id_vars=id_cols,
                    value_vars=outlet_cols,
                    var_name="Outlet",
                    value_name="Stock Qty",
                )
                source_label = "live REST endpoint"
            else:
                st.info(
                    "**No stock report uploaded and the SIP endpoint is not live yet.**\n\n"
                    "Export the **Current Stock Report** from Smart Inventory with POS "
                    "and upload it above - expected columns:\n\n"
                    "`Product, Size, SKU, Outlet, Stock Qty, Price, Last Updated`\n\n"
                    "Once `GET /wp-json/wc/v3/sip/outlet-stock` is deployed, this tab "
                    "also fills automatically."
                )
                return

    if report_df is None or report_df.empty:
        st.warning("The stock report contains no usable rows.")
        return

    pivot_df = pivot_stock_report(report_df)
    outlets = [
        c
        for c in pivot_df.columns
        if c not in ("Product", "Size", "SKU", "Total")
    ]

    _sip_kpi_strip(pivot_df, source_label)

    st.divider()
    view_warehouse, view_outlets, view_grid = st.tabs(
        [
            ":material/warehouse: Warehouse View",
            ":material/storefront: Outlets View",
            ":material/table_rows: Stock Grid",
        ]
    )

    with view_warehouse:
        _sip_warehouse_view(pivot_df)

    with view_outlets:
        _sip_outlet_view(pivot_df, outlets)

    with view_grid:
        st.markdown("#### \U0001F50D Granular SIP Stock Grid")
        lc, sc = st.columns([1, 3])
        with lc:
            sel_outlet = st.multiselect(
                "Filter by Outlet",
                outlets,
                placeholder="All Outlets",
                key="sip_grid_outlet_filter",
            )
        with sc:
            search = st.text_input(
                "Search Product or SKU", "", key="sip_grid_search"
            )

        grid_df = pivot_df.copy()
        if sel_outlet:
            keep = ["Product", "Size", "SKU"] + sel_outlet + ["Total"]
            grid_df = grid_df[[c for c in keep if c in grid_df.columns]]
        if search:
            q = search.lower()
            mask = grid_df["Product"].astype(str).str.lower().str.contains(q)
            if "SKU" in grid_df.columns:
                mask = mask | grid_df["SKU"].astype(str).str.lower().str.contains(q)
            grid_df = grid_df[mask]

        if grid_df.empty:
            st.info("No SIP stock rows match the current filters.")
            return

        num_cols = [c for c in grid_df.columns if c not in ("Product", "Size", "SKU")]
        styled = grid_df.style.format(
            {c: "{:,.0f}" for c in num_cols if c in grid_df.columns}
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

    st.divider()
    export_data = {
        "SIP Pivot": pivot_df,
        "SIP Report (deduped)": report_df,
    }
    try:
        excel_bytes = export_to_styled_excel(export_data)
    except Exception:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            export_data["SIP Pivot"].to_excel(
                writer, sheet_name="SIP Pivot", index=False
            )
            export_data["SIP Report (deduped)"].to_excel(
                writer, sheet_name="SIP Report (deduped)", index=False
            )
        excel_bytes = output.getvalue()

    st.download_button(
        label="\U0001F4BE Download SIP Stock Report (Excel)",
        data=excel_bytes,
        file_name=f"DEEN_SIP_Stock_{bd_today().strftime('%Y%m%d')}.xlsx",
        type="primary",
        use_container_width=True,
        key="sip_stock_report_download",
    )


# Main entry
# ---------------------------------------------------------------------------


def render_stock_analytics_tab():
    """Renders the redesigned Current Stock Analytics interface."""
    # Initialize session state for outlet stock report
    if "outlet_stock_report_excel" not in st.session_state:
        st.session_state.outlet_stock_report_excel = None
    if "outlet_stock_mapping_df" not in st.session_state:
        st.session_state.outlet_stock_mapping_df = None
    if "outlet_stock_summary_df" not in st.session_state:
        st.session_state.outlet_stock_summary_df = None
    if "outlet_sku_verification_df" not in st.session_state:
        st.session_state.outlet_sku_verification_df = None

    render_premium_header(
        "Current Stock Analytics",
        "Monitor and analyze inventory across all locations and WooCommerce",
        "📦",
    )

    # ── Section 1: WooCommerce Stock ────────────────────────────────────────
    st.markdown("## 🗄️ WooCommerce Stock")
    safe_render(
        render_woocommerce_stock_tab,
        fallback_msg="WooCommerce stock tab unavailable.",
    )

    # ── Section 2: Outlet Stock Analysis ───────────────────────────────────
    st.divider()
    st.markdown("## 🏪 Outlet Stock Analysis")
    safe_render(
        render_outlet_stock_analysis_tab,
        fallback_msg="Outlet stock tab unavailable.",
    )

    # ── Section 3: SIP Live Stock ───────────────────────────────────────────
    st.divider()
    st.markdown("## 📡 SIP Live Stock")
    safe_render(
        render_sip_live_stock_tab,
        fallback_msg="SIP live stock tab unavailable.",
    )
