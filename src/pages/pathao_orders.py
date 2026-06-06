import json
import os
import re
from io import BytesIO
from requests.auth import HTTPBasicAuth

import pandas as pd
import streamlit as st
import plotly.express as px

from src.components.status import render_status_toggle
from src.components.widgets import (
    render_action_bar,
    render_file_summary,
    render_reset_confirm,
    section_card,
)
from src.config.settings import get_pathao_config, get_woocommerce_config
from src.processing.order_processor import (
    normalize_manual_item_input,
    process_orders_dataframe,
)
from src.services.pathao.status import get_pathao_order_status
from src.services.pathao.client import PathaoClient
from src.state.persistence import clear_state_keys, save_state
from src.utils.file_io import read_uploaded
from src.utils.http import request_with_backoff
from src.pages.excel_exporter import export_to_styled_excel
from src.utils.logging import log_error

REQUIRED_COLUMNS = ["Phone (Billing)"]
SOURCE_WOOCOM = "WooCommerce Processing"
SOURCE_UPLOAD = "Upload / URL"


def _get_pathao_client():
    try:
        return PathaoClient(**get_pathao_config(required=True))
    except ValueError as exc:
        st.error(str(exc))
        return None


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
            client = _get_pathao_client()
            if client is None:
                status.update(label="Sync blocked", state="error")
                return
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

        with st.status("Connecting to WooCommerce API...", expanded=True) as status:
            st.write("📡 Fetching live orders...")
            df_live, _, _ = load_live_source()
            status.update(label="WooCommerce Sync Complete", state="complete", expanded=False)
            st.toast("✅ Orders pulled successfully!", icon="🎉")

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
    
    if hasattr(st, "pills"):
        source_mode = st.pills(
            "Select input source",
            [SOURCE_WOOCOM, SOURCE_UPLOAD],
            default=SOURCE_WOOCOM,
            selection_mode="single",
            key="pathao_source_mode",
            label_visibility="collapsed",
        )
        if not source_mode: source_mode = SOURCE_WOOCOM
    else:
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
                    result_df = process_orders_dataframe(preview_df.copy())
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
            def highlight_split_orders(row):
                spec_inst = str(row.get("SpecialInstruction", ""))
                if "PARTIAL ORDER" in spec_inst:
                    return ['background-color: rgba(245, 158, 11, 0.15); color: #b45309; font-weight: bold;'] * len(row)
                if "SPLIT " in spec_inst:
                    return ['background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: bold;'] * len(row)
                return [''] * len(row)
                
            styled_df = result_df.style.apply(highlight_split_orders, axis=1)
            st.dataframe(styled_df, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            pathao_excel_bytes = export_to_styled_excel({"Pathao": result_df}, group_by_col="Order ID")

            st.download_button(
                "Download repaired file",
                pathao_excel_bytes,
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
                vlink_excel_bytes = export_to_styled_excel({"Verification": vlink_df}, group_by_col="Order ID")

                st.download_button(
                    "Download Verification Report",
                    vlink_excel_bytes,
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


def _update_woocommerce_status(order_id, status, note=None):
    """Update WooCommerce order status via API."""
    wc_info = get_woocommerce_config(required=False)
    wc_url = wc_info.get("store_url")
    wc_key = wc_info.get("consumer_key")
    wc_secret = wc_info.get("consumer_secret")
    
    if not all([wc_url, wc_key, wc_secret]):
        return False, "Missing WooCommerce credentials"
        
    url = f"{wc_url.rstrip('/')}/wp-json/wc/v3/orders/{order_id}"
    payload = {"status": status}
    
    try:
        auth = HTTPBasicAuth(wc_key, wc_secret)
        res = request_with_backoff(
            "PUT", url, json=payload, auth=auth, timeout=10
        )
        res.raise_for_status()
        
        if note:
            note_url = f"{url}/notes"
            request_with_backoff(
                "POST",
                note_url,
                json={"note": note, "customer_note": False},
                auth=auth,
                timeout=10,
            )
            
        return True, "Success"
    except Exception as e:
        return False, str(e)


def _extract_woocommerce_order_id(raw_value):
    """Parse a WooCommerce order ID from common exported string formats."""
    text = str(raw_value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None

    match = re.fullmatch(r"(?:#|wc-|order-|invoice-)?(\d+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    if text.isdigit():
        return text

    return None


def _render_status_tracking_tab():
    with st.sidebar:
        st.markdown("### 📡 Tracking Settings")
        
        if hasattr(st, "pills"):
            track_filter = st.pills(
                "Bulk Report Filter",
                ["All Orders", "Failed & Pending Only"],
                default="All Orders",
                selection_mode="single",
                help="Filter out successfully delivered orders from the downloaded report."
            )
            if not track_filter: track_filter = "All Orders"
            
            auto_update_wc = st.pills(
                "Auto-Update WooCommerce",
                ["Disabled", "Enabled"],
                default="Disabled",
                selection_mode="single",
                help="Automatically update WooCommerce order statuses to 'completed' when Pathao marks them as Delivered."
            )
            if not auto_update_wc: auto_update_wc = "Disabled"
        else:
            track_filter = st.radio(
                "Bulk Report Filter",
                ["All Orders", "Failed & Pending Only"],
                index=0,
                help="Filter out successfully delivered orders from the downloaded report."
            )
            auto_update_wc = st.radio(
                "Auto-Update WooCommerce",
                ["Disabled", "Enabled"],
                index=0,
                help="Automatically update WooCommerce order statuses to 'completed' when Pathao marks them as Delivered."
            )

    section_card(
        "Live Order Tracking",
        "Track single or bulk Pathao consignments using your merchant credentials.",
    )

    st.subheader("Single Order Check")
    c_id, c_btn = st.columns([3, 1])
    with c_id:
        consignment_id = st.text_input("Consignment ID or Order ID", placeholder="e.g., DD0000000 or 199697", key="pathao_single_track")
    with c_btn:
        st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
        check_clicked = st.button("Check Status", use_container_width=True, type="primary", key="pathao_track_btn")

    if check_clicked and consignment_id:
        search_term = consignment_id.strip()
        
        # Auto-detect if it's a numeric WooCommerce Order ID instead of a Consignment ID
        if search_term.isdigit() and len(search_term) < 10:
            st.info(f"Detected WooCommerce Order ID format. Redirecting to Search...")
            with st.spinner(f"Searching Pathao orders for '{search_term}'..."):
                try:
                    client = _get_pathao_client()
                    if client is not None:
                        headers = client._get_headers()
                        search_url = f"{client.base_url}/aladdin/api/v1/orders"
                        res = request_with_backoff("GET", search_url, headers=headers, params={"search": search_term}, timeout=15)
                        res.raise_for_status()
                        orders = res.json().get("data", {}).get("data", [])
                        
                        if not orders:
                            st.error(f"No Pathao orders found matching Order ID '{search_term}'.")
                        else:
                            st.success(f"Found order status successfully!")
                            o = orders[0] # Show the first match
                            status_val = str(o.get("order_status", "N/A")).capitalize()
                            payment_val = str(o.get("payment_status", "N/A")).capitalize()
                            collected_val = f"৳{float(o.get('collected_amount', 0)):,.0f}" if str(o.get('collected_amount', 0)).replace('.','',1).isdigit() else f"৳{o.get('collected_amount', 0)}"

                            st.markdown(f"""
                            <div class="metric-container" style="animation: slideUpFade 0.5s ease-out forwards;">
                                <div class="metric-card">
                                    <div class="metric-content">
                                        <div class="metric-label">Order Status</div>
                                        <div class="metric-value" style="font-size: 1.5rem;">{status_val}</div>
                                    </div>
                                    <div class="metric-icon">📦</div>
                                </div>
                                <div class="metric-card">
                                    <div class="metric-content">
                                        <div class="metric-label">Payment Status</div>
                                        <div class="metric-value" style="font-size: 1.5rem;">{payment_val}</div>
                                    </div>
                                    <div class="metric-icon">💳</div>
                                </div>
                                <div class="metric-card">
                                    <div class="metric-content">
                                        <div class="metric-label">Collected Amount</div>
                                        <div class="metric-value" style="font-size: 1.5rem;">{collected_val}</div>
                                    </div>
                                    <div class="metric-icon">💰</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            with st.expander("View Full Details"):
                                st.json(o)
                except Exception as e:
                    st.error(f"Search failed: {e}")
        else:
            with st.spinner("Fetching status by Consignment ID..."):
                status_data = get_pathao_order_status(search_term)
                if "error" in status_data:
                    # Provide a better hint for 401/404 errors on invalid IDs
                    if "401" in status_data["error"] or "404" in status_data["error"]:
                        st.error("Error: Pathao rejected this ID. Make sure it's a valid Consignment ID (e.g., DD1234...). For Order IDs, use the search box below.")
                    else:
                        st.error(status_data["error"])
                else:
                    st.success("Status retrieved successfully!")
                    data_obj = status_data.get("data", {})
                    
                    status_val = str(data_obj.get("order_status", "N/A")).capitalize()
                    payment_val = str(data_obj.get("payment_status", "N/A")).capitalize()
                    collected_val = f"৳{float(data_obj.get('collected_amount', 0)):,.0f}" if str(data_obj.get('collected_amount', 0)).replace('.','',1).isdigit() else f"৳{data_obj.get('collected_amount', 0)}"

                    st.markdown(f"""
                    <div class="metric-container" style="animation: slideUpFade 0.5s ease-out forwards;">
                        <div class="metric-card">
                            <div class="metric-content">
                                <div class="metric-label">Order Status</div>
                                <div class="metric-value" style="font-size: 1.5rem;">{status_val}</div>
                            </div>
                            <div class="metric-icon">📦</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-content">
                                <div class="metric-label">Payment Status</div>
                                <div class="metric-value" style="font-size: 1.5rem;">{payment_val}</div>
                            </div>
                            <div class="metric-icon">💳</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-content">
                                <div class="metric-label">Collected Amount</div>
                                <div class="metric-value" style="font-size: 1.5rem;">{collected_val}</div>
                            </div>
                            <div class="metric-icon">💰</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander("View Full API Response"):
                        st.json(status_data)

    st.divider()

    st.subheader("Search by Order ID or Phone")
    st.write("Search Pathao to track a specific WooCommerce Order ID or check a customer's history by Phone.")
    c_search, c_search_btn = st.columns([3, 1])
    with c_search:
        search_input = st.text_input("Order ID or Phone", placeholder="e.g. 193252 or 01700000000", key="search_check_input")
    with c_search_btn:
        st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
        search_clicked = st.button("Search Pathao", use_container_width=True, type="secondary", key="search_check_btn")

    if search_clicked and search_input:
        with st.spinner("Searching Pathao orders..."):
            try:
                client = _get_pathao_client()
                if client is not None:
                    headers = client._get_headers()

                    search_url = f"{client.base_url}/aladdin/api/v1/orders"
                    params = {"search": search_input.strip()}

                    res = request_with_backoff(
                        "GET",
                        search_url,
                        headers=headers,
                        params=params,
                        timeout=15,
                    )
                    res.raise_for_status()
                    response_json = res.json()

                    data_obj = response_json.get("data", {})
                    orders = (
                        data_obj.get("data", []) if isinstance(data_obj, dict) else []
                    )

                    if not orders:
                        st.info("No orders found in Pathao for this search query.")
                    else:
                        st.success(f"Found {len(orders)} order(s) matching '{search_input}'.")
                        history_data = []
                        for o in orders:
                            amount_str = f"৳{float(o.get('collected_amount', 0)):,.0f}" if str(o.get('collected_amount', 0)).replace('.','',1).isdigit() else f"৳{o.get('collected_amount', 0)}"
                            history_data.append({
                                "Consignment ID": o.get("consignment_id", ""),
                                "Order ID": o.get("merchant_order_id", ""),
                                "Date": str(o.get("created_at", "")).split(" ")[0],
                                "Status": str(o.get("order_status", "")).capitalize(),
                                "Amount": amount_str
                            })
                        
                        df_history = pd.DataFrame(history_data)
                        def highlight_status(col):
                            return [
                                'background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 600;' 
                                if any(x in str(v).lower() for x in ['return', 'failed', 'cancel', 'error'])
                                else 'color: #10b981; font-weight: 600;' if 'delivered' in str(v).lower()
                                else 'color: #3b82f6; font-weight: 500;' if any(x in str(v).lower() for x in ['transit', 'processing', 'assigned'])
                                else ''
                                for v in col
                            ]
                        st.dataframe(df_history.style.apply(highlight_status, subset=['Status']), use_container_width=True)
            except Exception as e:
                st.error(f"Error searching Pathao: {e}")

    st.divider()

    st.subheader("Recent Orders Overview")
    st.write("Fetch the most recent orders directly from Pathao to quickly see what has been delivered, returned, or is still in transit.")
    if st.button("Fetch Last 50 Pathao Orders", use_container_width=True, key="pathao_recent_btn"):
        with st.spinner("Fetching recent orders..."):
            try:
                client = _get_pathao_client()
                if client is not None:
                    headers = client._get_headers()
                    search_url = f"{client.base_url}/aladdin/api/v1/orders"
                    res = request_with_backoff("GET", search_url, headers=headers, timeout=15)
                    res.raise_for_status()
                    orders = res.json().get("data", {}).get("data", [])
                    if not orders:
                        st.info("No recent orders found.")
                    else:
                        st.success(f"Successfully retrieved the last {len(orders)} orders.")
                        history_data = []
                        for o in orders:
                            amount_str = f"৳{float(o.get('collected_amount', 0)):,.0f}" if str(o.get('collected_amount', 0)).replace('.','',1).isdigit() else f"৳{o.get('collected_amount', 0)}"
                            history_data.append({
                                "Consignment ID": o.get("consignment_id", ""),
                                "Order ID": o.get("merchant_order_id", ""),
                                "Date": str(o.get("created_at", "")).split(" ")[0],
                                "Status": str(o.get("order_status", "")).capitalize(),
                                "Amount": amount_str
                            })
                        
                        df_history = pd.DataFrame(history_data)
                        def highlight_status(col):
                            return [
                                'background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 600;' 
                                if any(x in str(v).lower() for x in ['return', 'failed', 'cancel', 'error'])
                                else 'color: #10b981; font-weight: 600;' if 'delivered' in str(v).lower()
                                else 'color: #3b82f6; font-weight: 500;' if any(x in str(v).lower() for x in ['transit', 'processing', 'assigned'])
                                else ''
                                for v in col
                            ]
                        st.dataframe(df_history.style.apply(highlight_status, subset=['Status']), use_container_width=True)
            except Exception as e:
                st.error(f"Error fetching recent orders: {e}")

    st.divider()

    st.subheader("Bulk Status Check")
    st.write("Upload an Excel/CSV file containing Consignment IDs to bulk-check their current status.")
    bulk_file = st.file_uploader("Upload tracking file", type=["xlsx", "csv"], key="pathao_bulk_up")

    if bulk_file:
        try:
            bulk_df = read_uploaded(bulk_file)
            cols = list(bulk_df.columns)
            
            guess_idx = 0
            for i, c in enumerate(cols):
                if any(kw in str(c).lower() for kw in ["consignment", "tracking", "id"]):
                    guess_idx = i
                    break

            c_col, c_run = st.columns([3, 1])
            with c_col:
                id_col = st.selectbox("Select Consignment ID Column", cols, index=guess_idx)
            with c_run:
                st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
                run_bulk = st.button("Run Bulk Check", use_container_width=True, type="primary", key="pathao_bulk_btn")

            if run_bulk:
                order_id_col = next((c for c in cols if "order" in str(c).lower() and "merchant" in str(c).lower()), None)
                if not order_id_col:
                    order_id_col = next((c for c in cols if "order" in str(c).lower() or "invoice" in str(c).lower()), None)
                
                if auto_update_wc == "Enabled" and not order_id_col:
                    st.warning("⚠️ Auto-Update is enabled, but no 'Order ID' column was detected in your file. WooCommerce updates will be skipped.")

                with st.status("Fetching bulk statuses...", expanded=True) as status_ui:
                    results = []
                    status_cache = {}
                    updated_order_ids = set()
                    progress_bar = st.progress(0)
                    total = len(bulk_df)
                    
                    for i, row in bulk_df.iterrows():
                        cid = str(row[id_col]).strip()
                        row_copy = row.to_dict()
                        
                        if cid and cid.lower() not in ["nan", "none", ""]:
                            if cid not in status_cache:
                                status_cache[cid] = get_pathao_order_status(cid)
                            res = status_cache[cid]
                            if "error" in res:
                                row_copy["Live Status"] = "Error"
                                row_copy["Status Reason"] = res["error"]
                                row_copy["Payment Status"] = ""
                            else:
                                data = res.get("data", {})
                                live_status = data.get("order_status", "Unknown")
                                row_copy["Live Status"] = live_status
                                row_copy["Status Reason"] = data.get("reason", "")
                                row_copy["Payment Status"] = data.get("payment_status", "")
                                
                                if auto_update_wc == "Enabled" and order_id_col and "delivered" in live_status.lower():
                                    wc_id = _extract_woocommerce_order_id(row_copy.get(order_id_col, ""))
                                    if wc_id:
                                        if wc_id in updated_order_ids:
                                            row_copy["WC Update"] = "Skipped (already updated in this run)"
                                            results.append(row_copy)
                                            progress_bar.progress((i + 1) / total)
                                            continue

                                        success, msg = _update_woocommerce_status(
                                            wc_id, 
                                            "completed", 
                                            f"Auto-updated by DEEN-OPS: Pathao Consignment {cid} marked as Delivered."
                                        )
                                        if success:
                                            updated_order_ids.add(wc_id)
                                        row_copy["WC Update"] = "Success" if success else f"Failed: {msg}"
                                    else:
                                        row_copy["WC Update"] = "Invalid Order ID"
                        else:
                            row_copy["Live Status"] = "Invalid ID"
                            row_copy["Status Reason"] = ""
                            row_copy["Payment Status"] = ""

                        results.append(row_copy)
                        progress_bar.progress((i + 1) / total)

                    status_ui.update(label="Bulk check complete!", state="complete", expanded=False)

                updated_df = pd.DataFrame(results)
                st.session_state["pathao_bulk_result_df"] = updated_df
                
                total_orders = len(updated_df)
                delivered = len(updated_df[updated_df["Live Status"].astype(str).str.lower().str.contains("delivered")])
                failed = len(updated_df[updated_df["Live Status"].astype(str).str.lower().str.contains("return|failed|cancel|error")])
                in_transit = total_orders - delivered - failed
                
                st.markdown(f"""
                <div class="metric-container metric-container-4" style="animation: slideUpFade 0.5s ease-out forwards;">
                    <div class="metric-card">
                        <div class="metric-content">
                            <div class="metric-label">Total Tracked</div>
                            <div class="metric-value" style="font-size: 1.5rem;">{total_orders}</div>
                        </div>
                        <div class="metric-icon">📋</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-content">
                            <div class="metric-label">Delivered</div>
                            <div class="metric-value" style="font-size: 1.5rem; color: #10b981;">{delivered}</div>
                        </div>
                        <div class="metric-icon">✅</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-content">
                            <div class="metric-label">In Transit</div>
                            <div class="metric-value" style="font-size: 1.5rem; color: #3b82f6;">{in_transit}</div>
                        </div>
                        <div class="metric-icon">🚚</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-content">
                            <div class="metric-label">Failed / Return</div>
                            <div class="metric-value" style="font-size: 1.5rem; color: #ef4444;">{failed}</div>
                        </div>
                        <div class="metric-icon">❌</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("#### 📊 Delivery Ratios")
                status_summary = updated_df["Live Status"].value_counts().reset_index()
                status_summary.columns = ["Status", "Count"]

                color_map = {}
                for status in status_summary["Status"]:
                    s_lower = str(status).lower()
                    if any(x in s_lower for x in ['return', 'failed', 'cancel', 'error']):
                        color_map[status] = '#ef4444'
                    elif 'delivered' in s_lower:
                        color_map[status] = '#10b981'
                    elif any(x in s_lower for x in ['transit', 'processing', 'assigned']):
                        color_map[status] = '#3b82f6'
                    else:
                        color_map[status] = '#f59e0b'

                fig = px.pie(status_summary, names="Status", values="Count", hole=0.5, color="Status", color_discrete_map=color_map)
                fig.update_traces(textposition='inside', textinfo='percent+label')
                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), showlegend=False, height=350)
                
                c_pie, _ = st.columns([1, 2])
                with c_pie:
                    st.plotly_chart(fig, use_container_width=True)

                if track_filter == "Failed & Pending Only":
                    updated_df = updated_df[~updated_df["Live Status"].astype(str).str.lower().str.contains("delivered")]
                    st.info(f"Filtered out delivered orders. Showing {len(updated_df)} remaining orders.")

                def highlight_live_status(col):
                    return [
                        'background-color: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 600;' 
                        if any(x in str(v).lower() for x in ['return', 'failed', 'cancel', 'error'])
                        else 'color: #10b981; font-weight: 600;' if 'delivered' in str(v).lower()
                        else 'color: #3b82f6; font-weight: 500;' if any(x in str(v).lower() for x in ['transit', 'processing', 'assigned'])
                        else ''
                        for v in col
                    ]

                styled_df = updated_df.style.apply(highlight_live_status, subset=['Live Status'])
                st.dataframe(styled_df, use_container_width=True)
                
                bulk_status_excel_bytes = export_to_styled_excel({"Live_Statuses": updated_df})

                st.download_button(
                    "Download Updated Report",
                    bulk_status_excel_bytes,
                    "Bulk_Statuses.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )

        except Exception as e:
            log_error(e, context="Pathao Bulk Track")
            st.error(f"Error processing file: {e}")



def _render_auto_dispatch_tab():
    """Feature #1: Push processed Pathao orders directly via Pathao API (bulk create)."""
    section_card(
        "Auto-Dispatch to Pathao — One-Click API Push",
        "Automatically create consignments on Pathao for all processed orders without manual portal upload.",
    )

    result_df = st.session_state.get("pathao_res_df")
    if result_df is None or result_df.empty:
        st.info("⚡ No processed orders found. Go to **Order Processing** tab first, pull orders and run 'Process orders'.")
        return

    st.success(f"✅ {len(result_df)} processed orders ready for dispatch.")

    with st.expander("📄 Preview Orders for Dispatch", expanded=False):
        st.dataframe(result_df.head(20), use_container_width=True)

    with st.expander("⚙️ Dispatch Settings", expanded=True):
        dc1, dc2, dc3 = st.columns(3)
        with dc1:
            item_type = st.selectbox("Item Type", [2, 1, 3], format_func=lambda x: {2: "Parcel", 1: "Document", 3: "Fragile"}[x])
        with dc2:
            delivery_type = st.selectbox("Delivery Type", [48, 12], format_func=lambda x: {48: "Normal (48h)", 12: "Express (12h)"}[x])
        with dc3:
            special_instructions = st.text_input("Special Instructions", placeholder="Handle with care...")

    if st.button("🚀 Push to Pathao API", type="primary", use_container_width=True, key="pathao_autodispatch_btn"):
        client = _get_pathao_client()
        if client is None:
            return

        success_count = 0
        fail_count = 0
        fail_details = []

        with st.status(f"Dispatching {len(result_df)} orders to Pathao...", expanded=True) as dispatch_status:
            progress = st.progress(0)
            total = len(result_df)

            for i, (_, row) in enumerate(result_df.iterrows()):
                try:
                    # Build Pathao order payload from processed dataframe columns
                    payload = {
                        "merchant_order_id": str(row.get("Order ID", f"ORD-{i}")),
                        "recipient_name": str(row.get("Name", "Customer")),
                        "recipient_phone": str(row.get("Phone", "")).replace(" ", ""),
                        "recipient_address": str(row.get("Address", "")),
                        "recipient_city": int(row.get("CityId", 1)),
                        "recipient_zone": int(row.get("ZoneId", 1)),
                        "recipient_area": int(row.get("AreaId", 0)) if row.get("AreaId") else None,
                        "delivery_type": delivery_type,
                        "item_type": item_type,
                        "special_instruction": str(row.get("SpecialInstruction", special_instructions)),
                        "item_quantity": int(row.get("Qty", 1)),
                        "item_weight": float(row.get("Weight", 0.5)),
                        "amount_to_collect": float(row.get("COD", row.get("Total", 0))),
                        "item_description": str(row.get("ItemDesc", "")),
                    }
                    # Remove None fields
                    payload = {k: v for k, v in payload.items() if v is not None and v != ""}

                    headers = client._get_headers()
                    from src.utils.http import request_with_backoff
                    res = request_with_backoff(
                        "POST",
                        f"{client.base_url}/aladdin/api/v1/orders",
                        json=payload,
                        headers=headers,
                        timeout=15,
                    )
                    res.raise_for_status()
                    resp_data = res.json().get("data", {})
                    consignment_id = resp_data.get("consignment_id", "Created")
                    st.write(f"✅ Order {payload['merchant_order_id']} → Consignment: {consignment_id}")
                    success_count += 1
                except Exception as exc:
                    fail_count += 1
                    fail_details.append({"Order": str(row.get("Order ID", i)), "Error": str(exc)})
                    st.write(f"❌ Order {row.get('Order ID', i)}: {exc}")

                progress.progress((i + 1) / total)

            if fail_count == 0:
                dispatch_status.update(label=f"✅ All {success_count} orders dispatched!", state="complete", expanded=False)
            else:
                dispatch_status.update(label=f"⚠️ {success_count} dispatched, {fail_count} failed", state="error", expanded=True)

        if fail_details:
            with st.expander(f"❌ {fail_count} Failed Orders"):
                st.dataframe(pd.DataFrame(fail_details), use_container_width=True)


def _render_delivery_health_tab():
    """Feature #2: Delivery Health Dashboard — return rates, delivery rates, district breakdown."""
    section_card(
        "Delivery Health Dashboard",
        "Analyze delivery rates, return rates, and average delivery time from your bulk tracking history.",
    )

    bulk_df_key = "pathao_bulk_result_df"
    bulk_df = st.session_state.get(bulk_df_key)

    if bulk_df is None:
        st.info("📊 No bulk tracking data available. Run a Bulk Status Check in the **Order Tracking** tab first.")
        return

    if "Live Status" not in bulk_df.columns:
        st.warning("⚠️ The loaded data doesn't have a 'Live Status' column. Please run a fresh bulk check.")
        return

    total = len(bulk_df)
    status_series = bulk_df["Live Status"].astype(str).str.lower()

    delivered = status_series.str.contains("delivered").sum()
    returned = status_series.str.contains("return").sum()
    failed = status_series.str.contains("fail|cancel").sum()
    in_transit = total - delivered - returned - failed

    delivery_rate = delivered / total * 100 if total > 0 else 0
    return_rate = returned / total * 100 if total > 0 else 0

    # KPI Cards
    health_html = (
        '<div class="metric-container metric-container-4">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">DELIVERY RATE</div>'
        f'<div class="metric-value" style="color:#10b981;">{delivery_rate:.1f}%</div></div><div class="metric-icon">✅</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">RETURN RATE</div>'
        f'<div class="metric-value" style="color:#ef4444;">{return_rate:.1f}%</div></div><div class="metric-icon">🔄</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">IN TRANSIT</div>'
        f'<div class="metric-value" style="color:#3b82f6;">{in_transit}</div></div><div class="metric-icon">🚚</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">TOTAL TRACKED</div>'
        f'<div class="metric-value">{total}</div></div><div class="metric-icon">📦</div></div>'
        '</div>'
    )
    st.markdown(health_html, unsafe_allow_html=True)

    # Status Donut
    import plotly.graph_objects as go
    fig_donut = go.Figure(go.Pie(
        labels=["Delivered", "Returned", "Failed/Cancelled", "In Transit"],
        values=[delivered, returned, failed, in_transit],
        hole=0.55,
        marker_colors=["#10b981", "#ef4444", "#f59e0b", "#3b82f6"],
        textinfo="label+percent",
        hovertemplate="%{label}: %{value} orders (%{percent})<extra></extra>",
    ))
    fig_donut.update_layout(title="Dispatch Status Breakdown", margin=dict(l=10, r=10, t=40, b=10), height=320, showlegend=False)

    d1, d2 = st.columns(2)
    with d1:
        st.plotly_chart(fig_donut, use_container_width=True, config={"displayModeBar": False})

    with d2:
        # District breakdown if address / district col is available
        dist_col = next((c for c in bulk_df.columns if any(kw in str(c).lower() for kw in ["city", "district", "zone"])), None)
        if dist_col:
            dist_df = bulk_df.groupby(dist_col)["Live Status"].agg(
                total="count",
                delivered=lambda s: s.astype(str).str.lower().str.contains("delivered").sum(),
                returned=lambda s: s.astype(str).str.lower().str.contains("return").sum(),
            ).reset_index()
            dist_df["Delivery Rate %"] = (dist_df["delivered"] / dist_df["total"] * 100).round(1)
            dist_df = dist_df.sort_values("total", ascending=False).head(10)
            fig_dist = px.bar(
                dist_df, x=dist_col, y=["delivered", "returned"],
                title="Delivery vs Return by District",
                color_discrete_sequence=["#10b981", "#ef4444"],
                barmode="stack",
            )
            fig_dist.update_layout(margin=dict(l=10, r=10, t=40, b=30), height=320, showlegend=True)
            st.plotly_chart(fig_dist, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No city/district column detected for district-level breakdown.")

    # Action: Flag high-return orders
    if return_rate > 15:
        st.error(f"⚠️ High Return Rate Detected: {return_rate:.1f}%. Review addresses and product quality.")

    with st.expander("📊 Full Health Report"):
        st.dataframe(bulk_df, use_container_width=True)


def _render_wc_notes_tab():
    """Feature #9: Write WooCommerce order notes/status updates from within DEEN OPS."""
    section_card(
        "WooCommerce Order Notes Sync",
        "Write dispatch notes or update order statuses directly back to WooCommerce without opening the admin portal.",
    )

    nc1, nc2 = st.columns(2)
    with nc1:
        order_id_note = st.text_input("WooCommerce Order ID", placeholder="e.g. 4821", key="wc_note_order_id")
    with nc2:
        new_status = st.selectbox(
            "New Status (optional)",
            ["— Don't change status —", "processing", "completed", "on-hold", "cancelled"],
            key="wc_note_status_sel",
        )

    note_text = st.text_area(
        "Note / Message",
        placeholder="e.g. Dispatched via Pathao. Consignment: DD0001234. ETA: 2 days.",
        height=100,
        key="wc_note_text",
    )

    col_send, col_quick = st.columns(2)
    with col_send:
        if st.button("💬 Post Note to WooCommerce", type="primary", use_container_width=True, key="wc_note_send_btn"):
            if not order_id_note.strip():
                st.warning("Enter a WooCommerce Order ID.")
            else:
                target_status = None if new_status.startswith("—") else new_status
                with st.spinner("Posting to WooCommerce..."):
                    ok, msg = _update_woocommerce_status(
                        order_id_note.strip(),
                        target_status or "processing",
                        note=note_text.strip() or None,
                    )
                if ok:
                    st.success(f"✅ Note posted to Order #{order_id_note} successfully.")
                else:
                    st.error(f"❌ Failed: {msg}")

    with col_quick:
        # Quick dispatch note from Pathao result
        result_df_n = st.session_state.get("pathao_res_df")
        if result_df_n is not None and not result_df_n.empty:
            if st.button("🚚 Bulk: Post Dispatch Notes", type="secondary", use_container_width=True, key="wc_bulk_notes_btn"):
                ok_count = 0
                fail_count = 0
                progress_n = st.progress(0)
                total_n = len(result_df_n)
                for i, (_, row) in enumerate(result_df_n.iterrows()):
                    wc_id = str(row.get("Order ID", "")).strip()
                    if not wc_id or wc_id.lower() in {"nan", "none"}:
                        continue
                    parsed_id = _extract_woocommerce_order_id(wc_id)
                    if not parsed_id:
                        continue
                    note_auto = f"Dispatched via Pathao. Items: {row.get('ItemDesc', 'N/A')}. COD: ৳{row.get('COD', 0)}."
                    ok_n, _ = _update_woocommerce_status(parsed_id, "processing", note=note_auto)
                    if ok_n:
                        ok_count += 1
                    else:
                        fail_count += 1
                    progress_n.progress((i + 1) / total_n)
                st.success(f"✅ {ok_count} notes posted. {fail_count} failed.")
        else:
            st.caption("💡 Process orders in the Order Processing tab to enable bulk dispatch notes.")

    st.divider()
    st.markdown("#### 🗒️ Quick Note Templates")
    templates = [
        ("🚚 Dispatched", "Dispatched via Pathao. Expected delivery: 2-3 business days."),
        ("❌ Cancelled", "Order cancelled per customer request. Refund initiated."),
        ("🔄 On Hold", "Order placed on hold pending stock confirmation."),
        ("✅ Delivered", "Order delivered successfully. Payment collected."),
    ]
    for label, tmpl in templates:
        if st.button(label, key=f"wc_tmpl_{label}", use_container_width=True):
            st.session_state["wc_note_text"] = tmpl
            st.rerun()


def render_pathao_tab():
    processing_tab, helper_tab, tracking_tab, dispatch_tab, health_tab, notes_tab = st.tabs([
        ":material/settings: Order Processing",
        ":material/build: Item Description Helper",
        ":material/local_shipping: Order Tracking",
        ":material/rocket_launch: Auto-Dispatch",
        ":material/analytics: Delivery Health",
        ":material/edit_note: WC Notes Sync",
    ])
    with processing_tab:
        _render_processing_tab()
    with helper_tab:
        _render_item_description_tab()
    with tracking_tab:
        _render_status_tracking_tab()
    with dispatch_tab:
        _render_auto_dispatch_tab()
    with health_tab:
        _render_delivery_health_tab()
    with notes_tab:
        _render_wc_notes_tab()
