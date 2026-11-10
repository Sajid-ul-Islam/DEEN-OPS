"""Multi-Outlet and Warehouse Stock Inventory UI Component.

Renders high-level inventory metrics, multi-outlet stock matrix (Warehouse, Mirpur,
Wari, Cumilla, Sylhet), stock health alerts, branch replenishment filtering,
and multi-sheet Excel/CSV downloads.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config.constants import bd_now
from src.processing.stock_analytics import (
    CANONICAL_OUTLETS,
    build_stock_pivot_from_flat,
    compute_stock_kpis,
    ensure_stock_pivot_structure,
    filter_stock_inventory,
    load_cached_stock_inventory,
    save_cached_stock_inventory,
)
from src.services.exports.excel_exporter import export_to_styled_excel
from src.utils.file_io import read_uploaded


def export_stock_inventory_to_excel(pivot_df: pd.DataFrame) -> bytes:
    """Generate a formatted multi-sheet Excel file (.xlsx) with stock pivot and individual sheets."""
    if pivot_df is None or pivot_df.empty:
        return b""

    sheets: dict[str, pd.DataFrame] = {}

    # Sheet 1: All Stock Pivot
    sheets["All_Stock_Pivot"] = pivot_df

    # Sheet 2: Low Stock Alerts (items needing restocking)
    if "Total" in pivot_df.columns:
        low_stock_df = pivot_df[pivot_df["Total"] <= 5].copy()
        if not low_stock_df.empty:
            sheets["Low_Stock_Alerts"] = low_stock_df

    # Sheets 3+: Individual Outlets
    index_cols = ["Product", "Size", "SKU", "Category"]
    outlet_cols = [
        c
        for c in pivot_df.columns
        if c not in index_cols and c not in ("Total", "Status")
    ]

    for out_name in outlet_cols:
        sheet_key = f"Stock_{out_name}"[:31]
        out_slice = pivot_df[index_cols + [out_name]].copy()
        out_slice = out_slice.rename(columns={out_name: "Stock Quantity"})
        sheets[sheet_key] = out_slice[out_slice["Stock Quantity"] > 0]

    return export_to_styled_excel(sheets, group_by_col="Product")


def render_outlet_stock_view() -> None:
    """Render the full interactive Multi-Outlet & Warehouse Inventory matrix and export system."""
    st.markdown("### 🏬 Warehouse & Multi-Outlet Stock Inventory")
    st.caption(
        "Monitor stock levels across Central Warehouse and retail outlets (Mirpur, Wari, Cumilla, Sylhet), "
        "detect stockouts, identify branch replenishment needs, and export formatted reports."
    )

    # ── Initialize or load cached stock data ──────────────────────────────────
    if "outlet_stock_df" not in st.session_state:
        cached_df = load_cached_stock_inventory()
        st.session_state["outlet_stock_df"] = (
            cached_df if cached_df is not None else pd.DataFrame()
        )

    pivot_df: pd.DataFrame = st.session_state["outlet_stock_df"]

    # ── Action Bar: Upload, Sync, and Reset ────────────────────────────────────
    with st.expander(
        "📥 Import, Sync & Update Stock Inventory", expanded=pivot_df.empty
    ):
        c_up1, c_up2 = st.columns([2, 1.5])
        with c_up1:
            uploaded_stock_file = st.file_uploader(
                "Upload Smart Inventory / POS Stock Report (CSV or Excel):",
                type=["csv", "xlsx", "xls"],
                key="stock_report_uploader",
                help="Accepts 'Current Stock Report' from Smart Inventory with POS or flat stock exports",
            )
            if uploaded_stock_file is not None:
                try:
                    raw_df = read_uploaded(uploaded_stock_file)
                    new_pivot = build_stock_pivot_from_flat(raw_df)
                    if not new_pivot.empty:
                        st.session_state["outlet_stock_df"] = new_pivot
                        save_cached_stock_inventory(new_pivot)
                        st.success(
                            f"✅ Successfully imported **{len(new_pivot):,}** product variations!"
                        )
                        st.rerun()
                    else:
                        st.error(
                            "Failed to parse stock report. Please check file format."
                        )
                except Exception as e:
                    st.error(f"Error processing stock file: {e}")

        with c_up2:
            st.markdown("##### ⚡ Quick Sync & Actions")
            if st.button(
                "🔄 Sync Live WooCommerce Catalog",
                use_container_width=True,
                type="secondary",
            ):
                with st.spinner(
                    "Fetching live product stock from WooCommerce REST API..."
                ):
                    from src.services.woocommerce.stock_service import (
                        fetch_live_woocommerce_stock,
                    )

                    live_df = fetch_live_woocommerce_stock(max_pages=5)
                    if not live_df.empty:
                        merged_pivot = build_stock_pivot_from_flat(live_df)
                        # If existing pivot had outlet data, merge Warehouse stock
                        if not pivot_df.empty and "Mirpur" in pivot_df.columns:
                            for out in [
                                o for o in CANONICAL_OUTLETS if o != "Warehouse"
                            ]:
                                if out in pivot_df.columns:
                                    merged_pivot[out] = pivot_df[out]
                            merged_pivot = ensure_stock_pivot_structure(merged_pivot)

                        st.session_state["outlet_stock_df"] = merged_pivot
                        save_cached_stock_inventory(merged_pivot)
                        st.success(
                            f"⚡ Synced **{len(merged_pivot):,}** items from WooCommerce!"
                        )
                        st.rerun()
                    else:
                        st.warning("No items retrieved from WooCommerce REST API.")

            if not pivot_df.empty and st.button(
                "💾 Persist Current Snapshot", use_container_width=True
            ):
                if save_cached_stock_inventory(pivot_df):
                    st.toast("💾 Stock inventory saved to disk!")
                else:
                    st.error("Failed to save stock inventory.")

    if pivot_df.empty:
        st.info(
            "ℹ️ No stock inventory loaded. Upload a stock report above or sync from WooCommerce to begin."
        )
        return

    # ── Summary KPI Cards ─────────────────────────────────────────────────────
    kpis = compute_stock_kpis(pivot_df)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("📦 Total SKUs", f"{kpis['total_skus']:,}")
    m2.metric("🏢 Total Stock", f"{kpis['total_stock']:,} pcs")
    m3.metric("🏭 Warehouse", f"{kpis['warehouse_stock']:,} pcs")
    m4.metric("🏬 Retail Outlets", f"{kpis['outlets_stock']:,} pcs")
    m5.metric("🟡 Low Stock (≤5)", f"{kpis['low_stock_count']:,}")
    m6.metric("⚠️ Out of Stock", f"{kpis['out_of_stock_count']:,}")

    # Sub-breakdown of outlet stock
    ob = kpis.get("outlet_breakdown", {})
    if len(ob) > 1:
        st.caption(
            "🏬 **Outlet Stock Breakdown:** "
            + " · ".join([f"**{out}**: {qty:,}" for out, qty in ob.items()])
        )

    st.divider()

    # ── Filters Toolbar ───────────────────────────────────────────────────────
    f_col1, f_col2, f_col3, f_col4 = st.columns([1.5, 1.8, 1.8, 2.5])

    # Available Outlets
    index_cols = {"Product", "Size", "SKU", "Category", "Total", "Status"}
    data_outlets = [c for c in pivot_df.columns if c not in index_cols]
    outlet_options = ["All Outlets"] + data_outlets

    with f_col1:
        selected_outlet = st.selectbox(
            "📍 Focus Outlet",
            options=outlet_options,
            index=0,
            key="stock_view_outlet_select",
        )

    with f_col2:
        status_options = [
            "All",
            "In Stock",
            "Low Stock",
            "Out of Stock",
            "Replenish Needed",
        ]
        selected_status = st.selectbox(
            "📊 Stock Health",
            options=status_options,
            index=0,
            key="stock_view_status_select",
            help="'Replenish Needed' finds items available at Warehouse but out-of-stock at retail outlets",
        )

    with f_col3:
        categories = ["All Categories"]
        if "Category" in pivot_df.columns:
            cats = sorted(
                [c for c in pivot_df["Category"].dropna().unique() if str(c).strip()]
            )
            categories.extend(cats)
        selected_cat = st.selectbox(
            "🏷️ Category",
            options=categories,
            index=0,
            key="stock_view_category_select",
        )

    with f_col4:
        search_query = st.text_input(
            "🔍 Search Product, SKU, or Size",
            value="",
            placeholder="e.g. Panjabi, 101-0100, XL",
            key="stock_view_search_input",
        ).strip()

    # ── Filter DataFrame ──────────────────────────────────────────────────────
    filtered_df = filter_stock_inventory(
        df=pivot_df,
        outlet=selected_outlet,
        stock_status=selected_status,
        category=selected_cat,
        search_query=search_query,
    )

    st.caption(
        f"Showing **{len(filtered_df):,}** of **{len(pivot_df):,}** variations matching filters."
    )

    # ── Column Configuration for Streamlit Dataframe ──────────────────────────
    col_config = {
        "Product": st.column_config.TextColumn("Product Name", width="medium"),
        "Size": st.column_config.TextColumn("Size", width="small"),
        "SKU": st.column_config.TextColumn("SKU", width="medium"),
        "Category": st.column_config.TextColumn("Category", width="small"),
        "Warehouse": st.column_config.NumberColumn("Warehouse", format="%d pcs"),
        "Mirpur": st.column_config.NumberColumn("Mirpur", format="%d pcs"),
        "Wari": st.column_config.NumberColumn("Wari", format="%d pcs"),
        "Cumilla": st.column_config.NumberColumn("Cumilla", format="%d pcs"),
        "Sylhet": st.column_config.NumberColumn("Sylhet", format="%d pcs"),
        "Total": st.column_config.NumberColumn("Total Stock", format="%d pcs"),
        "Status": st.column_config.TextColumn("Status", width="small"),
    }

    # Display interactive table
    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
    )

    # ── Export & Download Section ─────────────────────────────────────────────
    st.markdown("#### 📥 Export Stock Reports")
    now_tag = bd_now().strftime("%Y%m%d_%H%M")
    base_fn = f"DEEN_Stock_Inventory_{now_tag}"

    down_col1, down_col2 = st.columns(2)
    with down_col1:
        try:
            excel_bytes = export_stock_inventory_to_excel(filtered_df)
            st.download_button(
                label=f"⬇️ Download Multi-Sheet Excel (.xlsx) — {len(filtered_df):,} SKUs",
                data=excel_bytes,
                file_name=f"{base_fn}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
                key="download_stock_excel_btn",
            )
        except Exception as e:
            st.warning(f"Excel export unavailable: {e}")

    with down_col2:
        csv_bytes = filtered_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label=f"⬇️ Download Filtered CSV (.csv) — {len(filtered_df):,} SKUs",
            data=csv_bytes,
            file_name=f"{base_fn}.csv",
            mime="text/csv",
            type="secondary",
            use_container_width=True,
            key="download_stock_csv_btn",
        )
