import json
import os
from io import BytesIO

import pandas as pd
import streamlit as st

from src.components.status import render_status_toggle
from src.components.widgets import (
    render_action_bar,
    render_file_summary,
    render_reset_confirm,
    section_card,
)
from src.config.ui_config import PATHAO_CONFIG
from src.processing.order_processor import (
    normalize_manual_item_input,
    process_orders_dataframe,
)
from src.services.pathao.client import PathaoClient
from src.state.persistence import clear_state_keys, save_state
from src.utils.file_io import read_uploaded
from src.utils.logging import log_error

REQUIRED_COLUMNS = ["Phone (Billing)"]
SOURCE_WOOCOM = "WooCommerce Processing"
SOURCE_UPLOAD = "Upload / URL"


def _reset_pathao_state():
    clear_state_keys(
        [
            "pathao_res_df",
            "pathao_preview_df",
            "pathao_preview_source",
            "pathao_vlink_df",
            "show_vlink_gen",
            "pathao_auto_process",
            "pathao_manual_items_df",
            "pathao_manual_desc",
        ]
    )


def _filter_processing_orders(df):
    status_col = (
        "Order Status"
        if "Order Status" in df.columns
        else "Status"
        if "Status" in df.columns
        else None
    )
    if not status_col:
        return df.copy(), False

    filtered_df = df[df[status_col].astype(str).str.lower() == "processing"].copy()
    return filtered_df, True


def _sync_pathao_map():
    with st.status("Connecting to Pathao API...", expanded=True) as status:
        try:
            client = PathaoClient(**PATHAO_CONFIG)
            st.write("Fetching cities...")
            cities, error = client.get_cities()

            if error:
                st.error(f"Sync failed: {error}")
                status.update(label="Sync failed", state="error")
                return

            if not cities:
                st.warning(
                    "Connected successfully, but Pathao returned an empty city list."
                )
                status.update(label="Sync complete (empty)", state="complete")
                return

            full_map = {}
            progress_bar = st.progress(0)
            for i, city in enumerate(cities):
                city_id = city["city_id"]
                city_name = city["city_name"]
                st.write(f"Syncing {city_name}...")
                zones, zone_error = client.get_zones(city_id)

                full_map[city_name] = {"city_id": city_id, "zones": {}}
                if not zone_error:
                    for zone in zones:
                        zone_id = zone["zone_id"]
                        zone_name = zone["zone_name"]
                        areas, area_error = client.get_areas(zone_id)
                        full_map[city_name]["zones"][zone_name] = {
                            "zone_id": zone_id,
                            "areas": areas if not area_error else [],
                        }

                progress_bar.progress((i + 1) / len(cities))

            os.makedirs("resources", exist_ok=True)
            with open("resources/pathao_map.json", "w", encoding="utf-8") as f:
                json.dump(full_map, f, indent=4)

            st.success(f"Successfully synced {len(cities)} cities and their areas.")
            status.update(label="Sync complete", state="complete")
        except Exception as exc:
            st.error(f"Sync failed: {exc}")
            status.update(label="Sync error", state="error")


def _load_processing_orders_from_woocommerce():
    if st.session_state.get("wc_curr_df") is not None:
        df_live = st.session_state.wc_curr_df
        st.info("Using the current operational WooCommerce snapshot.")
    else:
        from src.services.woocommerce.client import load_live_source

        with st.spinner("Connecting to WooCommerce API..."):
            df_live, _, _ = load_live_source()

    return _filter_processing_orders(df_live)


