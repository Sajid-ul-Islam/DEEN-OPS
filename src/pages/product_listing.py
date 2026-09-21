"""Product Listing & Excel Merger Page.

Aggregates item quantities from raw WooCommerce orders or Excel uploads,
maps live multi-outlet stock, applies pastel SKU color distinctions,
and generates warehouse-ready styled Excel picking lists.
"""

from __future__ import annotations

import colorsys

import pandas as pd
import streamlit as st

from src.components.ui.ui_components import render_premium_header
from src.config.constants import bd_now, bd_today
from src.processing.data_processing import aggregate_product_listing
from src.processing.column_detection import (
    DATE_COL_CANDIDATES,
    ITEM_NAME_COL_CANDIDATES,
    ORDER_ID_COL_CANDIDATES,
    QTY_COL_CANDIDATES,
    SKU_COL_CANDIDATES,
    detect_column,
    find_columns,
)
from src.services.exports.excel_exporter import export_to_styled_excel
from src.utils.safe_ops import safe_render


def _render_product_listing_content() -> None:
    render_premium_header(
        "Product Listing & SKU Aggregator",
        "Merge orders by SKU/Item, compare outlet stock, and export styled picking lists",
        "📋",
    )

    c_source, c_sync = st.columns([3, 1])
    with c_source:
        source_mode = st.radio(
            "Select Data Source:",
            ["⚡ Live WooCommerce Orders", "📁 Upload Order File (CSV/Excel)"],
            horizontal=True,
            key="pl_source_mode",
        )

    df: pd.DataFrame | None = None

    if source_mode == "⚡ Live WooCommerce Orders":
        wc_df = st.session_state.get("wc_full_df")
        if wc_df is None or wc_df.empty:
            wc_df = st.session_state.get("wc_curr_df")
        if wc_df is None or wc_df.empty:
            wc_df = st.session_state.get("wc_tracking_df")

        if wc_df is not None and not wc_df.empty:
            df = wc_df.copy()
            st.info(f"Loaded **{len(df):,}** order rows from live WooCommerce sync.")
        else:
            st.warning(
                "⚠️ No live order data found in memory. Please fetch orders from the Live Dashboard or upload a file."
            )
    else:
        uploaded_file = st.file_uploader(
            "Upload Order File (CSV or Excel)",
            type=["csv", "xlsx", "xls"],
            key="pl_file_uploader",
        )
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                st.success(f"Uploaded **{len(df):,}** rows successfully.")
            except Exception as e:
                st.error(f"Error reading uploaded file: {e}")

    if df is None or df.empty:
        return

    # Auto-detect relevant columns: first try to get the actual column matching known schema,
    # then fallback to smart partial detection, then defaults.
    cols = df.columns.tolist()
    det = find_columns(df)

    detected_item = (
        detect_column(df, ITEM_NAME_COL_CANDIDATES)
        or det.get("item")
        or det.get("name")
    )
    detected_sku = detect_column(df, SKU_COL_CANDIDATES) or det.get("sku")
    detected_qty = detect_column(df, QTY_COL_CANDIDATES) or det.get("qty")
    detected_order = detect_column(df, ORDER_ID_COL_CANDIDATES) or det.get("order_id")
    detected_date = detect_column(df, DATE_COL_CANDIDATES) or det.get("date")

    item_index = (
        cols.index(detected_item) if (detected_item and detected_item in cols) else 0
    )
    sku_index = (
        (cols.index(detected_sku) + 1) if (detected_sku and detected_sku in cols) else 0
    )
    qty_index = (
        cols.index(detected_qty) if (detected_qty and detected_qty in cols) else 0
    )
    order_index = (
        (cols.index(detected_order) + 1)
        if (detected_order and detected_order in cols)
        else 0
    )
    date_index = (
        (cols.index(detected_date) + 1)
        if (detected_date and detected_date in cols)
        else 0
    )

    # Ensure cached widget state doesn't point to non-existent columns from a previous file
    for key, valid_options, default_val in [
        ("pl_item_col", cols, cols[item_index] if cols else None),
        (
            "pl_sku_col",
            ["None"] + cols,
            (["None"] + cols)[sku_index] if cols else "None",
        ),
        ("pl_qty_col", cols, cols[qty_index] if cols else None),
        (
            "pl_order_col",
            ["None"] + cols,
            (["None"] + cols)[order_index] if cols else "None",
        ),
        (
            "pl_date_col",
            ["None"] + cols,
            (["None"] + cols)[date_index] if cols else "None",
        ),
    ]:
        if key in st.session_state and st.session_state[key] not in valid_options:
            st.session_state[key] = default_val

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        item_col = st.selectbox(
            "Item Name Column:",
            cols,
            index=item_index,
            key="pl_item_col",
        )
    with c2:
        sku_col = st.selectbox(
            "SKU Column (Optional):",
            ["None"] + cols,
            index=sku_index,
            key="pl_sku_col",
        )
    with c3:
        qty_col = st.selectbox(
            "Quantity Column:",
            cols,
            index=qty_index,
            key="pl_qty_col",
        )
    with c4:
        order_col = st.selectbox(
            "Order ID Column (Optional):",
            ["None"] + cols,
            index=order_index,
            key="pl_order_col",
        )
    with c5:
        date_col = st.selectbox(
            "Date Column (Optional):",
            ["None"] + cols,
            index=date_index,
            key="pl_date_col",
        )

    # Optional Outlet Filtering if SIP / Outlet data is present
    has_sip = "SIP" in df.columns or "Item Outlet" in df.columns
    if has_sip:
        from src.processing.sip_outlet_processor import process_order_item_outlets

        actual_order_col = (
            order_col
            if (order_col != "None" and order_col in df.columns)
            else ("Order Number" if "Order Number" in df.columns else df.columns[0])
        )
        if "Item Outlet" not in df.columns and "SIP" in df.columns:
            df = process_order_item_outlets(
                df,
                order_col=actual_order_col,
                sip_col="SIP",
            )

        if "Item Outlet" in df.columns:
            unique_outlets = [
                o for o in df["Item Outlet"].dropna().unique() if o != "Warehouse"
            ]
            outlet_opts = [
                "🏭 Warehouse Only (Recommended)",
                "🌐 All Outlets",
            ] + unique_outlets
            chosen_outlet = st.selectbox(
                "Filter Product Listing by Outlet:",
                outlet_opts,
                index=0,
                key="pl_outlet_filter_choice",
                help="Filters picking list to items fulfilled by the selected outlet.",
            )
            if chosen_outlet == "🏭 Warehouse Only (Recommended)":
                df = df[df["Item Outlet"] == "Warehouse"]
            elif chosen_outlet != "🌐 All Outlets":
                df = df[df["Item Outlet"] == chosen_outlet]

    # Grouping & Aggregation: sorted first item-wise, then SKU-wise
    merged_df = aggregate_product_listing(
        df,
        item_col=item_col,
        qty_col=qty_col,
        sku_col=sku_col if sku_col != "None" else None,
    )

    tot_units = int(merged_df[qty_col].sum()) if not merged_df.empty else 0
    tot_skus = len(merged_df)
    unique_orders = (
        df[order_col].nunique()
        if (order_col != "None" and order_col in df.columns)
        else len(df)
    )

    # Resolve Date
    date_val = None
    resolved_date_col = (
        date_col if (date_col != "None" and date_col in df.columns) else detected_date
    )
    if resolved_date_col and resolved_date_col in df.columns:
        dt_series = pd.to_datetime(df[resolved_date_col], errors="coerce").dropna()
        if not dt_series.empty:
            date_val = dt_series.max().strftime("%d %b %Y")
        else:
            first_valid = df[resolved_date_col].dropna()
            if not first_valid.empty:
                date_val = str(first_valid.iloc[-1])[:10]

    if not date_val:
        date_val = bd_today().strftime("%d %b %Y")

    # Resolve Last Order Number
    last_order_num = "—"
    if order_col != "None" and order_col in df.columns:
        valid_orders = df.dropna(subset=[order_col])
        if not valid_orders.empty:
            if resolved_date_col and resolved_date_col in valid_orders.columns:
                try:
                    sorted_df = valid_orders.sort_values(
                        by=resolved_date_col, ascending=False
                    )
                    last_order_num = str(sorted_df[order_col].iloc[0])
                except Exception:
                    last_order_num = str(valid_orders[order_col].iloc[-1])
            else:
                try:
                    num_ids = pd.to_numeric(valid_orders[order_col], errors="coerce")
                    if num_ids.notna().any():
                        last_order_num = str(int(num_ids.max()))
                    else:
                        last_order_num = str(valid_orders[order_col].iloc[-1])
                except Exception:
                    last_order_num = str(valid_orders[order_col].iloc[-1])

    last_order_display = (
        f"#{last_order_num}"
        if (last_order_num != "—" and not str(last_order_num).startswith("#"))
        else str(last_order_num)
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📦 Total Required Units", f"{tot_units:,}")
    m2.metric("🏷️ Unique SKUs / Products", f"{tot_skus:,}")
    m3.metric(
        "🛒 Total Orders",
        f"{unique_orders:,}"
        if isinstance(unique_orders, (int, float))
        else f"{unique_orders}",
    )
    m4.metric("📋 Last Order & Date", f"{last_order_display} · {date_val}")

    st.divider()

    # Construct the summary last row
    orders_label = (
        f"{unique_orders:,} Orders"
        if isinstance(unique_orders, (int, float))
        else f"{unique_orders}"
    )
    summary_row = {}
    if sku_col != "None" and sku_col in merged_df.columns:
        summary_row[item_col] = (
            f"TOTAL: {orders_label} | Last Order: {last_order_display}"
        )
        summary_row[sku_col] = f"Date: {date_val}"
    else:
        summary_row[item_col] = (
            f"TOTAL: {orders_label} | Last Order: {last_order_display} | Date: {date_val}"
        )
    summary_row[qty_col] = tot_units

    display_df = (
        pd.concat([merged_df, pd.DataFrame([summary_row])], ignore_index=True)
        if not merged_df.empty
        else merged_df
    )

    # Style table with pastel group coloring
    def _apply_pastel_colors(data_df):
        styles = pd.DataFrame("", index=data_df.index, columns=data_df.columns)
        color_col = (
            item_col
            if item_col in data_df.columns
            else (sku_col if sku_col != "None" else None)
        )
        if not color_col:
            return styles
        content_df = data_df.iloc[:-1] if len(data_df) > 1 else data_df
        unique_vals = content_df[color_col].unique()

        color_dict = {}
        for i, val in enumerate(unique_vals):
            hue = (i * 0.618033988749895) % 1.0
            rgb = colorsys.hls_to_rgb(hue, 0.94, 0.45)
            color_dict[val] = "#%02x%02x%02x" % (
                int(rgb[0] * 255),
                int(rgb[1] * 255),
                int(rgb[2] * 255),
            )

        for idx, row in content_df.iterrows():
            val = row[color_col]
            hex_c = color_dict.get(val, "#ffffff")
            styles.loc[idx, :] = (
                f"background-color: {hex_c}; color: #0f172a; font-weight: 500;"
            )

        # Highlight the last summary row
        if len(data_df) > 0:
            last_idx = data_df.index[-1]
            styles.loc[last_idx, :] = (
                "background-color: #e2e8f0; color: #0f172a; font-weight: 800; border-top: 2px solid #475569;"
            )
        return styles

    st.markdown("### 📋 Aggregated Product Picking List")
    st.dataframe(
        display_df.style.apply(_apply_pastel_colors, axis=None),
        use_container_width=True,
        height=min(600, max(300, len(display_df) * 35 + 40)),
        column_config={
            qty_col: st.column_config.NumberColumn("📦 Total Quantity", format="%d"),
            item_col: st.column_config.TextColumn("🛍️ Item Name"),
        },
    )

    # Export to styled Excel
    export_col = (
        item_col
        if item_col in display_df.columns
        else (sku_col if sku_col != "None" else None)
    )
    excel_bytes = export_to_styled_excel(
        {"Product Listing": display_df},
        group_by_col=export_col,
    )

    st.download_button(
        label="📥 Download Styled Product Listing (Excel)",
        data=excel_bytes,
        file_name=f"Product_Listing_{bd_now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )


def render_product_listing_tab() -> None:
    """Public router entry point for Product Listing page."""
    safe_render(
        _render_product_listing_content, fallback_msg="Product Listing unavailable."
    )
