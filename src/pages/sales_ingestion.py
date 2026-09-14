from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

from src.components.dashboard.dashboard_output import render_dashboard_output
from src.components.ui.widgets import (
    render_action_bar,
    render_reset_confirm,
    section_card,
)
from src.config.constants import SHIPPED_STATUSES, bd_now, bd_today
from src.processing.column_detection import find_columns
from src.processing.data_processing import aggregate_data, prepare_granular_data
from src.services.woocommerce.client import load_from_woocommerce
from src.utils.file_io import read_sales_file
from src.utils.logging import log_system_event
from src.utils.snapshots import save_sales_snapshot


def render_manual_tab():
    def _reset_manual_state():
        st.session_state.manual_generate = False
        st.session_state.manual_df = None

    # v11.3 State Enforcement: Prioritize Ingestion UI over Live defaults
    st.session_state["manual_tab_active"] = True
    st.session_state["wc_sync_mode"] = "Custom Range"

    # ── Timeframe & Date Range Preset Controls (Default: Last 7 Days) ───────────
    today_date = bd_today()
    if "ingest_preset" not in st.session_state:
        st.session_state["ingest_preset"] = "Last 7 Days"
        st.session_state["wc_sync_start_date"] = today_date - timedelta(days=7)
        st.session_state["wc_sync_end_date"] = today_date

    col_d1, col_d2 = st.columns([2, 3])
    with col_d1:
        preset_opts = [
            "Last 7 Days",
            "Last 14 Days",
            "Last 30 Days (1 Month)",
            "Last 90 Days",
            "Custom Range",
        ]
        curr_preset = st.session_state.get("ingest_preset", "Last 7 Days")
        chosen_preset = st.selectbox(
            "📅 Ingestion Timeframe",
            preset_opts,
            index=preset_opts.index(curr_preset) if curr_preset in preset_opts else 0,
            key="ingest_preset_selector",
            help="Default timeframe is 7 days. Select presets or pick a custom range below.",
        )

    with col_d2:
        if chosen_preset == "Last 7 Days":
            req_start = today_date - timedelta(days=7)
            req_end = today_date
        elif chosen_preset == "Last 14 Days":
            req_start = today_date - timedelta(days=14)
            req_end = today_date
        elif chosen_preset == "Last 30 Days (1 Month)":
            req_start = today_date - timedelta(days=30)
            req_end = today_date
        elif chosen_preset == "Last 90 Days":
            req_start = today_date - timedelta(days=90)
            req_end = today_date
        else:
            req_start = st.session_state.get(
                "wc_sync_start_date", today_date - timedelta(days=7)
            )
            req_end = st.session_state.get("wc_sync_end_date", today_date)

        chosen_dates = st.date_input(
            "📅 Active Date Range", value=(req_start, req_end), key="ingest_date_picker"
        )
        if isinstance(chosen_dates, (list, tuple)) and len(chosen_dates) == 2:
            start_d, end_d = chosen_dates[0], chosen_dates[1]
        else:
            start_d, end_d = req_start, req_end

    if (
        st.session_state.get("wc_sync_start_date") != start_d
        or st.session_state.get("wc_sync_end_date") != end_d
        or st.session_state.get("ingest_preset") != chosen_preset
    ):
        st.session_state["ingest_preset"] = chosen_preset
        st.session_state["wc_sync_start_date"] = start_d
        st.session_state["wc_sync_end_date"] = end_d
        st.session_state["wc_sync_mode"] = "Custom Range"
        st.session_state["wc_sync_start_time"] = datetime.strptime(
            "00:00", "%H:%M"
        ).time()
        st.session_state["wc_sync_end_time"] = datetime.strptime(
            "23:59", "%H:%M"
        ).time()
        st.session_state.manual_df = None
        st.session_state.manual_autoload_attempted = False
        load_from_woocommerce.clear()
        st.rerun()

    render_reset_confirm("Sales Data Ingestion", "manual", _reset_manual_state)

    st.info(
        f"📊 Analyzing Sales Data for **{chosen_preset}** ({st.session_state.get('wc_sync_start_date')} to {st.session_state.get('wc_sync_end_date')})."
    )

    # Auto-Load Intelligence with API / Snapshot Fallback
    if st.session_state.get("manual_df") is None and not st.session_state.get(
        "manual_autoload_attempted", False
    ):
        st.session_state["manual_autoload_attempted"] = True
        s_d = st.session_state.get("wc_sync_start_date", today_date - timedelta(days=7))
        e_d = st.session_state.get("wc_sync_end_date", today_date)

        days_span = (e_d - s_d).days
        with st.status(
            f"🚀 Fetching WooCommerce Sales ({s_d} to {e_d})...", expanded=True
        ) as status:
            try:
                st.write("Initializing synchronization protocol...")
                st.session_state["wc_sync_mode"] = "Custom Range"
                st.session_state["wc_sync_start_time"] = datetime.strptime(
                    "00:00", "%H:%M"
                ).time()
                st.session_state["wc_sync_end_time"] = datetime.strptime(
                    "23:59", "%H:%M"
                ).time()

                st.write("Fetching transaction payloads from WooCommerce...")
                wc_res = load_from_woocommerce(
                    cache_buster=str(int(bd_now().timestamp() * 1000))
                )
                df_res = wc_res["df_to_return"]
                if not df_res.empty:
                    st.write("Data structured. Saving snapshot...")
                    st.session_state.manual_df = df_res
                    st.session_state.manual_source_name = (
                        f"WooCommerce_{days_span}d ({s_d} to {e_d})"
                    )
                    save_sales_snapshot(df_res)
                    status.update(
                        label="API Sync Complete", state="complete", expanded=False
                    )
                    st.toast(f"✅ Ingested {len(df_res)} orders for {chosen_preset}!")
                    st.rerun()
            except Exception as e:
                status.update(
                    label=f"API Sync Failed: {e}", state="error", expanded=False
                )

    # v11.3 Sync State
    df = st.session_state.get("manual_df")
    source_name = st.session_state.get("manual_source_name", "")

    # Optional Sources Expander
    with st.expander("📤 Optional: External Source (Upload / URL)"):
        uploaded_file = st.file_uploader(
            "📂 Drag and drop sales file",
            type=["xlsx", "csv"],
            key="manual_uploader_v2",
        )
        if uploaded_file:
            df_up = read_sales_file(uploaded_file, uploaded_file.name)
            if df_up is not None:
                st.session_state.manual_df = df_up
                st.session_state.manual_source_name = uploaded_file.name
                df = df_up
                source_name = uploaded_file.name

        if st.session_state.get("manual_df") is not None:
            df = st.session_state.manual_df
            source_name = st.session_state.get(
                "manual_source_name", "WooCommerce_Custom_Pull"
            )

    if df is not None:
        st.divider()
        st.subheader("🛠️ Data Transformation & Filtering")

        with st.expander(
            "🔢 Filter Raw Ingestion Data (Order ID / Status)", expanded=False
        ):
            col1, col2 = st.columns(2)
            with col1:
                min_order_id = st.number_input(
                    "Start Order ID", value=0, step=1, help="Leave as 0 to ignore"
                )
            with col2:
                max_order_id = st.number_input(
                    "End Order ID", value=0, step=1, help="Leave as 0 to ignore"
                )

            only_shipped = st.checkbox("📦 Show Shipped Orders Only", value=False)

            if min_order_id > 0 and max_order_id > 0:
                order_col = (
                    "Order ID"
                    if "Order ID" in df.columns
                    else "Order Number"
                    if "Order Number" in df.columns
                    else None
                )
                if order_col:
                    df = df.copy()
                    df[order_col] = pd.to_numeric(df[order_col], errors="coerce")
                    df = df[
                        (df[order_col] >= min_order_id)
                        & (df[order_col] <= max_order_id)
                    ]

            if only_shipped:
                status_col = (
                    "Order Status"
                    if "Order Status" in df.columns
                    else "Status"
                    if "Status" in df.columns
                    else None
                )
                if status_col:
                    df = df[
                        df[status_col].astype(str).str.lower().isin(SHIPPED_STATUSES)
                    ]

                    if "mod_dt_parsed" in df.columns:
                        s_d = st.session_state.get("wc_sync_start_date")
                        e_d = st.session_state.get("wc_sync_end_date")

                        if s_d and e_d:
                            s_dt = pd.to_datetime(s_d)
                            e_dt = (
                                pd.to_datetime(e_d)
                                + pd.Timedelta(days=1)
                                - pd.Timedelta(seconds=1)
                            )
                            df = df[
                                (df["mod_dt_parsed"] >= s_dt)
                                & (df["mod_dt_parsed"] <= e_dt)
                            ]
            st.info(f"Rows matching criteria: {len(df)}")

            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Filtered Orders")

            st.download_button(
                label="💾 Export Filtered Orders (Excel)",
                data=buf.getvalue(),
                file_name="Filtered_Orders.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    if df is None:
        # v11.3 Call unified dashboard with None to show ingestion expander
        render_dashboard_output(None, None, None, None, None, "None", granular_df=None)
        return

    try:
        # v10.7+ Direct Intelligence (Bypass mapping for WooCommerce and Snapshots)
        if "WooCommerce" in str(source_name) or "Snapshot" in str(source_name):
            final_mapping = {
                "name": "Item Name",
                "cost": "Item Cost",
                "qty": "Quantity",
                "date": "Order Date" if "Date" not in df.columns else "Date",
                "order_id": "Order Number",
                "phone": "Phone (Billing)",
                "sku": "SKU",
            }
            df_standard, timeframe = prepare_granular_data(df, final_mapping)
            if not df_standard.empty:
                drill, summ, top, basket = aggregate_data(df_standard, final_mapping)
                render_dashboard_output(
                    drill,
                    summ,
                    top,
                    str(timeframe) if timeframe is not None else None,
                    basket,
                    str(source_name) if source_name is not None else None,
                    granular_df=df_standard,
                )
            else:
                st.warning("⚠️ No records found after data processing.")
            return

        st.caption(f"Active Data Source: {source_name}")
        auto_cols = find_columns(df)
        all_cols = list(df.columns)

        section_card(
            "Column Mapping",
            "Detected columns are prefilled. Verify before generating dashboard output.",
        )

        def get_col_idx(key):
            if key in auto_cols and auto_cols[key] in all_cols:
                return all_cols.index(auto_cols[key])
            return 0

        col1, col2 = st.columns(2)
        with col1:
            mapped_name = st.selectbox(
                "Product Name", all_cols, index=get_col_idx("name"), key="manual_name"
            )
            mapped_cost = st.selectbox(
                "Price/Cost", all_cols, index=get_col_idx("cost"), key="manual_cost"
            )
            mapped_qty = st.selectbox(
                "Quantity", all_cols, index=get_col_idx("qty"), key="manual_qty"
            )
            mapped_date = st.selectbox(
                "Date (Optional)",
                ["None"] + all_cols,
                index=get_col_idx("date") + 1 if "date" in auto_cols else 0,
                key="manual_date",
            )
        with col2:
            mapped_order = st.selectbox(
                "Order ID (Optional)",
                ["None"] + all_cols,
                index=get_col_idx("order_id") + 1 if "order_id" in auto_cols else 0,
                key="manual_order",
            )
            mapped_phone = st.selectbox(
                "Phone (Optional)",
                ["None"] + all_cols,
                index=get_col_idx("phone") + 1 if "phone" in auto_cols else 0,
                key="manual_phone",
            )
            mapped_sku = st.selectbox(
                "SKU (Optional)",
                ["None"] + all_cols,
                index=get_col_idx("sku") + 1 if "sku" in auto_cols else 0,
                key="manual_sku",
            )

        final_mapping = {
            "name": mapped_name,
            "cost": mapped_cost,
            "qty": mapped_qty,
            "date": mapped_date if mapped_date != "None" else None,
            "order_id": mapped_order if mapped_order != "None" else None,
            "phone": mapped_phone if mapped_phone != "None" else None,
            "sku": mapped_sku if mapped_sku != "None" else None,
        }

        with st.expander("Search Raw Data"):
            search = st.text_input("Product search...", key="manual_search")
            if search:
                st.dataframe(
                    df[
                        df[mapped_name]
                        .astype(str)
                        .str.contains(search, case=False, na=False)
                    ],
                    use_container_width=True,
                )
            else:
                st.dataframe(df.head(10), use_container_width=True)

        generate_clicked, _ = render_action_bar("Generate dashboard", "manual_generate")
        if generate_clicked:
            with st.status("🔄 Processing data...", expanded=True) as proc_status:
                proc_status.update(label="📊 Standardizing column mapping...")
                df_standard, timeframe = prepare_granular_data(df, final_mapping)
                if not df_standard.empty:
                    proc_status.update(label="📈 Aggregating sales data...")
                    drill, summ, top, basket = aggregate_data(
                        df_standard, final_mapping
                    )
                    proc_status.update(
                        label="✅ Data processed, rendering dashboard...",
                        state="complete",
                    )
                    manual_updated = bd_now().strftime("%Y-%m-%d %H:%M:%S")
                    render_dashboard_output(
                        drill,
                        summ,
                        top,
                        str(timeframe) if timeframe is not None else None,
                        basket,
                        str(source_name) if source_name is not None else None,
                        manual_updated,
                        granular_df=df_standard,
                    )
                else:
                    proc_status.update(
                        label="⚠️ No data after processing", state="error"
                    )

    except Exception as e:
        log_system_event("FILE_ERROR", str(e))
        st.error(f"File error: {e}")