def _render_processing_tab():
    render_reset_confirm("Pathao Processor", "pathao", _reset_pathao_state)

    with st.expander("Pathao API & Sync Settings", expanded=False):
        st.markdown("### Location Database Sync")

        pathao_map_path = "resources/pathao_map.json"
        if os.path.exists(pathao_map_path):
            from datetime import datetime

            modified_at = os.path.getmtime(pathao_map_path)
            updated_str = datetime.fromtimestamp(modified_at).strftime(
                "%Y-%m-%d %H:%M"
            )
            render_status_toggle(
                "Local DB Loaded", "success", f"Last updated: {updated_str}"
            )
        else:
            render_status_toggle(
                "No Local Data",
                "warning",
                "Sync required for smart zone matching.",
            )

        st.info(
            "Sync the local database with Pathao city, zone, and area data for more accurate matching."
        )

        if st.button("Sync Available Locations from Pathao", use_container_width=True):
            _sync_pathao_map()

    section_card(
        "Order Source",
        "Choose whether to pull active processing orders from WooCommerce or process a user-supplied file.",
    )
    source_mode = st.radio(
        "Select input source",
        [SOURCE_WOOCOM, SOURCE_UPLOAD],
        horizontal=True,
        key="pathao_source_mode",
        label_visibility="collapsed",
    )

    if st.session_state.get("pathao_source_mode_last") != source_mode:
        st.session_state.pathao_source_mode_last = source_mode
        st.session_state.pathao_preview_df = None
        st.session_state.pathao_preview_source = None
        st.session_state.pathao_res_df = None
        st.session_state.pathao_vlink_df = None
        st.session_state.show_vlink_gen = False
        st.session_state.pathao_auto_process = False

    preview_df = None
    valid_file = False
    uploaded_file = None
    fetch_live_clicked = False

    if source_mode == SOURCE_WOOCOM:
        c_pull, c_hint = st.columns([1, 1])
        with c_pull:
            fetch_live_clicked = st.button(
                "Pull Processing Orders",
                type="secondary",
                use_container_width=True,
                key="pathao_live",
            )
        with c_hint:
            st.info("Only WooCommerce rows with status `processing` will be used.")
    else:
        uploaded_file = st.file_uploader("", type=["xlsx", "csv"], key="pathao_up")
        c_upload, c_url = st.columns(2)
        with c_upload:
            st.caption("Upload an Excel or CSV export.")
        with c_url:
            url_input = st.text_input(
                "Paste public CSV/XLSX URL",
                key="pathao_url_input",
                label_visibility="collapsed",
                placeholder="Paste public CSV/XLSX URL...",
            )
            if url_input and st.button(
                "Fetch URL",
                use_container_width=True,
                type="secondary",
                key="pathao_url_fetch",
            ):
                try:
                    from src.utils.url_fetch import fetch_dataframe_from_url

                    with st.spinner("Fetching from URL..."):
                        df_res = fetch_dataframe_from_url(url_input)
                        st.session_state.pathao_preview_df = df_res
                        st.session_state.pathao_preview_source = source_mode
                        st.session_state.pathao_auto_process = True
                        st.rerun()
                except Exception as exc:
                    st.error(f"URL fetch failed: {exc}")

    if fetch_live_clicked:
        try:
            preview_df, used_status_filter = _load_processing_orders_from_woocommerce()
            st.session_state.pathao_preview_df = preview_df
            st.session_state.pathao_preview_source = source_mode
            st.session_state.pathao_auto_process = True

            missing = [c for c in REQUIRED_COLUMNS if c not in preview_df.columns]
            valid_file = len(missing) == 0

            if preview_df.empty and used_status_filter:
                st.warning("No WooCommerce rows are currently in `processing` status.")
            else:
                st.success(f"Successfully pulled {len(preview_df)} processing rows.")
        except Exception as exc:
            log_error(exc, context="Pathao WooCommerce Pull")
            st.error(f"Failed to fetch data: {exc}")
    elif uploaded_file:
        try:
            preview_df = read_uploaded(uploaded_file)
            st.session_state.pathao_preview_df = preview_df
            st.session_state.pathao_preview_source = source_mode
            valid_file = render_file_summary(
                uploaded_file, preview_df, REQUIRED_COLUMNS
            )
        except Exception as exc:
            log_error(exc, context="Pathao Upload")
            st.error("Failed to read uploaded file.")
    elif (
        st.session_state.get("pathao_preview_df") is not None
        and st.session_state.get("pathao_preview_source") == source_mode
    ):
        preview_df = st.session_state.pathao_preview_df
        missing = [c for c in REQUIRED_COLUMNS if c not in preview_df.columns]
        valid_file = len(missing) == 0

    if preview_df is not None:
        with st.expander("Preview source data", expanded=False):
            st.dataframe(preview_df.head(50), use_container_width=True)

    run_clicked, clear_clicked = render_action_bar(
        primary_label="Process orders",
        primary_key="pathao_process_btn",
        secondary_label="Clear source data",
        secondary_key="pathao_clear_btn",
    )

    if st.session_state.get("pathao_auto_process"):
        run_clicked = True
        st.session_state.pathao_auto_process = False

    if clear_clicked:
        _reset_pathao_state()
        st.rerun()

    if run_clicked:
        if preview_df is None or not valid_file:
            st.warning("Load a valid source before processing orders.")
        else:
            try:
                with st.status("Processing orders...", expanded=True) as status:
                    st.write("Applying cleanup, district resolution, and address normalization...")
                    result_df = process_orders_dataframe(preview_df)
                    st.session_state.pathao_res_df = result_df
                    save_state()
                    status.update(
                        label="Processing complete", state="complete", expanded=False
                    )
                st.success(f"Processed {len(result_df)} grouped orders.")
            except Exception as exc:
                log_error(exc, context="Pathao Processor")
                st.error("Pathao processing failed. Check System Logs for details.")

    result_df = st.session_state.get("pathao_res_df")
    if result_df is not None:
        with st.expander("Preview output", expanded=True):
            st.dataframe(result_df, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            buf_pathao = BytesIO()
            with pd.ExcelWriter(buf_pathao, engine="xlsxwriter") as writer:
                result_df.to_excel(writer, sheet_name="Pathao", index=False)
                workbook = writer.book
                header_format = workbook.add_format(
                    {
                        "bold": True,
                        "bg_color": "#4F81BD",
                        "font_color": "white",
                        "border": 1,
                    }
                )

                ws = writer.sheets["Pathao"]
                for idx, col in enumerate(result_df.columns):
                    ws.write(0, idx, str(col), header_format)
                    max_len = max(result_df[col].astype(str).map(len).max(), len(str(col))) + 2
                    ws.set_column(idx, idx, min(max_len, 50))

            st.download_button(
                "Download repaired file",
                buf_pathao.getvalue(),
                "Pathao_Final.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )

        with c2:
            if st.button(
                "Generate Verification Links",
                type="secondary",
                use_container_width=True,
            ):
                st.session_state.show_vlink_gen = True

        if st.session_state.get("show_vlink_gen"):
            with st.status("Generating links...", expanded=True):
                import random

                df_v = result_df.copy()
                domain = "https://deencommerce.com/v"
                links = []
                for _, row in df_v.iterrows():
                    token = f"{random.getrandbits(32):08x}"
                    order_id = str(row.get("Order ID", "VERIFY"))
                    links.append(f"{domain}/verify?id={order_id}&token={token}")
                df_v["Verification Link"] = links
                st.session_state.pathao_vlink_df = df_v
                st.success("Verification links generated.")

            vlink_df = st.session_state.get("pathao_vlink_df")
            if vlink_df is not None:
                buf_vlink = BytesIO()
                with pd.ExcelWriter(buf_vlink, engine="xlsxwriter") as writer:
                    vlink_df.to_excel(writer, sheet_name="Verification", index=False)
                    workbook = writer.book
                    header_format = workbook.add_format(
                        {
                            "bold": True,
                            "bg_color": "#4F81BD",
                            "font_color": "white",
                            "border": 1,
                        }
                    )

                    ws = writer.sheets["Verification"]
                    for idx, col in enumerate(vlink_df.columns):
                        ws.write(0, idx, str(col), header_format)
                        max_len = max(vlink_df[col].astype(str).map(len).max(), len(str(col))) + 2
                        ws.set_column(idx, idx, min(max_len, 80))

                st.download_button(
                    "Download Verification Report",
                    buf_vlink.getvalue(),
                    "Deliveries_Verification.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


def _render_item_description_tab():
    section_card(
        "Item Description Helper",
        "Paste one item per line to normalize, sort, and generate the same ItemDesc style used by the bulk order processor.",
    )
    st.caption("Supported formats: `2x Item Name`, `Item Name x2`, `Item Name (2 pcs)`, or `Item Name | SKU123`.")

    raw_items = st.text_area(
        "Manual item input",
        key="pathao_manual_items",
        height=220,
        placeholder="2x Oxford Shirt - Navy | SKU123\nPolo Shirt x1\nJeans (2 pcs)",
    )

    if st.button("Normalize and sort items", type="primary", use_container_width=True, key="pathao_manual_normalize"):
        if not raw_items.strip():
            st.warning("Enter at least one item line.")
        else:
            normalized_items, description = normalize_manual_item_input(raw_items)
            st.session_state.pathao_manual_items_df = pd.DataFrame(normalized_items)
            st.session_state.pathao_manual_desc = description

    normalized_df = st.session_state.get("pathao_manual_items_df")
    manual_desc = st.session_state.get("pathao_manual_desc")

    if normalized_df is not None and not normalized_df.empty:
        display_df = normalized_df.rename(
            columns={"category": "Category", "label": "Normalized Item", "qty": "Qty"}
        )
        with st.expander("Normalized items", expanded=True):
            st.dataframe(display_df, use_container_width=True, hide_index=True)

    if manual_desc:
        from src.components.clipboard import render_copy_button

        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown("#### Generated Item Description")
        with c2:
            render_copy_button(manual_desc, label="Copy ItemDesc")
        st.code(manual_desc)


def render_pathao_tab():
    processing_tab, helper_tab = st.tabs(["Order Processing", "Item Description Helper"])
    with processing_tab:
        _render_processing_tab()
    with helper_tab:
        _render_item_description_tab()
