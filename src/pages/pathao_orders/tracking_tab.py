"""Order Tracking tab: live status refresh, bulk report, and WC auto-updates."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.components.ui.dataframe_search import render_dataframe_search
from src.components.ui.widgets import section_card
from src.pages.pathao_orders.shared import _get_pathao_client, _highlight_status
from src.services.exports.excel_exporter import export_to_styled_excel
from src.services.pathao.status import get_pathao_order_status
from src.services.woocommerce.orders import extract_order_id, update_order_status
from src.utils.file_io import read_uploaded
from src.utils.http import request_with_backoff
from src.utils.logging import log_error


def _render_status_tracking_tab():
    with st.sidebar:
        st.markdown("### 📡 Tracking Settings")

        if hasattr(st, "pills"):
            track_filter = st.pills(
                "Bulk Report Filter",
                ["All Orders", "Failed & Pending Only"],
                default="All Orders",
                selection_mode="single",
                help="Filter out successfully delivered orders from the downloaded report.",
            )
            if not track_filter:
                track_filter = "All Orders"

            auto_update_wc = st.pills(
                "Auto-Update WooCommerce",
                ["Disabled", "Enabled"],
                default="Disabled",
                selection_mode="single",
                help="Automatically update WooCommerce order statuses to 'completed' when Pathao marks them as Delivered.",
            )
            if not auto_update_wc:
                auto_update_wc = "Disabled"
        else:
            track_filter = st.radio(
                "Bulk Report Filter",
                ["All Orders", "Failed & Pending Only"],
                index=0,
                help="Filter out successfully delivered orders from the downloaded report.",
            )
            auto_update_wc = st.radio(
                "Auto-Update WooCommerce",
                ["Disabled", "Enabled"],
                index=0,
                help="Automatically update WooCommerce order statuses to 'completed' when Pathao marks them as Delivered.",
            )

    section_card(
        "Live Order Tracking",
        "Track single or bulk Pathao consignments using your merchant credentials.",
    )

    st.subheader("Single Order Check")
    c_id, c_btn = st.columns([3, 1])
    with c_id:
        consignment_id = st.text_input(
            "Consignment ID or Order ID",
            placeholder="e.g., DD0000000 or 199697",
            key="pathao_single_track",
        )
    with c_btn:
        st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
        check_clicked = st.button(
            "Check Status",
            use_container_width=True,
            type="primary",
            key="pathao_track_btn",
        )

    if check_clicked and consignment_id:
        search_term = consignment_id.strip()

        # Auto-detect if it's a numeric WooCommerce Order ID instead of a Consignment ID
        if search_term.isdigit() and len(search_term) < 10:
            st.info("Detected WooCommerce Order ID format. Redirecting to Search...")
            with st.spinner(f"Searching Pathao orders for '{search_term}'..."):
                try:
                    client = _get_pathao_client()
                    if client is not None:
                        headers = client._get_headers()
                        search_url = f"{client.base_url}/aladdin/api/v1/orders"
                        res = request_with_backoff(
                            "GET",
                            search_url,
                            headers=headers,
                            params={"search": search_term},
                            timeout=15,
                        )
                        res.raise_for_status()
                        orders = res.json().get("data", {}).get("data", [])

                        if not orders:
                            st.error(
                                f"No Pathao orders found matching Order ID '{search_term}'."
                            )
                        else:
                            st.toast("✅ Found order status successfully!")
                            o = orders[0]  # Show the first match
                            status_val = str(o.get("order_status", "N/A")).capitalize()
                            payment_val = str(
                                o.get("payment_status", "N/A")
                            ).capitalize()
                            collected_val = (
                                f"৳{float(o.get('collected_amount', 0)):,.0f}"
                                if str(o.get("collected_amount", 0))
                                .replace(".", "", 1)
                                .isdigit()
                                else f"৳{o.get('collected_amount', 0)}"
                            )

                            st.markdown(
                                f"""
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
                            """,
                                unsafe_allow_html=True,
                            )
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
                        st.error(
                            "Error: Pathao rejected this ID. Make sure it's a valid Consignment ID (e.g., DD1234...). For Order IDs, use the search box below."
                        )
                    else:
                        st.error(status_data["error"])
                else:
                    st.toast("✅ Status retrieved successfully!")
                    data_obj = status_data.get("data", {})

                    status_val = str(data_obj.get("order_status", "N/A")).capitalize()
                    payment_val = str(
                        data_obj.get("payment_status", "N/A")
                    ).capitalize()
                    collected_val = (
                        f"৳{float(data_obj.get('collected_amount', 0)):,.0f}"
                        if str(data_obj.get("collected_amount", 0))
                        .replace(".", "", 1)
                        .isdigit()
                        else f"৳{data_obj.get('collected_amount', 0)}"
                    )

                    st.markdown(
                        f"""
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
                    """,
                        unsafe_allow_html=True,
                    )

                    with st.expander("View Full API Response"):
                        st.json(status_data)

    st.divider()

    st.subheader("Search by Order ID or Phone")
    st.write(
        "Search Pathao to track a specific WooCommerce Order ID or check a customer's history by Phone."
    )
    c_search, c_search_btn = st.columns([3, 1])
    with c_search:
        search_input = st.text_input(
            "Order ID or Phone",
            placeholder="e.g. 193252 or 01700000000",
            key="search_check_input",
        )
    with c_search_btn:
        st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
        search_clicked = st.button(
            "Search Pathao",
            use_container_width=True,
            type="secondary",
            key="search_check_btn",
        )

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
                        st.toast(
                            f"✅ Found {len(orders)} order(s) matching '{search_input}'."
                        )
                        history_data = []
                        for o in orders:
                            amount_str = (
                                f"৳{float(o.get('collected_amount', 0)):,.0f}"
                                if str(o.get("collected_amount", 0))
                                .replace(".", "", 1)
                                .isdigit()
                                else f"৳{o.get('collected_amount', 0)}"
                            )
                            history_data.append(
                                {
                                    "Consignment ID": o.get("consignment_id", ""),
                                    "Order ID": o.get("merchant_order_id", ""),
                                    "Date": str(o.get("created_at", "")).split(" ")[0],
                                    "Status": str(
                                        o.get("order_status", "")
                                    ).capitalize(),
                                    "Amount": amount_str,
                                }
                            )

                        df_history = pd.DataFrame(history_data)
                        st.dataframe(
                            df_history.style.apply(
                                _highlight_status, subset=["Status"]
                            ),
                            use_container_width=True,
                        )
            except Exception as e:
                st.error(f"Error searching Pathao: {e}")

    st.divider()

    st.subheader("Recent Orders Overview")
    st.write(
        "Fetch the most recent orders directly from Pathao to quickly see what has been delivered, returned, or is still in transit."
    )
    if st.button(
        "Fetch Last 50 Pathao Orders", use_container_width=True, key="pathao_recent_btn"
    ):
        with st.spinner("Fetching recent orders..."):
            try:
                client = _get_pathao_client()
                if client is not None:
                    headers = client._get_headers()
                    search_url = f"{client.base_url}/aladdin/api/v1/orders"
                    res = request_with_backoff(
                        "GET", search_url, headers=headers, timeout=15
                    )
                    res.raise_for_status()
                    orders = res.json().get("data", {}).get("data", [])
                    if not orders:
                        st.info("No recent orders found.")
                    else:
                        st.toast(
                            f"✅ Successfully retrieved the last {len(orders)} orders."
                        )
                        history_data = []
                        for o in orders:
                            amount_str = (
                                f"৳{float(o.get('collected_amount', 0)):,.0f}"
                                if str(o.get("collected_amount", 0))
                                .replace(".", "", 1)
                                .isdigit()
                                else f"৳{o.get('collected_amount', 0)}"
                            )
                            history_data.append(
                                {
                                    "Consignment ID": o.get("consignment_id", ""),
                                    "Order ID": o.get("merchant_order_id", ""),
                                    "Date": str(o.get("created_at", "")).split(" ")[0],
                                    "Status": str(
                                        o.get("order_status", "")
                                    ).capitalize(),
                                    "Amount": amount_str,
                                }
                            )

                        df_history = pd.DataFrame(history_data)
                        st.dataframe(
                            df_history.style.apply(
                                _highlight_status, subset=["Status"]
                            ),
                            use_container_width=True,
                        )
            except Exception as e:
                st.error(f"Error fetching recent orders: {e}")

    st.divider()

    st.subheader("Bulk Status Check")
    st.write(
        "Upload an Excel/CSV file containing Consignment IDs to bulk-check their current status."
    )
    bulk_file = st.file_uploader(
        "Upload tracking file", type=["xlsx", "csv"], key="pathao_bulk_up"
    )

    if bulk_file:
        try:
            bulk_df = read_uploaded(bulk_file)
            cols = list(bulk_df.columns)

            guess_idx = 0
            for i, c in enumerate(cols):
                if any(
                    kw in str(c).lower() for kw in ["consignment", "tracking", "id"]
                ):
                    guess_idx = i
                    break

            c_col, c_run = st.columns([3, 1])
            with c_col:
                id_col = st.selectbox(
                    "Select Consignment ID Column", cols, index=guess_idx
                )
            with c_run:
                st.markdown(
                    '<div style="margin-top: 28px;"></div>', unsafe_allow_html=True
                )
                run_bulk = st.button(
                    "Run Bulk Check",
                    use_container_width=True,
                    type="primary",
                    key="pathao_bulk_btn",
                )

            if run_bulk:
                order_id_col = next(
                    (
                        c
                        for c in cols
                        if "order" in str(c).lower() and "merchant" in str(c).lower()
                    ),
                    None,
                )
                if not order_id_col:
                    order_id_col = next(
                        (
                            c
                            for c in cols
                            if "order" in str(c).lower() or "invoice" in str(c).lower()
                        ),
                        None,
                    )

                if auto_update_wc == "Enabled" and not order_id_col:
                    st.warning(
                        "⚠️ Auto-Update is enabled, but no 'Order ID' column was detected in your file. WooCommerce updates will be skipped."
                    )

                with st.status("Fetching bulk statuses...", expanded=True) as status_ui:
                    results = []
                    status_cache = {}
                    updated_order_ids = set()
                    progress_bar = st.progress(0)
                    total = len(bulk_df)

                    for step_idx, (_, row) in enumerate(bulk_df.iterrows()):
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
                                row_copy["Payment Status"] = data.get(
                                    "payment_status", ""
                                )

                                if (
                                    auto_update_wc == "Enabled"
                                    and order_id_col
                                    and "delivered" in live_status.lower()
                                ):
                                    wc_id = extract_order_id(
                                        row_copy.get(order_id_col, "")
                                    )
                                    if wc_id:
                                        if wc_id in updated_order_ids:
                                            row_copy["WC Update"] = (
                                                "Skipped (already updated in this run)"
                                            )
                                            results.append(row_copy)
                                            if total > 0:
                                                progress_bar.progress(
                                                    min(1.0, (step_idx + 1) / total)
                                                )
                                            continue

                                        success, msg = update_order_status(
                                            wc_id,
                                            "completed",
                                            f"Auto-updated by DEEN-OPS: Pathao Consignment {cid} marked as Delivered.",
                                        )
                                        if success:
                                            updated_order_ids.add(wc_id)
                                        row_copy["WC Update"] = (
                                            "Success" if success else f"Failed: {msg}"
                                        )
                                    else:
                                        row_copy["WC Update"] = "Invalid Order ID"
                        else:
                            row_copy["Live Status"] = "Invalid ID"
                            row_copy["Status Reason"] = ""
                            row_copy["Payment Status"] = ""

                        results.append(row_copy)
                        if total > 0:
                            progress_bar.progress(min(1.0, (step_idx + 1) / total))

                    status_ui.update(
                        label="Bulk check complete!", state="complete", expanded=False
                    )

                updated_df = pd.DataFrame(results)
                st.session_state["pathao_bulk_result_df"] = updated_df

                total_orders = len(updated_df)
                delivered = len(
                    updated_df[
                        updated_df["Live Status"]
                        .astype(str)
                        .str.lower()
                        .str.contains("delivered")
                    ]
                )
                failed = len(
                    updated_df[
                        updated_df["Live Status"]
                        .astype(str)
                        .str.lower()
                        .str.contains("return|failed|cancel|error")
                    ]
                )
                in_transit = total_orders - delivered - failed

                st.markdown(
                    f"""
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
                """,
                    unsafe_allow_html=True,
                )

                st.markdown("#### 📊 Delivery Ratios")
                status_summary = updated_df["Live Status"].value_counts().reset_index()
                status_summary.columns = ["Status", "Count"]

                color_map = {}
                for status in status_summary["Status"]:
                    s_lower = str(status).lower()
                    if any(
                        x in s_lower for x in ["return", "failed", "cancel", "error"]
                    ):
                        color_map[status] = "#ef4444"
                    elif "delivered" in s_lower:
                        color_map[status] = "#10b981"
                    elif any(
                        x in s_lower for x in ["transit", "processing", "assigned"]
                    ):
                        color_map[status] = "#3b82f6"
                    else:
                        color_map[status] = "#f59e0b"

                fig = px.pie(
                    status_summary,
                    names="Status",
                    values="Count",
                    hole=0.5,
                    color="Status",
                    color_discrete_map=color_map,
                )
                fig.update_traces(textposition="inside", textinfo="percent+label")
                fig.update_layout(
                    margin=dict(t=20, b=20, l=10, r=10), showlegend=False, height=350
                )

                c_pie, _ = st.columns([1, 2])
                with c_pie:
                    st.plotly_chart(fig, use_container_width=True)

                if track_filter == "Failed & Pending Only":
                    updated_df = updated_df[
                        ~updated_df["Live Status"]
                        .astype(str)
                        .str.lower()
                        .str.contains("delivered")
                    ]
                    st.info(
                        f"Filtered out delivered orders. Showing {len(updated_df)} remaining orders."
                    )

                track_search = render_dataframe_search(
                    updated_df, "pathao_track", height=400
                )
                st.dataframe(
                    track_search.style.apply(_highlight_status, subset=["Live Status"]),
                    use_container_width=True,
                )

                bulk_status_excel_bytes = export_to_styled_excel(
                    {"Live_Statuses": updated_df}
                )

                st.download_button(
                    "Download Updated Report",
                    bulk_status_excel_bytes,
                    "Bulk_Statuses.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )

        except Exception as e:
            log_error(e, context="Pathao Bulk Track")
            st.error(f"Error processing file: {e}")
