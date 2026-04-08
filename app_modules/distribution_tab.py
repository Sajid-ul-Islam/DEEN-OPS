import io

import pandas as pd
import plotly.express as px
import streamlit as st

from app_modules.error_handler import log_error
from app_modules.persistence import clear_state_keys, save_state
from app_modules.ui_components import (
    render_action_bar,
    render_reset_confirm,
    section_card,
)
from app_modules.ui_config import INVENTORY_LOCATIONS
from inventory_modules import core as inv_core


def _read_uploaded(uploaded_file):
    if not uploaded_file:
        return None
    uploaded_file.seek(0)
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def _reset_inventory_state():
    clear_state_keys(
        ["inv_res_data", "inv_active_l", "inv_t_col", "inv_master_df_live", "inv_l_Ecom_df"]
    )


def _render_upload_summary(master_df, title_col):
    c1, c2 = st.columns(2)
    c1.metric("Master rows", 0 if master_df is None else len(master_df))
    c2.metric("Title column", title_col if title_col else "Not detected")


def render_distribution_tab(search_q):
    render_reset_confirm("Inventory Distribution", "inventory", _reset_inventory_state)
    master_file = st.file_uploader("", type=["xlsx", "csv"], key="inv_up")

    st.markdown('<div style="margin-top: -12px;"></div>', unsafe_allow_html=True)
    c_live, c_gsheet = st.columns(2)
    with c_live:
        fetch_live_clicked = st.button(
            "🔗 Pull from Live Dash",
            type="secondary",
            use_container_width=True,
            key="dist_live",
        )
    with c_gsheet:
        if st.button("📩 Fetch Master from GSheet", use_container_width=True, type="secondary", key="dist_gsheet"):
            try:
                from app_modules.ui_config import DEFAULT_GSHEET_URL
                with st.spinner("Fetching master from Google Sheet..."):
                    df_res = pd.read_csv(DEFAULT_GSHEET_URL)
                    st.session_state.inv_master_df_live = df_res
                    st.session_state.inv_auto_analyze = True
                    st.rerun()
            except Exception as e:
                st.error(f"GSheet failed: {e}")

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
                from app_modules.sales_dashboard import load_live_source
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
                st.success(f"Successfully pulled {len(df_live)} records.")
        except Exception as exc:
            log_error(exc, context="Inventory WooCommerce Pull")
            st.error(f"Failed to fetch data: {exc}")
    elif master_file:
        try:
            master_df = _read_uploaded(master_file)
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
                if "Ecom" not in loc_files:
                    with st.status("🔗 Reconciling Live Web Stock...", expanded=False) as sync_status:
                        t_skus = set(master_df[sku_col].dropna().astype(str).unique()) if sku_col and sku_col in master_df.columns else None
                        t_titles = set()
                        from inventory_modules.core import item_name_to_title_size
                        t_col = title_col if title_col in master_df.columns else None
                        if t_col:
                            for item in master_df[t_col].dropna():
                                title, _ = item_name_to_title_size(str(item))
                                if title: t_titles.add(title.strip().lower())
                        
                        from app_modules.sales_dashboard import fetch_woocommerce_stock
                        wocom_df = fetch_woocommerce_stock(filter_skus=t_skus, filter_titles=t_titles)
                        
                        if wocom_df is not None:
                            loc_files["Ecom"] = wocom_df
                            sync_status.update(label=f"Done: Ecom stock synced for {len(wocom_df)} relevant items.", state="complete")
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

        st.dataframe(df, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Distribution")
        st.download_button(
            "Download distribution report",
            output.getvalue(),
            "Stock_Distribution.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )
