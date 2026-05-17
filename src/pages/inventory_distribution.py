import io
import pandas as pd
import plotly.express as px
import streamlit as st

from src.utils.logging import log_error
from src.state.persistence import clear_state_keys, save_state
from src.components.widgets import (
    render_action_bar,
    render_reset_confirm,
    section_card,
)
from src.config.ui_config import INVENTORY_LOCATIONS
from src.inventory import core as inv_core
from src.utils.file_io import read_uploaded


def _reset_inventory_state():
    clear_state_keys(
        ["inv_res_data", "inv_active_l", "inv_t_col", "inv_master_df_live", "inv_l_Ecom_df", "inv_pathao_df", "inv_inventory_map", "inv_sku_map", "inv_sku_col"]
    )


def _clear_analysis_results():
    clear_state_keys(["inv_res_data", "inv_active_l", "inv_t_col", "inv_pathao_df", "inv_inventory_map", "inv_sku_map", "inv_sku_col"])


def _render_upload_summary(master_df, title_col):
    c1, c2 = st.columns(2)
    c1.metric("Master rows", 0 if master_df is None else (master_df.shape[0] if hasattr(master_df, 'shape') else len(master_df)))
    c2.metric("Title column", title_col if title_col else "Not detected")


def render_distribution_tab(search_q):
    render_reset_confirm("Inventory Distribution", "inventory", _reset_inventory_state)
    master_file = st.file_uploader("", type=["xlsx", "csv"], key="inv_up")

    st.markdown('<div style="margin-top: -12px;"></div>', unsafe_allow_html=True)
    c_live, c_url = st.columns(2)
    with c_live:
        fetch_live_clicked = st.button(
            "🔗 Pull from Live Dash",
            type="secondary",
            use_container_width=True,
            key="dist_live",
        )
    with c_url:
        url_input = st.text_input("Paste public CSV/XLSX URL", key="dist_url_input", label_visibility="collapsed", placeholder="Paste public CSV/XLSX URL...")
        if url_input and st.button("Fetch URL", use_container_width=True, type="secondary", key="dist_url_fetch"):
            try:
                from src.utils.url_fetch import fetch_dataframe_from_url
                with st.spinner("Fetching from URL..."):
                    df_res = fetch_dataframe_from_url(url_input)
                    st.session_state.inv_master_df_live = df_res
                    st.session_state.inv_auto_analyze = True
                    _clear_analysis_results()
                    st.rerun()
            except Exception as e:
                st.error(f"URL fetch failed: {e}")

    loc_files = {}
    loc_cols = st.columns(len(INVENTORY_LOCATIONS))
    for i, loc in enumerate(INVENTORY_LOCATIONS):
        with loc_cols[i]:
            if loc == "Ecom":
                # Show status if synced or using manual upload
                if st.session_state.get(f"inv_l_{loc}_df") is not None:
                    st.caption("✅ Using Cached Web Stock")
                    loc_files[loc] = st.session_state.get(f"inv_l_{loc}_df")

                # Instruction

            uploaded = st.file_uploader(
                f"{loc}", key=f"inv_l_{loc}", type=["xlsx", "csv"]
            )
            if uploaded:
                loc_files[loc] = uploaded

    master_df = None
    title_col = None
    sku_col = None

    if fetch_live_clicked:
        _clear_analysis_results()
        try:
            # v9.8 Rapid In-Memory Pull
            if st.session_state.get("wc_curr_df") is not None:
                df_live = st.session_state.wc_curr_df.copy()
                
                status_col = "Order Status" if "Order Status" in df_live.columns else "Status" if "Status" in df_live.columns else None
                if status_col:
                    df_live = df_live[df_live[status_col].astype(str).str.lower().isin(["processing", "on-hold", "pending"])]
                    
                source_name = "Dashboard_Live_Today"
                st.info("⚡ Instant Pull: Using Today's Active Shift data (Processing/On-Hold) from Dashboard.")
            else:
                from src.services.woocommerce.client import load_live_source
                with st.spinner("Connecting to WooCommerce API..."):
                    df_live, source_name, _ = load_live_source()
                    status_col = "Order Status" if "Order Status" in df_live.columns else "Status" if "Status" in df_live.columns else None
                    if status_col:
                        df_live = df_live[df_live[status_col].astype(str).str.lower().isin(["processing", "on-hold", "pending"])]

            master_df = df_live
            st.session_state.inv_master_df_live = master_df
            st.session_state.inv_auto_analyze = True

            _, _, title_col, sku_col = inv_core.identify_columns(master_df)

            if not title_col:
                st.error(
                    "Could not detect an item title/name column."
                )
            else:
                st.success(f"Successfully pulled {df_live.shape[0] if hasattr(df_live, 'shape') else len(df_live)} records.")
        except Exception as exc:
            log_error(exc, context="Inventory WooCommerce Pull")
            st.error(f"Failed to fetch data: {exc}")
    elif master_file:
        if st.session_state.get("inv_last_master_name") != master_file.name:
            st.session_state.inv_last_master_name = master_file.name
            _clear_analysis_results()
            
        try:
            master_df = read_uploaded(master_file)
            st.session_state.inv_master_df_live = master_df
            _, _, title_col, sku_col = inv_core.identify_columns(master_df)
            _render_upload_summary(master_df, title_col)
            if not title_col:
                st.error(
                    "Could not detect an item title/name column in the master list."
                )
            else:
                st.success("Validation passed. Ready to run analysis.")
        except Exception as exc:
            log_error(exc, context="Inventory Upload")
            st.error("Failed to read master stock list.")
    elif st.session_state.get("inv_master_df_live") is not None:
        master_df = st.session_state.inv_master_df_live
        _, _, title_col, sku_col = inv_core.identify_columns(master_df)

    st.markdown("---")
    sync_live_web_stock = st.toggle("Sync Live Web Stock (Ecom)", value=True, help="Turn on to automatically fetch real-time web stock for Ecom location if a file is not manually uploaded.")

    analyze_clicked, clear_clicked = render_action_bar(
        primary_label="Analyze distribution",
        primary_key="inv_analyze_btn",
        secondary_label="Clear inventory data",
        secondary_key="inv_clear_btn",
    )

    if st.session_state.get("inv_auto_analyze"):
        analyze_clicked = True
        st.session_state.inv_auto_analyze = False

    if clear_clicked:
        _reset_inventory_state()
        st.rerun()

    if analyze_clicked:
        if master_df is None or not title_col:
            st.warning(
                "Upload a valid master stock list or pull from live source before analysis."
            )
        else:
            # Prevent empty SKUs from clustering unrelated products together
            if sku_col and sku_col in master_df.columns:
                master_df[sku_col] = master_df[sku_col].astype(str).fillna("N/A")
                master_df[sku_col] = master_df[sku_col].replace({"": "N/A", "NaN": "N/A", "nan": "N/A", "None": "N/A", "0": "N/A"})
            else:
                master_df["SKU"] = "N/A"
                sku_col = "SKU"

            try:
                # 1. INTEGRATED REAL-TIME ECOM SYNC:
                # Only sync if "Ecom" wasn't manually uploaded for this analysis
                if "Ecom" not in loc_files and sync_live_web_stock:
                    with st.status("🔗 Reconciling Live Web Stock...", expanded=False) as sync_status:
                        t_skus = set(master_df[sku_col].dropna().astype(str).unique()) if sku_col and sku_col in master_df.columns else None
                        t_titles = set()
                        from src.inventory.core import item_name_to_title_size
                        t_col = title_col if title_col in master_df.columns else None
                        if t_col:
                            for item in master_df[t_col].dropna():
                                title, _ = item_name_to_title_size(str(item))
                                if title: t_titles.add(title.strip().lower())

                        from src.services.woocommerce.stock import fetch_woocommerce_stock
                        wocom_df = fetch_woocommerce_stock(filter_skus=t_skus, filter_titles=t_titles)

                        if wocom_df is not None:
                            loc_files["Ecom"] = wocom_df
                            st.session_state.inv_l_Ecom_df = wocom_df
                            sync_status.update(label=f"Done: Ecom stock synced for {wocom_df.shape[0] if hasattr(wocom_df, 'shape') else len(wocom_df)} relevant items.", state="complete")
                        else:
                            st.warning("⚠️ WooCommerce sync failed. Analysis will proceed using other locations.")

                inventory_map, warnings, _, sku_map = (
                    inv_core.load_inventory_from_uploads(loc_files)
                )
                if warnings:
                    for warning in warnings:
                        st.warning(warning)

                result_df, _ = inv_core.add_stock_columns_from_inventory(
                    master_df,
                    title_col,
                    inventory_map,
                    INVENTORY_LOCATIONS,
                    sku_col,
                    sku_map,
                )

                if "Fulfillment" in result_df.columns:
                    error_mask = result_df["Fulfillment"].astype(str).str.contains("Error", na=False)
                    if error_mask.any():
                        st.warning(f"⚠️ Encountered processing errors in {error_mask.sum()} order row(s). Check the 'Fulfillment' column for details.")

                st.session_state.inv_res_data = result_df
                st.session_state.inv_active_l = INVENTORY_LOCATIONS
                st.session_state.pop("inv_pathao_df", None)
                st.session_state.inv_t_col = title_col
                st.session_state.inv_inventory_map = inventory_map
                st.session_state.inv_sku_map = sku_map
                st.session_state.inv_sku_col = sku_col
                save_state()
                st.success("Distribution analysis complete.")
            except Exception as exc:
                log_error(exc, context="Inventory Analyze")
                st.error("Distribution analysis failed.")

    if st.session_state.get("inv_res_data") is not None:
        st.divider()
        st.subheader("🧮 Live Scenario Simulator")
        st.markdown("Adjust the sliders below to simulate demand and supply changes. The distribution matrix will recalculate in real-time.")
        
        sc1, sc2 = st.columns(2)
        with sc1:
            sim_demand_adj = st.slider("Simulate Demand / Order Volume (%)", -50, 200, 0, step=10, help="Simulate a percentage change in requested order quantities.")
        with sc2:
            sim_supply_adj = st.slider("Simulate Supply / Stock Level (%)", -50, 100, 0, step=10, help="Simulate a percentage change in available stock across all locations.")
            
        if sim_demand_adj != 0 or sim_supply_adj != 0:
            master_df = st.session_state.get("inv_master_df_live")
            inventory_map = st.session_state.get("inv_inventory_map")
            sku_map = st.session_state.get("inv_sku_map")
            sku_col = st.session_state.get("inv_sku_col")
            title_col = st.session_state.get("inv_t_col")
            locations = st.session_state.get("inv_active_l")
            
            if master_df is not None and inventory_map is not None:
                sim_master_df = master_df.copy()
                
                _, qty_col, _, _ = inv_core.identify_columns(sim_master_df)
                if qty_col and qty_col in sim_master_df.columns:
                    sim_master_df[qty_col] = pd.to_numeric(sim_master_df[qty_col], errors='coerce').fillna(1) * (1 + (sim_demand_adj / 100.0))
                    sim_master_df[qty_col] = sim_master_df[qty_col].apply(lambda x: max(1, int(round(x))))
                    
                sim_inventory_map = {}
                for k, locs in inventory_map.items():
                    sim_inventory_map[k] = {loc: max(0, int(round(qty * (1 + (sim_supply_adj / 100.0))))) for loc, qty in locs.items()}
                    
                with st.spinner("Simulating..."):
                    df, _ = inv_core.add_stock_columns_from_inventory(
                        sim_master_df,
                        title_col,
                        sim_inventory_map,
                        locations,
                        sku_col,
                        sku_map,
                    )
            else:
                df = st.session_state.inv_res_data.copy()
        else:
            df = st.session_state.inv_res_data.copy()
            
        total_orders = df.shape[0] if hasattr(df, 'shape') else len(df)
        oos_count = df[df["Dispatch Suggestion"] == "OOS / Unfulfillable"].shape[0] if "Dispatch Suggestion" in df.columns else 0
        split_count = df[df["Dispatch Suggestion"] == "Multiple / Split"].shape[0] if "Dispatch Suggestion" in df.columns else 0
        
        oos_rate = (oos_count / total_orders * 100) if total_orders > 0 else 0
        
        sim_html = (
            '<div class="metric-container">'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Total Items</div><div class="metric-value">{total_orders:,.0f}</div></div><div class="metric-icon">📦</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Out of Stock Rate</div><div class="metric-value">{oos_rate:.1f}%</div></div><div class="metric-icon">⚠️</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Split Parcels</div><div class="metric-value">{split_count:,.0f}</div></div><div class="metric-icon">✂️</div></div>'
            '</div>'
        )
        st.markdown(sim_html, unsafe_allow_html=True)
        st.divider()

        title_key = st.session_state.inv_t_col
        active_locations = st.session_state.inv_active_l

        if search_q:
            df = df[
                df[title_key]
                .astype(str)
                .str.lower()
                .str.contains(search_q.lower(), na=False)
            ]

        def highlight_inventory_rows(row):
            sugg = str(row.get("Dispatch Suggestion", ""))
            if "OOS" in sugg or "Unfulfillable" in sugg:
                return ['background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 500;'] * len(row)
            elif "Multiple / Split" in sugg:
                return ['background-color: rgba(245, 158, 11, 0.15); color: #b45309; font-weight: 500;'] * len(row)
            elif "Error" in sugg:
                return ['background-color: rgba(220, 38, 38, 0.2); color: #991b1b; font-weight: bold;'] * len(row)
            return [''] * len(row)

        # Render UI Tabs
        tab_all, tab_ecom, tab_wari, tab_cumilla, tab_sylhet, tab_split, tab_oos = st.tabs([
            "All Orders", "Ecom-Mirpur", "Wari", "Cumilla", "Sylhet", "Multiple / Split", "Out of Stock"
        ])
        with tab_all: st.dataframe(df.style.apply(highlight_inventory_rows, axis=1), use_container_width=True)
        with tab_ecom: st.dataframe(df[df["Dispatch Suggestion"] == "Ecom-Mirpur"].style.apply(highlight_inventory_rows, axis=1), use_container_width=True)
        with tab_wari: st.dataframe(df[df["Dispatch Suggestion"] == "Wari"].style.apply(highlight_inventory_rows, axis=1), use_container_width=True)
        with tab_cumilla: st.dataframe(df[df["Dispatch Suggestion"] == "Cumilla"].style.apply(highlight_inventory_rows, axis=1), use_container_width=True)
        with tab_sylhet: st.dataframe(df[df["Dispatch Suggestion"] == "Sylhet"].style.apply(highlight_inventory_rows, axis=1), use_container_width=True)
        with tab_split: st.dataframe(df[df["Dispatch Suggestion"] == "Multiple / Split"].style.apply(highlight_inventory_rows, axis=1), use_container_width=True)
        with tab_oos: st.dataframe(df[df["Dispatch Suggestion"] == "OOS / Unfulfillable"].style.apply(highlight_inventory_rows, axis=1), use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            loc_totals = [{"Metric": "Total SKUs Analyzed", "Value": df.shape[0] if hasattr(df, 'shape') else len(df)}]
            for loc in active_locations:
                if loc in df.columns:
                    loc_totals.append({"Metric": f"Total Units ({loc})", "Value": pd.to_numeric(df[loc], errors='coerce').sum()})
            df_metrics = pd.DataFrame(loc_totals)
            df_metrics.to_excel(writer, index=False, sheet_name="Distribution Metrics")
            
            group_col = inv_core.get_group_by_column(df)

            def make_color_func(target_df):
                def get_row_colors(col_series):
                    colors = []
                    color_idx = 0
                    current_val = None
                    
                    group_vals = target_df[group_col].values
                    col_vals = col_series.values
                    
                    for i, val in enumerate(group_vals):
                        val_str = str(val).strip().lower()
                        if pd.notna(val) and val_str != "" and val_str != "nan":
                            if current_val != val_str:
                                current_val = val_str
                                color_idx = 1 - color_idx
                        else:
                            current_val = None
                            color_idx = 0
                            
                        bg_color = '#E8F2FF' if color_idx == 1 else '#FFFFFF'
                        font_style = ''
                        
                        if col_series.name == "Fulfillment" and "Stock Exhausted by Prior Orders" in str(col_vals[i]):
                            bg_color = '#FEE2E2'
                            font_style = 'color: #DC2626; font-weight: bold;'
                            
                        colors.append(f'background-color: {bg_color}; {font_style}')
                    return colors
                return get_row_colors

            sheets_data = [
                ("All Orders", None),
                ("Ecom-Mirpur", "Ecom-Mirpur"),
                ("Wari", "Wari"),
                ("Cumilla", "Cumilla"),
                ("Sylhet", "Sylhet"),
                ("Multiple Split", "Multiple / Split"),
                ("Out of Stock", "OOS / Unfulfillable")
            ]
            
            sheet_names_to_format = [("Distribution Metrics", df_metrics)]

            for sheet_name, suggestion_val in sheets_data:
                if suggestion_val is None:
                    tab_df = df.copy()
                else:
                    tab_df = df[df["Dispatch Suggestion"] == suggestion_val].copy()
                
                if tab_df.empty and suggestion_val is not None:
                    continue

                styled = False
                if group_col:
                    try:
                        color_func = make_color_func(tab_df)
                        styled_df = tab_df.style.apply(color_func, axis=0)
                        styled_df.to_excel(writer, index=False, sheet_name=sheet_name)
                        styled = True
                    except Exception as e:
                        log_error(e, context="Excel Styling")
                
                if not styled:
                    tab_df.to_excel(writer, index=False, sheet_name=sheet_name)
                
                sheet_names_to_format.append((sheet_name, tab_df))

            workbook = writer.book
            header_format = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})

            # Auto-format column widths & apply header styles
            for sheet_name, df_ref in sheet_names_to_format:
                if sheet_name in writer.sheets and not df_ref.empty:
                    ws = writer.sheets[sheet_name]
                    for idx, col in enumerate(df_ref.columns):
                        ws.write(0, idx, str(col), header_format)
                        try:
                            max_len = max(df_ref[col].astype(str).map(lambda x: len(str(x))).max(), len(str(col))) + 2
                            ws.set_column(idx, idx, min(max_len, 50))
                        except Exception as e:
                            import traceback
                            with open("h:\\DEEN-OPS\\excel_format_error.log", "a", encoding="utf-8") as f:
                                f.write(traceback.format_exc())
                            max_len = len(str(col)) + 2
                            ws.set_column(idx, idx, min(max_len, 50))
                        
                    # Apply Excel Data Grouping (Outline) for orders with multiple items
                    if group_col and group_col in df_ref.columns:
                        current_group = None
                        for row_idx in range(len(df_ref)):
                            val = df_ref.iloc[row_idx][group_col]
                            val_str = str(val).strip() if pd.notna(val) else ""
                            if val_str and val_str == current_group:
                                # Group additional items under the first row of the order
                                try:
                                    ws.set_row(row_idx + 1, None, None, {'level': 1})
                                except Exception:
                                    pass
                            else:
                                current_group = val_str

        st.download_button(
            "Download distribution report",
            output.getvalue(),
            "Stock_Distribution.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )

        # --- PATHAO INTEGRATION ---
        st.divider()
        st.subheader("📦 Generate Pathao Bulk Sheet")
        st.write("Automatically create multi-parcel Pathao uploads based on these exact dispatch locations.")
        
        c_pathao1, c_pathao2 = st.columns([1, 1])
        with c_pathao1:
            dispatch_loc_options = ["All Fulfillable"] + [loc for loc in active_locations if "Dispatch Suggestion" in df.columns and loc in df["Dispatch Suggestion"].unique()]
            selected_pathao_loc = st.selectbox("Filter Dispatch Location for Pathao", dispatch_loc_options)
            
            if st.button("Process for Pathao", use_container_width=True):
                with st.spinner("Processing orders..."):
                    from src.processing.order_processor import process_orders_dataframe
                    try:
                        if selected_pathao_loc == "All Fulfillable":
                            valid_dispatch_df = df[df["Dispatch Suggestion"] != "OOS / Unfulfillable"].copy()
                        else:
                            valid_dispatch_df = df[df["Dispatch Suggestion"] == selected_pathao_loc].copy()
                        
                        # Ensure Pathao processor finds the correct phone column
                        from src.processing.column_detection import find_columns
                        det_cols = find_columns(valid_dispatch_df)
                        if det_cols.get("phone") and det_cols["phone"] != "Phone (Billing)":
                            valid_dispatch_df = valid_dispatch_df.rename(columns={det_cols["phone"]: "Phone (Billing)"})
                            
                        if valid_dispatch_df.empty:
                            st.error("No fulfillable items to process.")
                        else:
                            st.session_state.inv_pathao_df = process_orders_dataframe(valid_dispatch_df)
                            st.rerun()
                    except Exception as e:
                        from src.utils.logging import log_error
                        log_error(e, context="Inventory Pathao Processor")
                        st.error(f"Pathao processing failed: {e}")
        
        with c_pathao2:
            if st.session_state.get("inv_pathao_df") is not None:
                p_output = io.BytesIO()
                with pd.ExcelWriter(p_output, engine="xlsxwriter") as p_writer:
                    st.session_state.inv_pathao_df.to_excel(p_writer, index=False, sheet_name="Pathao")
                    workbook = p_writer.book
                    header_format = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
                    ws = p_writer.sheets["Pathao"]
                    for idx, col in enumerate(st.session_state.inv_pathao_df.columns):
                        ws.write(0, idx, str(col), header_format)
                        try:
                            max_len = max(st.session_state.inv_pathao_df[col].astype(str).map(lambda x: len(str(x))).max(), len(str(col))) + 2
                            ws.set_column(idx, idx, min(max_len, 50))
                        except Exception:
                            ws.set_column(idx, idx, 20)
                            
                st.download_button(
                    "📥 Download Pathao Excel",
                    p_output.getvalue(),
                    "Pathao_Bulk_From_Inventory.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )
