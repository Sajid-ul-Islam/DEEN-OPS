"""Product Listing & Warehouse Picking Workspace.

Provides automated item and SKU aggregation, warehouse picking metrics,
pastel group styling, and styled Excel exports for WooCommerce orders.
"""

from __future__ import annotations

import colorsys

import pandas as pd
import streamlit as st

from src.components.ui.ui_components import render_premium_header
from src.config.constants import bd_now, bd_today
from src.processing.orders.product_aggregator import aggregate_product_listing
from src.services.exports.excel_exporter import export_to_styled_excel
from src.utils.file_io import read_uploaded


def _detect_column(cols: list[str], candidates: list[str], default_idx: int = 0) -> int:
    """Find the best match column index from candidates (case-insensitive substring)."""
    for cand in candidates:
        for idx, col in enumerate(cols):
            if cand.lower() in col.lower():
                return idx
    return default_idx


def render_product_listing_tab() -> None:
    """Render the Product Listing & Warehouse Picking workspace."""
    render_premium_header(
        title="Product Listing & Picking List",
        subtitle="Aggregate orders by Item Name and SKU variant for warehouse picking and dispatch.",
        icon="📋",
    )

    df = None
    data_source = st.radio(
        "Select Data Source:",
        ["Live WooCommerce Session", "Upload Excel / CSV File"],
        horizontal=True,
        key="pl_data_source",
    )

    if data_source == "Live WooCommerce Session":
        # Check active session dataframe
        live_df = st.session_state.get("wc_curr_df")
        if live_df is None or live_df.empty:
            live_df = st.session_state.get("wc_full_df")

        if live_df is not None and not live_df.empty:
            df = live_df.copy()
            st.info(
                f"Using active WooCommerce session data ({len(df):,} items loaded)."
            )
        else:
            st.warning("⚠️ No active WooCommerce order session found in memory.")
    else:
        uploaded_file = st.file_uploader(
            "Upload Orders Export (Excel or CSV):",
            type=["xlsx", "xls", "csv"],
            key="pl_file_uploader",
        )
        if uploaded_file is not None:
            try:
                df = read_uploaded(uploaded_file)
                st.success(f"Uploaded **{len(df):,}** rows successfully.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    if df is None or df.empty:
        st.info("💡 Upload an order file or sync live WooCommerce data to proceed.")
        return

    cols = df.columns.tolist()
    if not cols:
        st.error("Uploaded file has no columns.")
        return

    # Auto-detect best column matches
    name_candidates = [
        "Product Name",
        "Item Name",
        "Name",
        "Product",
        "Title",
        "item_name",
    ]
    qty_candidates = ["Quantity", "Qty", "quantity", "qty", "Units", "Count"]
    sku_candidates = ["SKU", "sku", "Item SKU", "Product SKU", "Code"]
    order_candidates = [
        "Order ID",
        "Order Number",
        "Order #",
        "order_id",
        "ID",
        "Order",
    ]
    date_candidates = [
        "Order Date",
        "Date",
        "Order Date Modified",
        "Created At",
        "date",
    ]

    item_idx = _detect_column(cols, name_candidates, 0)
    qty_idx = _detect_column(cols, qty_candidates, 0)
    sku_idx = _detect_column(cols, sku_candidates, 0)
    order_idx = _detect_column(cols, order_candidates, 0)
    date_idx = _detect_column(cols, date_candidates, 0)

    # Column configuration selectors
    with st.expander("⚙️ Column Configuration", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            item_col = st.selectbox(
                "Item Name Column:",
                cols,
                index=item_idx,
                key="pl_item_col",
            )
        with c2:
            qty_col = st.selectbox(
                "Quantity Column:",
                cols,
                index=qty_idx,
                key="pl_qty_col",
            )
        with c3:
            sku_options = ["None"] + cols
            sku_default = cols[sku_idx] if cols[sku_idx] in sku_options else "None"
            sku_col = st.selectbox(
                "SKU Column (Optional):",
                sku_options,
                index=sku_options.index(sku_default),
                key="pl_sku_col",
            )
        with c4:
            order_options = ["None"] + cols
            order_default = (
                cols[order_idx] if cols[order_idx] in order_options else "None"
            )
            order_col = st.selectbox(
                "Order ID Column:",
                order_options,
                index=order_options.index(order_default),
                key="pl_order_col",
            )
        with c5:
            date_options = ["None"] + cols
            date_default = cols[date_idx] if cols[date_idx] in date_options else "None"
            date_col = st.selectbox(
                "Date Column (Optional):",
                date_options,
                index=date_options.index(date_default),
                key="pl_date_col",
            )

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
    if date_col != "None" and date_col in df.columns:
        dt_series = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not dt_series.empty:
            date_val = dt_series.max().strftime("%d %b %Y")
        else:
            first_valid = df[date_col].dropna()
            if not first_valid.empty:
                date_val = str(first_valid.iloc[-1])[:10]

    if not date_val:
        date_val = bd_today().strftime("%d %b %Y")

    # Resolve Last Order Number
    last_order_num = "—"
    if order_col != "None" and order_col in df.columns:
        valid_orders = df.dropna(subset=[order_col])
        if not valid_orders.empty:
            if date_col != "None" and date_col in valid_orders.columns:
                try:
                    sorted_df = valid_orders.sort_values(by=date_col, ascending=False)
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
    def _apply_pastel_colors(data_df: pd.DataFrame) -> pd.DataFrame:
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
                "background-color: #e2e8f0; color: #0f172a; "
                "font-weight: 800; border-top: 2px solid #475569;"
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
