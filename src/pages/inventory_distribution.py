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
        ["inv_res_data", "inv_active_l", "inv_t_col", "inv_master_df_live", "inv_l_Ecom_df"]
    )


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
        try:
            # v9.8 Rapid In-Memory Pull
            if st.session_state.get("wc_curr_df") is not None:
                df_live = st.session_state.wc_curr_df
                source_name = "Dashboard_Live_Today"
                st.info("⚡ Instant Pull: Using Today's Active Shift data from Dashboard.")
            else:
                from src.services.woocommerce.client import load_live_source
                with st.spinner("Connecting to WooCommerce API..."):
                    df_live, source_name, _ = load_live_source()

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

                st.session_state.inv_res_data = result_df
                st.session_state.inv_active_l = INVENTORY_LOCATIONS
                st.session_state.inv_t_col = title_col
                save_state()
                st.success("Distribution analysis complete.")
            except Exception as exc:
                log_error(exc, context="Inventory Analyze")
                st.error("Distribution analysis failed.")

    if st.session_state.get("inv_res_data") is not None:
        df = st.session_state.inv_res_data.copy()
        title_key = st.session_state.inv_t_col
        active_locations = st.session_state.inv_active_l

        if search_q:
            df = df[
                df[title_key]
                .astype(str)
                .str.lower()
                .str.contains(search_q.lower(), na=False)
            ]

        # Render UI Tabs
        tab_all, tab_ecom, tab_wari, tab_cumilla, tab_sylhet, tab_split, tab_oos = st.tabs([
            "All Orders", "Ecom-Mirpur", "Wari", "Cumilla", "Sylhet", "Multiple / Split", "Out of Stock"
        ])
        with tab_all: st.dataframe(df, use_container_width=True)
        with tab_ecom: st.dataframe(df[df["Dispatch Suggestion"] == "Ecom-Mirpur"], use_container_width=True)
        with tab_wari: st.dataframe(df[df["Dispatch Suggestion"] == "Wari"], use_container_width=True)
        with tab_cumilla: st.dataframe(df[df["Dispatch Suggestion"] == "Cumilla"], use_container_width=True)
        with tab_sylhet: st.dataframe(df[df["Dispatch Suggestion"] == "Sylhet"], use_container_width=True)
        with tab_split: st.dataframe(df[df["Dispatch Suggestion"] == "Multiple / Split"], use_container_width=True)
        with tab_oos: st.dataframe(df[df["Dispatch Suggestion"] == "OOS / Unfulfillable"], use_container_width=True)

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
                    for val in target_df[group_col]:
                        val_str = str(val).strip().lower()
                        if pd.notna(val) and val_str != "" and val_str != "nan":
                            if current_val != val_str:
                                current_val = val_str
                                color_idx = 1 - color_idx
                        else:
                            current_val = None
                            color_idx = 0
                        colors.append('background-color: #E8F2FF' if color_idx == 1 else 'background-color: #FFFFFF')
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
