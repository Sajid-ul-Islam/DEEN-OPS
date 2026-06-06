import io
import pandas as pd
import streamlit as st

from src.utils.logging import log_error
from src.state.persistence import clear_state_keys, save_state
from src.components.widgets import (
    render_action_bar,
    render_reset_confirm,
)
from src.config.ui_config import INVENTORY_LOCATIONS
from src.inventory import core as inv_core
from src.utils.file_io import read_uploaded
from src.pages.excel_exporter import export_to_styled_excel


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

    import os
    import io
    loc_files = {}
    loc_cols = st.columns(len(INVENTORY_LOCATIONS))

    default_files = {
        "Mirpur": "Mir.xlsx",
        "Wari": "War.xlsx",
        "Cumilla": "Cum.xlsx",
        "Sylhet": "Syl.xlsx"
    }

    for i, loc in enumerate(INVENTORY_LOCATIONS):
        with loc_cols[i]:
            if loc == "Ecom":
                # Show status if synced or using manual upload
                if st.session_state.get(f"inv_l_{loc}_df") is not None:
                    st.caption("✅ Using Cached Web Stock")
                    loc_files[loc] = st.session_state.get(f"inv_l_{loc}_df")

            uploaded = st.file_uploader(
                f"{loc}", key=f"inv_l_{loc}", type=["xlsx", "csv"]
            )
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
                    st.caption("ℹ️ No default file")

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
                    df_live = df_live[df_live[status_col].astype(str).str.lower().isin(["processing", "on-hold", "pending", "waiting"])]
                    
                source_name = "Dashboard_Live_Today"
                st.info("⚡ Instant Pull: Using Today's Active Shift data (Processing/On-Hold) from Dashboard.")
            else:
                from src.services.woocommerce.client import load_live_source
                with st.spinner("Connecting to WooCommerce API..."):
                    df_live, source_name, _ = load_live_source()
                    status_col = "Order Status" if "Order Status" in df_live.columns else "Status" if "Status" in df_live.columns else None
                    if status_col:
                        df_live = df_live[df_live[status_col].astype(str).str.lower().isin(["processing", "on-hold", "pending", "waiting"])]

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

    # ── Outlet Priority ──────────────────────────────────────────────────────
    with st.expander("⚙️ Dispatch Priority Order", expanded=False):
        st.caption(
            "Drag to reorder — the top outlet is tried first when suggesting dispatch. "
            "Default: Ecom-Mirpur → Wari → Cumilla → Sylhet."
        )
        default_priority = ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet"]
        # Persist across reruns
        if "inv_priority_order" not in st.session_state:
            st.session_state.inv_priority_order = default_priority.copy()

        current_priority = st.session_state.inv_priority_order

        # Render as a numbered multiselect that the user can reorder by toggling
        # (Streamlit has no native drag-sort; we use a selectbox-based rank editor)
        st.markdown("**Set rank for each outlet (1 = highest priority):**")
        rank_cols = st.columns(len(default_priority))
        new_order_map = {}
        used_ranks = set()
        valid = True
        for i, loc in enumerate(default_priority):
            with rank_cols[i]:
                current_rank = (
                    current_priority.index(loc) + 1
                    if loc in current_priority
                    else i + 1
                )
                rank = st.number_input(
                    loc,
                    min_value=1,
                    max_value=len(default_priority),
                    value=current_rank,
                    step=1,
                    key=f"inv_rank_{loc}",
                )
                if rank in used_ranks:
                    valid = False
                used_ranks.add(rank)
                new_order_map[rank] = loc

        if valid and len(new_order_map) == len(default_priority):
            new_priority = [new_order_map[r] for r in sorted(new_order_map)]
            if new_priority != current_priority:
                st.session_state.inv_priority_order = new_priority
                st.rerun()
        elif not valid:
            st.warning("Each outlet must have a unique rank. Duplicate ranks detected.")

        st.info(
            "Current order: **"
            + " → ".join(st.session_state.inv_priority_order)
            + "**"
        )

        if st.button("Reset to Default", key="inv_priority_reset", use_container_width=True):
            st.session_state.inv_priority_order = default_priority.copy()
            st.rerun()
    # ────────────────────────────────────────────────────────────────────────

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
                    priority_locations=st.session_state.get("inv_priority_order"),
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
        
        st.markdown("""
            <style>
            .live-pulse {
                display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                background: #10b981; margin-right: 8px;
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 1);
                animation: pulse-green 2s infinite;
            }
            @keyframes pulse-green {
                0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
                70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
                100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
            }
            .sim-badge {
                background: rgba(245, 158, 11, 0.15); color: #d97706; 
                padding: 2px 10px; border-radius: 20px; font-size: 0.75rem; 
                font-weight: 700; border: 1px solid rgba(217, 119, 6, 0.3);
            }
            </style>
        """, unsafe_allow_html=True)

        sim_demand_adj = 0
        sim_supply_adj = 0
        
        with st.container(border=True):
            st.markdown(
                '<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">'
                '<div style="display: flex; align-items: center;"><div class="live-pulse"></div>'
                '<h3 style="margin: 0; font-size: 1.25rem;">Live Scenario Simulator</h3></div>'
                '</div>', unsafe_allow_html=True
            )
            sc1, sc2 = st.columns(2)
            with sc1:
                sim_demand_adj = st.slider("Simulate Demand Volume (%)", -50, 200, 0, step=10)
            with sc2:
                sim_supply_adj = st.slider("Simulate Supply Level (%)", -50, 100, 0, step=10)
            
        if sim_demand_adj != 0 or sim_supply_adj != 0:
            st.toast("⚡ Simulation Mode Active", icon="🧪")
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
                        priority_locations=st.session_state.get("inv_priority_order"),
                    )
            else:
                df = st.session_state.inv_res_data.copy()
        else:
            df = st.session_state.inv_res_data.copy()
            
        total_orders = df.shape[0] if hasattr(df, 'shape') else len(df)
        oos_count = df[df["Dispatch Suggestion"] == "OOS / Unfulfillable"].shape[0] if "Dispatch Suggestion" in df.columns else 0
        split_count = df[df["Dispatch Suggestion"] == "Multiple / Split"].shape[0] if "Dispatch Suggestion" in df.columns else 0
        
        oos_rate = (oos_count / total_orders * 100) if total_orders > 0 else 0
        
        
        sim_badge_html = '<span class="sim-badge">SIMULATED DATA</span>' if (sim_demand_adj != 0 or sim_supply_adj != 0) else '<span style="color: #64748b; font-size: 0.75rem;">LIVE SNAPSHOT</span>'
        
        st.markdown(
            f'<div style="margin: 1.5rem 0 0.5rem 0;">{sim_badge_html}</div>'
            '<div class="metric-container">'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Total Items</div><div class="metric-value">{total_orders:,.0f}</div></div><div class="metric-icon">📦</div></div>'
            f'<div class="metric-card" style="border-left: 4px solid {"#ef4444" if oos_rate > 10 else "#10b981"}"><div class="metric-content"><div class="metric-label">Out of Stock Rate</div><div class="metric-value">{oos_rate:.1f}%</div></div><div class="metric-icon">⚠️</div></div>'
            f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Split Parcels</div><div class="metric-value">{split_count:,.0f}</div></div><div class="metric-icon">✂️</div></div>'
            '</div>', 
            unsafe_allow_html=True
        )
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

        # Render UI Tabs — dynamic based on priority order
        _priority = st.session_state.get("inv_priority_order", ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet"])
        _tab_labels = [":material/all_inbox: All Orders"] + [f":material/store: {loc}" for loc in _priority] + [":material/call_split: Multiple / Split", ":material/warning: Out of Stock"]
        _tabs = st.tabs(_tab_labels)

        def get_df_height(data_len):
            return min(800, max(400, data_len * 35 + 43))

        with _tabs[0]:  # All Orders
            st.dataframe(df.style.apply(highlight_inventory_rows, axis=1), use_container_width=True, height=get_df_height(len(df)))

        for _i, _loc_label in enumerate(_priority):
            with _tabs[_i + 1]:
                sub_df = df[df["Dispatch Suggestion"] == _loc_label]
                st.dataframe(sub_df.style.apply(highlight_inventory_rows, axis=1), use_container_width=True, height=get_df_height(len(sub_df)))

        with _tabs[len(_priority) + 1]:  # Multiple / Split
            sub_df = df[df["Dispatch Suggestion"] == "Multiple / Split"]
            st.dataframe(sub_df.style.apply(highlight_inventory_rows, axis=1), use_container_width=True, height=get_df_height(len(sub_df)))

        with _tabs[len(_priority) + 2]:  # Out of Stock
            sub_df = df[df["Dispatch Suggestion"] == "OOS / Unfulfillable"]
            st.dataframe(sub_df.style.apply(highlight_inventory_rows, axis=1), use_container_width=True, height=get_df_height(len(sub_df)))

        # Prepare data for centralized exporter
        export_data = {}

        # 1. Metrics sheet
        loc_totals = [{"Metric": "Total SKUs Analyzed", "Value": len(df)}]
        for loc in active_locations:
            if loc in df.columns:
                loc_totals.append({"Metric": f"Total Units ({loc})", "Value": pd.to_numeric(df[loc], errors='coerce').sum()})
        export_data["Distribution Metrics"] = pd.DataFrame(loc_totals)

        # 2. Partitioned sheets
        sheets_to_process = [("All Orders", None)]
        for _loc_label in _priority:
            sheets_to_process.append((_loc_label[:31], _loc_label))
        sheets_to_process += [
            ("Multiple Split", "Multiple / Split"),
            ("Out of Stock",   "OOS / Unfulfillable"),
        ]

        for sheet_name, suggestion_val in sheets_to_process:
            tab_df = df.copy() if suggestion_val is None else df[df["Dispatch Suggestion"] == suggestion_val].copy()
            if not tab_df.empty or suggestion_val is None:
                export_data[sheet_name] = tab_df

        excel_report_bytes = export_to_styled_excel(export_data)

        st.download_button(
            "Download distribution report",
            excel_report_bytes,
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
                p_excel_bytes = export_to_styled_excel({"Pathao": st.session_state.inv_pathao_df})
                st.download_button(
                    "📥 Download Pathao Excel",
                    p_excel_bytes,
                    "Pathao_Bulk_From_Inventory.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )
