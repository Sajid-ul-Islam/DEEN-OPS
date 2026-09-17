"""SIP Item-Wise Outlet Mapper Page (Tools Section).

Enables users to upload WooCommerce order exports with SIP outlet data,
automatically map item-wise dispatch locations, view split-order analytics,
and export an enriched Excel file with the 'Item Outlet' column.
"""

from __future__ import annotations

import colorsys
import os
from typing import Optional
import pandas as pd
import streamlit as st

from src.components.ui.ui_components import render_metric_grid, render_premium_header
from src.config.constants import bd_now, bd_today
from src.processing.sip_outlet_processor import (
    compute_sip_stats,
    generate_outlet_product_listing,
    generate_pathao_bulk_consignments,
    is_inside_dhaka,
    process_order_item_outlets,
)
from src.services.exports.excel_exporter import export_to_styled_excel
from src.utils.file_io import read_uploaded, to_excel_bytes


def _detect_col(df: pd.DataFrame, candidates: list[str], default_idx: int = 0) -> int:
    cols = df.columns.tolist()
    for cand in candidates:
        for i, col in enumerate(cols):
            if str(col).strip().lower() == cand.lower():
                return i
    for cand in candidates:
        for i, col in enumerate(cols):
            if cand.lower() in str(col).strip().lower():
                return i
    return default_idx if 0 <= default_idx < len(cols) else 0


def render_sip_outlet_tab() -> None:
    """Render the SIP Item-Wise Outlet Mapper page."""
    render_premium_header(
        "SIP Item-Wise Outlet Extractor",
        "Parse WooCommerce multi-outlet SIP data to map item-specific dispatch locations (Warehouse, Mirpur, Cumilla, Wari, Sylhet)",
        "🏬",
    )

    # 1. Data Source Selection
    c_source, c_sample = st.columns([3, 1])
    with c_source:
        source_opt = st.radio(
            "Select Data Source:",
            ["📁 Upload Order File (Excel/CSV)", "📋 Load Sample Input File", "⚡ Live WooCommerce Data"],
            horizontal=True,
            key="sip_source_opt",
        )

    df: Optional[pd.DataFrame] = None
    sample_file_path = "Product listing Sample input.xlsx"

    if source_opt == "📋 Load Sample Input File":
        if os.path.exists(sample_file_path):
            try:
                df = pd.read_excel(sample_file_path)
                st.success(f"Loaded **{len(df):,}** rows from `{sample_file_path}`.")
            except Exception as e:
                st.error(f"Error loading sample file: {e}")
        else:
            st.warning("Sample input file not found in root directory.")
    elif source_opt == "⚡ Live WooCommerce Data":
        wc_df = st.session_state.get("wc_full_df")
        if wc_df is None or wc_df.empty:
            wc_df = st.session_state.get("wc_curr_df")
        if wc_df is not None and not wc_df.empty:
            df = wc_df.copy()
            st.info(f"Loaded **{len(df):,}** order rows from live WooCommerce sync.")
        else:
            st.warning("No live order data in memory. Please sync orders or upload a file.")
    else:
        uploaded_file = st.file_uploader(
            "Upload Customer Order Spreadsheet (Excel or CSV)",
            type=["xlsx", "xls", "csv"],
            key="sip_file_uploader",
        )
        if uploaded_file is not None:
            try:
                df = read_uploaded(uploaded_file)
                st.success(f"Uploaded **{len(df):,}** rows successfully.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    if df is None or df.empty:
        st.info("💡 Upload an order file (or click 'Load Sample Input File') to extract item-wise outlets.")
        return

    cols = df.columns.tolist()

    # 2. Configuration & Column Mapping
    with st.expander("⚙️ Column & Extraction Settings", expanded=False):
        order_candidates = ["Order Number", "Order ID", "order_id", "ID", "Invoice Number"]
        sip_candidates = ["SIP", "sip", "SIP Stock", "Outlet SIP", "Outlet Stock"]

        def_order_idx = _detect_col(df, order_candidates, 0)
        def_sip_idx = _detect_col(df, sip_candidates, min(6, len(cols) - 1))

        c1, c2, c3 = st.columns(3)
        with c1:
            order_col = st.selectbox(
                "Order Identifier Column:",
                cols,
                index=def_order_idx,
                key="sip_order_col",
            )
        with c2:
            sip_col = st.selectbox(
                "SIP Routing JSON Column:",
                cols,
                index=def_sip_idx,
                key="sip_target_sip_col",
            )
        with c3:
            target_col_name = st.text_input(
                "New Column Name:",
                value="Item Outlet",
                key="sip_col_name",
            )

        canonical_toggle = st.checkbox(
            "Canonical Outlet Names (e.g. 'mirpur-12' -> 'Mirpur')",
            value=True,
            key="sip_canonical_toggle",
        )

    # 3. Process the DataFrame
    with st.spinner("Mapping item outlets..."):
        processed_df = process_order_item_outlets(
            df=df,
            order_col=order_col,
            sip_col=sip_col,
            target_col=target_col_name,
            canonical=canonical_toggle,
        )
        stats = compute_sip_stats(
            df=processed_df,
            order_col=order_col,
            outlet_col=target_col_name,
        )

    # 4. Display KPI Metrics
    metrics = [
        {"label": "Total Line Items", "value": f"{stats['total_items']:,}", "icon": "📦"},
        {"label": "Unique Orders", "value": f"{stats['total_orders']:,}", "icon": "🧾"},
        {"label": "Multi-Item Orders", "value": f"{stats['multi_item_orders']:,}", "icon": "🛍️"},
        {
            "label": "Split Outlet Orders",
            "value": f"{stats['split_orders_count']:,}",
            "icon": "🔀",
        },
    ]
    render_metric_grid(metrics)

    # 5. Outlet Breakdown Badges
    st.markdown("##### 📍 Outlet Allocation Summary")
    outlet_counts = stats.get("outlet_counts", {})
    if outlet_counts:
        cols_b = st.columns(min(len(outlet_counts), 5))
        for idx, (outlet, count) in enumerate(outlet_counts.items()):
            col_target = cols_b[idx % len(cols_b)]
            pct = (count / stats['total_items'] * 100) if stats['total_items'] else 0
            col_target.metric(label=outlet, value=f"{count:,} items", delta=f"{pct:.1f}%")

    # 6. Split Orders Warning Card
    if stats["split_orders_count"] > 0:
        with st.expander(
            f"⚠️ Split-Outlet Orders Detected ({stats['split_orders_count']} orders)",
            expanded=True,
        ):
            st.warning(
                "The following orders contain items dispatched from **multiple different outlets**. "
                "These orders will require split fulfillment or partial dispatch:"
            )
            split_rows = []
            for item in stats["split_orders"]:
                order_id = item["order_id"]
                sub = processed_df[processed_df[order_col] == order_id]
                item_names = sub.get("Item Name", sub.iloc[:, 1]).tolist() if "Item Name" in sub else []
                outlets = sub[target_col_name].tolist()
                items_detail = " | ".join([f"{name} ({out})" for name, out in zip(item_names, outlets)]) if item_names else item["summary"]
                split_rows.append({
                    "Order Number": order_id,
                    "Items Count": item["item_count"],
                    "Outlets": item["summary"],
                    "Details": items_detail,
                })
            st.dataframe(pd.DataFrame(split_rows), use_container_width=True, hide_index=True)

    # 7. Multi-View Tabs: Full Orders vs Warehouse Product Listing vs Pathao Bulk
    tab_full, tab_wh_listing, tab_pathao = st.tabs([
        "📋 Full Orders with Outlet Mapping",
        "🏭 Warehouse Product Listing (Picking List)",
        "🚚 Pathao Bulk Consignments",
    ])

    with tab_full:
        st.markdown(f"##### 📋 Order Line Items with '{target_col_name}' Column")

        c_filter, c_search = st.columns([2, 2])
        with c_filter:
            avail_outlets = ["All Outlets"] + list(outlet_counts.keys())
            selected_outlet = st.selectbox("Filter by Outlet:", avail_outlets, key="sip_outlet_filter")
        with c_search:
            search_query = st.text_input("Search Order or Item:", "", key="sip_search_query")

        display_df = processed_df.copy()
        if selected_outlet != "All Outlets":
            display_df = display_df[display_df[target_col_name] == selected_outlet]

        if search_query.strip():
            q = search_query.strip().lower()
            mask = display_df.astype(str).apply(lambda row: row.str.lower().str.contains(q, regex=False)).any(axis=1)
            display_df = display_df[mask]

        st.caption(f"Showing **{len(display_df):,}** of **{len(processed_df):,}** rows")
        st.dataframe(display_df, use_container_width=True)

        excel_bytes = to_excel_bytes(processed_df, sheet_name="Order_Item_Outlets")
        st.download_button(
            label=f"📥 Download Enriched Excel with '{target_col_name}'",
            data=excel_bytes,
            file_name="orders_with_item_outlets.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

    with tab_wh_listing:
        c_pick_out, c_item, c_sku, c_qty = st.columns([2, 2, 2, 1])
        with c_pick_out:
            listing_outlet_options = ["Warehouse"] + [o for o in outlet_counts.keys() if o != "Warehouse"] + ["All"]
            selected_listing_outlet = st.selectbox(
                "Select Outlet for Product Listing:",
                listing_outlet_options,
                index=0,
                key="sip_listing_outlet_choice",
            )
        with c_item:
            item_candidates = ["Item Name", "Product Name", "Item", "Product", "Title"]
            det_item_idx = _detect_col(processed_df, item_candidates, 0)
            pl_item_col = st.selectbox("Item Column:", cols, index=det_item_idx, key="sip_pl_item_col")
        with c_sku:
            sku_candidates = ["SKU", "sku", "Product SKU", "Variation SKU"]
            det_sku_idx = _detect_col(processed_df, sku_candidates, 0)
            sku_options = ["None"] + cols
            pl_sku_col = st.selectbox(
                "SKU Column:",
                sku_options,
                index=(sku_options.index(cols[det_sku_idx]) if cols[det_sku_idx] in sku_options else 0),
                key="sip_pl_sku_col",
            )
        with c_qty:
            qty_candidates = ["Quantity", "Qty", "Units", "Count"]
            det_qty_idx = _detect_col(processed_df, qty_candidates, 0)
            pl_qty_col = st.selectbox("Qty Column:", cols, index=det_qty_idx, key="sip_pl_qty_col")

        filtered_raw = (
            processed_df[processed_df[target_col_name] == selected_listing_outlet]
            if selected_listing_outlet != "All"
            else processed_df
        )

        outlet_listing_df = generate_outlet_product_listing(
            df=processed_df,
            outlet=selected_listing_outlet,
            item_col=pl_item_col,
            qty_col=pl_qty_col,
            sku_col=pl_sku_col if pl_sku_col != "None" else None,
            outlet_col=target_col_name,
        )

        if outlet_listing_df.empty:
            st.warning(f"No line items found for outlet **{selected_listing_outlet}**.")
        else:
            tot_units = int(outlet_listing_df[pl_qty_col].sum())
            tot_skus = len(outlet_listing_df)
            unique_orders = filtered_raw[order_col].nunique() if order_col in filtered_raw else len(filtered_raw)

            # Resolve Date from order data
            date_val = None
            for c in ["Order Date", "Date", "date", "created_at"]:
                if c in filtered_raw.columns:
                    dt_series = pd.to_datetime(filtered_raw[c], errors="coerce").dropna()
                    if not dt_series.empty:
                        date_val = dt_series.max().strftime("%d %b %Y")
                    else:
                        first_valid = filtered_raw[c].dropna()
                        if not first_valid.empty:
                            date_val = str(first_valid.iloc[-1])[:10]
                    break
            if not date_val:
                date_val = bd_today().strftime("%d %b %Y")

            # Resolve Last Order Number
            last_order_num = "—"
            if order_col in filtered_raw.columns:
                valid_orders = filtered_raw.dropna(subset=[order_col])
                if not valid_orders.empty:
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

            # 4 KPI Metrics matching Aggregated Product Picking List
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

            # Construct summary last row
            orders_label = f"{unique_orders:,} Orders" if isinstance(unique_orders, (int, float)) else f"{unique_orders}"
            summary_row = {}
            if pl_sku_col != "None" and pl_sku_col in outlet_listing_df.columns:
                summary_row[pl_item_col] = (
                    f"TOTAL: {orders_label} | Last Order: {last_order_display}"
                )
                summary_row[pl_sku_col] = f"Date: {date_val}"
            else:
                summary_row[pl_item_col] = (
                    f"TOTAL: {orders_label} | Last Order: {last_order_display} | Date: {date_val}"
                )
            summary_row[pl_qty_col] = tot_units

            display_df = pd.concat([outlet_listing_df, pd.DataFrame([summary_row])], ignore_index=True)

            # Style table with pastel group coloring
            def _apply_pastel_colors(data_df):
                styles = pd.DataFrame("", index=data_df.index, columns=data_df.columns)
                color_col = (
                    pl_item_col
                    if pl_item_col in data_df.columns
                    else (pl_sku_col if pl_sku_col != "None" else None)
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

                if len(data_df) > 0:
                    last_idx = data_df.index[-1]
                    styles.loc[last_idx, :] = (
                        "background-color: #e2e8f0; color: #0f172a; font-weight: 800; border-top: 2px solid #475569;"
                    )
                return styles

            st.markdown(f"### 📋 Aggregated Product Picking List — {selected_listing_outlet}")
            st.dataframe(
                display_df.style.apply(_apply_pastel_colors, axis=None),
                use_container_width=True,
                height=min(600, max(300, len(display_df) * 35 + 40)),
                column_config={
                    pl_qty_col: st.column_config.NumberColumn("📦 Total Quantity", format="%d"),
                    pl_item_col: st.column_config.TextColumn("🛍️ Item Name"),
                },
            )

            # Export to styled Excel with pastel color grouping
            export_col = (
                pl_item_col
                if pl_item_col in display_df.columns
                else (pl_sku_col if pl_sku_col != "None" else None)
            )
            excel_styled_bytes = export_to_styled_excel(
                {f"{selected_listing_outlet} Picking List": display_df},
                group_by_col=export_col,
            )

            st.download_button(
                label=f"📥 Download Styled {selected_listing_outlet} Product Listing (Excel)",
                data=excel_styled_bytes,
                file_name=f"{selected_listing_outlet.lower().replace(' ', '_')}_picking_list_{bd_now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )

    with tab_pathao:
        st.markdown("### 🚚 Pathao Bulk Upload Consignments")
        st.caption(
            "Auto-generates 15-column Pathao Bulk Upload sheet. Orders with items across multiple outlets are split into separate consignments: "
            "Warehouse & Mirpur dispatch together (default order ID), Cumilla adds ' c', Sylhet adds ' s', and Wari adds ' w'. "
            "Delivery fee (50 Tk inside Dhaka, 90 Tk outside Dhaka) is added to the first dispatch only."
        )

        with st.expander("⚙️ Pathao Consignment Settings", expanded=False):
            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                store_name_val = st.text_input("Store Name:", value="DEEN", key="pathao_store_name")
            with pc2:
                in_dhaka_fee = st.number_input("Inside Dhaka Fee (Tk):", value=50, step=5, key="pathao_in_fee")
            with pc3:
                out_dhaka_fee = st.number_input("Outside Dhaka Fee (Tk):", value=90, step=5, key="pathao_out_fee")
            with pc4:
                def_weight_val = st.text_input("Default Weight (kg):", value="0.5", key="pathao_weight")

        pathao_df = generate_pathao_bulk_consignments(
            df=processed_df,
            store_name=store_name_val,
            inside_dhaka_fee=int(in_dhaka_fee),
            outside_dhaka_fee=int(out_dhaka_fee),
            default_weight=def_weight_val,
            order_col=order_col,
            sip_col=sip_col,
            target_col=target_col_name,
        )

        if pathao_df.empty:
            st.warning("No consignments generated.")
        else:
            tot_consignments = len(pathao_df)
            tot_cod = int(pd.to_numeric(pathao_df["AmountToCollect(*)"], errors="coerce").fillna(0).sum())
            split_consignments_count = len(pathao_df[pathao_df["SpecialInstruction"].str.contains("Split Part", na=False)])
            inside_dhaka_count = sum(
                1 for _, r in pathao_df.iterrows()
                if is_inside_dhaka(r["RecipientCity(*)"], r["RecipientAddress(*)"])
            )
            outside_dhaka_count = tot_consignments - inside_dhaka_count

            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("📦 Total Consignments", f"{tot_consignments:,}")
            pm2.metric("🔀 Split Consignments", f"{split_consignments_count:,}")
            pm3.metric("💰 Total Amount to Collect", f"৳{tot_cod:,}")
            pm4.metric("🏙️ Dhaka / Outside", f"{inside_dhaka_count} in / {outside_dhaka_count} out")

            st.divider()

            # Filter and search Pathao records
            c_p_filter, c_p_search = st.columns([2, 2])
            with c_p_filter:
                p_outlets = ["All Outlets"] + [o for o in pathao_df["WarehouseOutlet"].dropna().unique() if o]
                selected_p_outlet = st.selectbox("Filter Consignments by Outlet:", p_outlets, key="pathao_outlet_filter")
            with c_p_search:
                p_search_q = st.text_input("Search Consignments (ID, Phone, Name):", "", key="pathao_search_q")

            p_display = pathao_df.copy()
            if selected_p_outlet != "All Outlets":
                p_display = p_display[p_display["WarehouseOutlet"] == selected_p_outlet]

            if p_search_q.strip():
                pq = p_search_q.strip().lower()
                p_mask = p_display.astype(str).apply(lambda row: row.str.lower().str.contains(pq, regex=False)).any(axis=1)
                p_display = p_display[p_mask]

            st.caption(f"Showing **{len(p_display):,}** of **{len(pathao_df):,}** consignments")
            st.dataframe(p_display, use_container_width=True)

            # Download buttons for Pathao Bulk (Excel and CSV)
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                pathao_excel_bytes = to_excel_bytes(pathao_df, sheet_name="Pathao_Bulk")
                st.download_button(
                    label="📥 Download Pathao Bulk Upload (.xlsx)",
                    data=pathao_excel_bytes,
                    file_name=f"pathao_bulk_upload_{bd_now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )
            with c_d2:
                pathao_csv_bytes = pathao_df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    label="📥 Download Pathao Bulk Upload (.csv)",
                    data=pathao_csv_bytes,
                    file_name=f"pathao_bulk_upload_{bd_now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
