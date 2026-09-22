import io
from datetime import datetime

import pandas as pd
import streamlit as st

from src.components.ui.ui_components import render_premium_header


def _compute_reconciliation_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Classify returned orders against WooCommerce & Pathao live statuses."""
    if df.empty:
        return df

    df = df.copy()

    def _classify_row(row):
        wc_st = str(row.get("Order Status", "")).lower().strip()
        p_st = str(row.get("Live Pathao Status", "")).lower().strip()
        pmt = str(row.get("Payment Method Title", "")).lower().strip()

        # 1. Reconciliation Status
        if wc_st in [
            "refunded",
            "cancelled",
            "failed",
            "returned",
            "wc-refunded",
            "wc-cancelled",
            "wc-returned",
        ]:
            rec_status = "â Verified (WC Refunded/Cancelled)"
        elif "delivered" in p_st:
            rec_status = "ð¨ Courier Discrepancy (Pathao Delivered)"
        elif wc_st in [
            "processing",
            "shipped",
            "completed",
            "confirmed",
            "wc-shipped",
            "wc-completed",
        ]:
            rec_status = "â ï¸ WC Status Mismatch (Action Needed)"
        else:
            rec_status = "ð¡ Pending Verification"

        # 2. Payment Refund Risk
        is_prepaid = any(
            kw in pmt
            for kw in [
                "bkash",
                "nagad",
                "rocket",
                "card",
                "online",
                "ssl",
                "amarpay",
                "bank",
            ]
        ) or (
            pmt != ""
            and not any(kw in pmt for kw in ["cod", "cash on delivery", "cash"])
        )
        pmt_flag = (
            "ð'³ Prepaid (Refund Verification Required)"
            if is_prepaid
            else "ð'µ Cash on Delivery (COD)"
        )

        # 3. Action Recommendation
        if rec_status == "â ï¸ WC Status Mismatch (Action Needed)":
            action = "Update WC Order Status to Cancelled / Refunded"
        elif rec_status == "ð¨ Courier Discrepancy (Pathao Delivered)":
            action = "Audit physically before issuing refund"
        elif is_prepaid and rec_status != "â Verified (WC Refunded/Cancelled)":
            action = "Verify customer bKash/Bank refund transfer"
        else:
            action = "No Action Required"

        return pd.Series([rec_status, pmt_flag, action])

    classified = df.apply(_classify_row, axis=1)
    df["Reconciliation Status"] = classified[0]
    df["Payment Type"] = classified[1]
    df["Recommended Action"] = classified[2]
    return df


def _render_direct_wc_audit_tab():
    """Render direct WooCommerce live refund & return audit without needing Google Sheets."""
    st.markdown("#### ð Direct Live WooCommerce Return & Refund Audit")
    st.caption(
        "Fetch recent orders marked as Refunded, Cancelled, or Failed directly from WooCommerce to verify fulfillment and tracking statuses."
    )

    c1, c2 = st.columns([2, 1])
    with c1:
        st.info(
            "Query WooCommerce REST API for orders marked with return/refund statuses to verify against Pathao courier data."
        )
    with c2:
        fetch_direct = st.button(
            "ð" Audit Live WC Returns",
            type="primary",
            use_container_width=True,
            key="btn_direct_wc_audit",
        )

    if fetch_direct or "direct_wc_returns_df" in st.session_state:
        if fetch_direct:
            with st.status(
                "ð"¡ Fetching WooCommerce refund & cancellation data...", expanded=True
            ) as status_box:
                try:
                    from src.services.woocommerce.client import (
                        HTTPBasicAuth,
                        _flatten_order,
                        get_woocommerce_config,
                        request_with_backoff,
                    )

                    cfg = get_woocommerce_config(required=False)
                    if not cfg:
                        st.error("WooCommerce credentials missing.")
                        return

                    endpoint = (
                        f"{cfg.get('store_url', '').rstrip('/')}/wp-json/wc/v3/orders"
                    )
                    auth = HTTPBasicAuth(
                        cfg.get("consumer_key", ""), cfg.get("consumer_secret", "")
                    )
                    params = {
                        "per_page": 100,
                        "status": "refunded,cancelled,failed",
                        "orderby": "date",
                        "order": "desc",
                        "_fields": "id,number,date_created,date_created_gmt,date_modified,date_modified_gmt,status,billing,shipping,payment_method_title,line_items,total,discount_total,shipping_total,fee_lines,coupon_lines,meta_data",
                    }

                    status_box.update(
                        label="ð"¡ Requesting refunded/cancelled orders from WooCommerce..."
                    )
                    res = request_with_backoff(
                        "GET", endpoint, params=params, auth=auth, timeout=15
                    )
                    res.raise_for_status()
                    import json

                    data = json.loads(res.content.decode("utf-8-sig"))

                    rows = []
                    for order in data:
                        rows.extend(_flatten_order(order))

                    df_wc_returns = pd.DataFrame(rows)
                    if df_wc_returns.empty:
                        status_box.update(
                            label="â¹ï¸ No refunded or cancelled orders found in recent records.",
                            state="complete",
                        )
                        st.info(
                            "No refunded, cancelled, or failed orders found in recent WooCommerce records."
                        )
                        return

                    df_wc_returns = _compute_reconciliation_fields(df_wc_returns)
                    st.session_state["direct_wc_returns_df"] = df_wc_returns
                    status_box.update(
                        label=f"â Loaded {len(df_wc_returns)} returned/cancelled items from WooCommerce",
                        state="complete",
                    )

                except Exception as e:
                    status_box.update(
                        label="â Failed to fetch WooCommerce orders", state="error"
                    )
                    st.error(f"Failed to fetch WooCommerce direct audit data: {e}")

        if "direct_wc_returns_df" in st.session_state:
            df_direct = st.session_state["direct_wc_returns_df"].copy()
            st.divider()

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                st.metric("Total WC Refunds/Cancels", len(df_direct))
            with col_m2:
                refunded_count = len(
                    df_direct[
                        df_direct["Order Status"].astype(str).str.lower() == "refunded"
                    ]
                )
                st.metric("Refunded Status", refunded_count)
            with col_m3:
                cancelled_count = len(
                    df_direct[
                        df_direct["Order Status"].astype(str).str.lower() == "cancelled"
                    ]
                )
                st.metric("Cancelled Status", cancelled_count)
            with col_m4:
                tot_val = pd.to_numeric(
                    df_direct.get("Item Cost", 0), errors="coerce"
                ).sum()
                st.metric("Refunded Value", f"à§³ {tot_val:,.0f}")

            st.markdown("##### ð" Live WooCommerce Refund Audit Records")
            st.dataframe(
                df_direct[
                    [
                        c
                        for c in [
                            "Order ID",
                            "Order Date",
                            "Order Status",
                            "Payment Method Title",
                            "Full Name (Billing)",
                            "Phone (Billing)",
                            "Item Name",
                            "Item Cost",
                            "Quantity",
                            "Pathao Consignment ID",
                            "Reconciliation Status",
                            "Recommended Action",
                        ]
                        if c in df_direct.columns
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Item Cost": st.column_config.NumberColumn(
                        "Item Cost", format="à§³ %d"
                    ),
                    "Order ID": st.column_config.NumberColumn("Order ID", format="%d"),
                },
            )


def render_return_analytics_tab():
    render_premium_header(
        "Return Analytics",
        "Track, analyze, and reconcile order returns with WooCommerce & Pathao data",
        "ð"",
    )

    sheet_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4j3i94IWVlVYI5gErxzfmmaYNiirGqnrncRKrDCbHvmLYpzH9l4_etjYmfCoDj_Gv-_mps2gnufXE/pub?output=csv&gid=0&single=true"

    with st.status(
        "ð"¥ Fetching return data from Google Sheets...", expanded=True
    ) as fetch_status:
        try:
            from src.utils.http import request_with_backoff

            fetch_status.update(label="ð"- Connecting to Google Sheets...")
            r = request_with_backoff("GET", sheet_url, timeout=15)
            r.raise_for_status()
            fetch_status.update(label="ð" Parsing returned data...")
            df = pd.read_csv(io.StringIO(r.text))
            fetch_status.update(
                label=f"â {len(df)} return records loaded", state="complete"
            )

            if "Date" in df.columns:
                df["Parsed_Date"] = pd.to_datetime(df["Date"], errors="coerce")
                valid_dates = df["Parsed_Date"].dropna()

                if not valid_dates.empty:
                    min_date = valid_dates.min().date()
                    max_date = valid_dates.max().date()

                    def clear_enrichment():
                        if "enriched_returns" in st.session_state:
                            del st.session_state["enriched_returns"]
                        if "full_enriched_returns" in st.session_state:
                            del st.session_state["full_enriched_returns"]

                    st.markdown("### ð" Filter Returns by Date")
                    col1, col2 = st.columns([1.5, 1])

                    with col1:
                        time_opts = [
                            "All Time",
                            "Last Day",
                            "Last 7 Days",
                            "Last 15 Days",
                            "Last Month",
                        ]
                        has_pills = hasattr(st, "pills")

                        if has_pills:
                            selected_time = st.pills(
                                "Quick Range",
                                time_opts,
                                default="All Time",
                                label_visibility="collapsed",
                            )
                        else:
                            selected_time = st.radio(
                                "Quick Range",
                                time_opts,
                                index=0,
                                horizontal=True,
                                label_visibility="collapsed",
                            )

                    with col2:
                        default_range = (min_date, max_date)
                        if selected_time == "Last Day":
                            default_range = (max_date - pd.Timedelta(days=1), max_date)
                        elif selected_time == "Last 7 Days":
                            default_range = (max_date - pd.Timedelta(days=7), max_date)
                        elif selected_time == "Last 15 Days":
                            default_range = (max_date - pd.Timedelta(days=15), max_date)
                        elif selected_time == "Last Month":
                            default_range = (max_date - pd.Timedelta(days=30), max_date)

                        selected_dates = st.date_input(
                            "Select Time Range",
                            value=default_range,
                            min_value=min_date,
                            max_value=max_date,
                            help="Filter the Google Sheet returns by date before matching.",
                            label_visibility="collapsed",
                        )

                    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                        start_d, end_d = selected_dates
                        df = df[
                            (df["Parsed_Date"].dt.date >= start_d)
                            & (df["Parsed_Date"].dt.date <= end_d)
                        ]

            total_returns = len(df)

            st.markdown(
                '<div class="metric-container">'
                f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Filtered Returns</div><div class="metric-value">{total_returns}</div></div><div class="metric-icon">ð"¦</div></div>'
                "</div>",
                unsafe_allow_html=True,
            )

            st.divider()

            tab_enrich, tab_recon, tab_direct_wc, tab_raw = st.tabs(
                [
                    "ð Enriched Matches & Analytics",
                    "â-ï¸ WooCommerce Reconciliation Matrix",
                    "ð Direct WooCommerce Refund Audit",
                    "ð" Raw Google Sheet Data",
                ]
            )

            with tab_raw:
                st.markdown("#### ð" Loaded Google Sheet Data")
                st.dataframe(df, use_container_width=True, hide_index=True)

            with tab_direct_wc:
                _render_direct_wc_audit_tab()

            if "Order ID" not in df.columns:
                st.warning("Could not find 'Order ID' in the Google Sheet.")
                return

            with tab_enrich:
                st.markdown(
                    "#### ð" Real-Time Return Tracking & WooCommerce Cross-Verification"
                )

                enable_pathao = st.toggle(
                    "Enable Pathao Fetching",
                    value=True,
                    help="Turn off to skip Pathao tracking status and only fetch WooCommerce data.",
                )

                col1, col2 = st.columns([2, 1])
                with col1:
                    st.info(
                        "Fetch live order details from WooCommerce and tracking statuses from Pathao to audit and verify returns."
                    )
                with col2:
                    if st.button(
                        "â¡ Fetch & Enrich Data",
                        use_container_width=True,
                        type="primary",
                    ):
                        clear_enrichment()

                        df_to_match = df.copy()
                        df_to_match["Order ID"] = pd.to_numeric(
                            df_to_match["Order ID"], errors="coerce"
                        )
                        df_to_match = df_to_match.dropna(subset=["Order ID"])
                        order_ids_to_fetch = (
                            df_to_match["Order ID"].astype(int).unique().tolist()
                        )
                        with st.status(
                            "ð"- Enriching return data with WooCommerce & Pathao...",
                            expanded=True,
                        ) as enrich_status:
                            from src.services.woocommerce.client import (
                                fetch_specific_woocommerce_orders,
                            )

                            try:
                                enrich_status.update(
                                    label="ð"¡ Fetching WooCommerce order details..."
                                )
                                wc_orders = fetch_specific_woocommerce_orders(
                                    order_ids_to_fetch
                                )
                                wc_df = pd.DataFrame(wc_orders)

                                pathao_statuses = {}
                                if (
                                    enable_pathao
                                    and "Courier ID" in df_to_match.columns
                                ):
                                    courier_ids = (
                                        df_to_match["Courier ID"]
                                        .dropna()
                                        .unique()
                                        .tolist()
                                    )
                                    enrich_status.update(
                                        label=f"ð" Fetching Pathao statuses (disk-cached) for {len(courier_ids)} orders..."
                                    )
                                    from src.services.pathao.status import (
                                        batch_get_pathao_order_statuses,
                                    )

                                    pathao_statuses = batch_get_pathao_order_statuses(
                                        courier_ids
                                    )

                                if pathao_statuses:
                                    df_to_match["Live Pathao Status"] = df_to_match[
                                        "Courier ID"
                                    ].map(pathao_statuses)
                                else:
                                    df_to_match["Live Pathao Status"] = (
                                        "N/A (Skipped)" if not enable_pathao else "N/A"
                                    )

                                if not wc_df.empty and "Order Number" in wc_df.columns:
                                    enrich_status.update(
                                        label="ð" Merging return data with WooCommerce orders..."
                                    )
                                    wc_df["Order Number_Num"] = pd.to_numeric(
                                        wc_df["Order Number"], errors="coerce"
                                    )

                                    merged_df = pd.merge(
                                        df_to_match,
                                        wc_df,
                                        left_on="Order ID",
                                        right_on="Order Number_Num",
                                        how="inner",
                                    )

                                    if merged_df.empty:
                                        enrich_status.update(
                                            label="â ï¸ No matching WooCommerce orders found",
                                            state="error",
                                        )
                                        st.warning(
                                            "No matching WooCommerce orders found for these returns."
                                        )
                                    else:
                                        merged_df = merged_df.rename(
                                            columns={
                                                "Order ID_x": "GSheet Order ID",
                                                "Order ID_y": "WC Internal ID",
                                            }
                                        )
                                        merged_df = _compute_reconciliation_fields(
                                            merged_df
                                        )

                                        overview_cols = [
                                            "Order Number",
                                            "Courier ID",
                                            "Live Pathao Status",
                                            "Delivery Issue",
                                            "Item Name",
                                            "Order Status",
                                            "Payment Method Title",
                                            "Reconciliation Status",
                                            "Payment Type",
                                            "Recommended Action",
                                            "Full Name (Billing)",
                                            "Phone (Billing)",
                                            "Order Date",
                                            "Item Cost",
                                            "Quantity",
                                        ]
                                        existing_cols = [
                                            c
                                            for c in overview_cols
                                            if c in merged_df.columns
                                        ]

                                        st.session_state["enriched_returns"] = (
                                            merged_df[existing_cols].copy()
                                        )
                                        st.session_state["full_enriched_returns"] = (
                                            merged_df.copy()
                                        )
                                        enrich_status.update(
                                            label=f"â Enriched {len(merged_df)} return records",
                                            state="complete",
                                        )
                                else:
                                    enrich_status.update(
                                        label="â ï¸ WooCommerce returned no data",
                                        state="error",
                                    )
                                    st.warning(
                                        "WooCommerce failed to return data for these order IDs."
                                    )

                            except Exception as match_err:
                                enrich_status.update(
                                    label="â Enrichment failed", state="error"
                                )
                                st.error(f"Failed to load external data: {match_err}")

                if "enriched_returns" in st.session_state:
                    enriched_df = st.session_state["enriched_returns"].copy()
                    full_df = st.session_state["full_enriched_returns"].copy()

                    if (
                        selected_time
                        and selected_time != "All Time"
                        and "Order Date" in enriched_df.columns
                    ):
                        enriched_df["Parsed_Order_Date"] = pd.to_datetime(
                            enriched_df["Order Date"], errors="coerce"
                        )
                        max_dt = enriched_df["Parsed_Order_Date"].max()

                        if pd.notna(max_dt):
                            if selected_time == "Last Day":
                                cutoff = max_dt - pd.Timedelta(days=1)
                            elif selected_time == "Last 7 Days":
                                cutoff = max_dt - pd.Timedelta(days=7)
                            elif selected_time == "Last 15 Days":
                                cutoff = max_dt - pd.Timedelta(days=15)
                            elif selected_time == "Last Month":
                                cutoff = max_dt - pd.Timedelta(days=30)

                            enriched_df = enriched_df[
                                enriched_df["Parsed_Order_Date"] >= cutoff
                            ]
                            if "Order Date" in full_df.columns:
                                full_df["Parsed_Order_Date"] = pd.to_datetime(
                                    full_df["Order Date"], errors="coerce"
                                )
                                full_df = full_df[
                                    full_df["Parsed_Order_Date"] >= cutoff
                                ]

                    st.divider()

                    if "Order Number" in enriched_df.columns:
                        enriched_df["Order Number Str"] = (
                            enriched_df["Order Number"]
                            .astype(str)
                            .str.lower()
                            .str.strip()
                        )
                        enriched_df["Outlet"] = "Main/Online"
                        enriched_df.loc[
                            enriched_df["Order Number Str"].str.contains(
                                r"[- ]?c$", regex=True, na=False
                            ),
                            "Outlet",
                        ] = "Central (C)"
                        enriched_df.loc[
                            enriched_df["Order Number Str"].str.contains(
                                r"[- ]?w$", regex=True, na=False
                            ),
                            "Outlet",
                        ] = "Warehouse (W)"
                        enriched_df.loc[
                            enriched_df["Order Number Str"].str.contains(
                                r"[- ]?s$", regex=True, na=False
                            ),
                            "Outlet",
                        ] = "Sylhet/Savar (S)"

                    total_shipped = 0
                    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                        try:
                            start_iso = datetime.combine(
                                selected_dates[0], datetime.min.time()
                            ).isoformat()
                            end_iso = datetime.combine(
                                selected_dates[1], datetime.max.time()
                            ).isoformat()
                            from src.services.woocommerce.client import (
                                get_woocommerce_shipped_orders_count,
                            )

                            total_shipped = get_woocommerce_shipped_orders_count(
                                start_iso, end_iso
                            )
                        except Exception as e:
                            st.warning(
                                f"Could not fetch total shipped orders for return rate: {e}"
                            )

                    total_matches = len(enriched_df)
                    return_rate = (
                        (total_matches / total_shipped * 100)
                        if total_shipped > 0
                        else 0
                    )

                    financial_impact = 0
                    if "Item Cost" in enriched_df.columns:
                        financial_impact = pd.to_numeric(
                            enriched_df["Item Cost"], errors="coerce"
                        ).sum()

                    wc_mismatches = 0
                    if "Reconciliation Status" in enriched_df.columns:
                        wc_mismatches = len(
                            enriched_df[
                                enriched_df["Reconciliation Status"]
                                .astype(str)
                                .str.contains(
                                    "WC Status Mismatch", case=False, na=False
                                )
                            ]
                        )

                    prepaid_refunds = 0
                    if "Payment Type" in enriched_df.columns:
                        prepaid_refunds = len(
                            enriched_df[
                                enriched_df["Payment Type"]
                                .astype(str)
                                .str.contains("Prepaid", case=False, na=False)
                            ]
                        )

                    st.markdown(
                        '<div class="metric-container">', unsafe_allow_html=True
                    )
                    st.markdown(
                        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Total Shipped</div><div class="metric-value">{total_shipped}</div></div><div class="metric-icon">ð"¦</div></div>'
                        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Matched Returns</div><div class="metric-value">{total_matches}</div></div><div class="metric-icon">ð"</div></div>'
                        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Return Rate</div><div class="metric-value">{return_rate:.1f}%</div></div><div class="metric-icon">ð"</div></div>'
                        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">WC Status Mismatches</div><div class="metric-value">{wc_mismatches}</div></div><div class="metric-icon">â ï¸</div></div>'
                        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Prepaid Refund Risks</div><div class="metric-value">{prepaid_refunds}</div></div><div class="metric-icon">ð'³</div></div>'
                        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">Financial Impact</div><div class="metric-value">à§³ {financial_impact:,.0f}</div></div><div class="metric-icon">ð'°</div></div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown("</div>", unsafe_allow_html=True)

                    st.divider()

                    import plotly.express as px

                    col_chart1, col_chart2 = st.columns(2)

                    with col_chart1:
                        st.markdown("##### ð© Return Reasons Breakdown")
                        if (
                            "Delivery Issue" in enriched_df.columns
                            and not enriched_df["Delivery Issue"].isna().all()
                        ):
                            fig_issues = px.pie(
                                enriched_df,
                                names="Delivery Issue",
                                hole=0.6,
                                color_discrete_sequence=px.colors.qualitative.Pastel,
                            )
                            fig_issues.update_layout(
                                margin=dict(t=10, b=10, l=10, r=10),
                                showlegend=True,
                                legend=dict(
                                    orientation="h",
                                    yanchor="bottom",
                                    y=-0.2,
                                    xanchor="center",
                                    x=0.5,
                                ),
                                paper_bgcolor="rgba(0,0,0,0)",
                                plot_bgcolor="rgba(0,0,0,0)",
                            )
                            st.plotly_chart(
                                fig_issues,
                                use_container_width=True,
                                config={"displayModeBar": False},
                            )
                        else:
                            st.info("No Return Reason data available.")

                    with col_chart2:
                        st.markdown("##### ð" Return Volume over Time")
                        if "Order Date" in enriched_df.columns:
                            try:
                                df_dates = enriched_df.copy()
                                df_dates["Order Date"] = pd.to_datetime(
                                    df_dates["Order Date"], errors="coerce"
                                ).dt.date
                                date_counts = (
                                    df_dates["Order Date"].value_counts().reset_index()
                                )
                                date_counts.columns = ["Date", "Count"]
                                date_counts = date_counts.sort_values("Date")

                                if not date_counts.empty:
                                    fig_trend = px.bar(
                                        date_counts,
                                        x="Date",
                                        y="Count",
                                        color_discrete_sequence=["#3b82f6"],
                                    )
                                    fig_trend.update_layout(
                                        margin=dict(t=10, b=10, l=10, r=10),
                                        xaxis_title=None,
                                        yaxis_title="Returned Orders",
                                        paper_bgcolor="rgba(0,0,0,0)",
                                        plot_bgcolor="rgba(0,0,0,0)",
                                    )
                                    st.plotly_chart(
                                        fig_trend,
                                        use_container_width=True,
                                        config={"displayModeBar": False},
                                    )
                                else:
                                    st.info("No valid dates to chart.")
                            except Exception as e:
                                st.warning(f"Could not chart trends: {e}")
                        else:
                            st.info("No Order Date data available.")

                    st.divider()
                    st.markdown("##### ð" Matched Records & Status Overview")
                    st.dataframe(
                        enriched_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Live Pathao Status": st.column_config.TextColumn(
                                "Pathao Status",
                                help="Live tracking status from Pathao",
                            ),
                            "Item Cost": st.column_config.NumberColumn(
                                "Item Cost",
                                format="à§³ %d",
                            ),
                        },
                    )

            with tab_recon:
                st.markdown("#### â-ï¸ WooCommerce Status Reconciliation & Action Audit")
                st.caption(
                    "Audit returned orders against live WooCommerce order statuses and Pathao delivery logs to catch order status mismatches and prepaid refund risks."
                )

                if "enriched_returns" in st.session_state:
                    rec_df = st.session_state["enriched_returns"].copy()
                    full_recon_df = st.session_state["full_enriched_returns"].copy()

                    filter_opts = [
                        "All Returns",
                        "â ï¸ WC Status Mismatches Only",
                        "ð'³ Prepaid Refund Risks",
                        "ð¨ Courier Discrepancies",
                        "â Verified Returns",
                    ]
                    if hasattr(st, "pills"):
                        sel_filter = st.pills(
                            "Filter Audit Matrix",
                            filter_opts,
                            default="All Returns",
                            key="pills_recon_filter",
                        )
                    else:
                        sel_filter = st.radio(
                            "Filter Audit Matrix",
                            filter_opts,
                            index=0,
                            horizontal=True,
                            key="radio_recon_filter",
                        )

                    display_recon = rec_df.copy()
                    if sel_filter == "â ï¸ WC Status Mismatches Only":
                        display_recon = display_recon[
                            display_recon["Reconciliation Status"]
                            .astype(str)
                            .str.contains("WC Status Mismatch", case=False, na=False)
                        ]
                    elif sel_filter == "ð'³ Prepaid Refund Risks":
                        display_recon = display_recon[
                            display_recon["Payment Type"]
                            .astype(str)
                            .str.contains("Prepaid", case=False, na=False)
                        ]
                    elif sel_filter == "ð¨ Courier Discrepancies":
                        display_recon = display_recon[
                            display_recon["Reconciliation Status"]
                            .astype(str)
                            .str.contains("Courier Discrepancy", case=False, na=False)
                        ]
                    elif sel_filter == "â Verified Returns":
                        display_recon = display_recon[
                            display_recon["Reconciliation Status"]
                            .astype(str)
                            .str.contains("Verified", case=False, na=False)
                        ]

                    search_q = st.text_input(
                        "ð" Search by Order ID, Phone, or Product Name",
                        key="search_recon_matrix",
                    ).strip()
                    if search_q:
                        display_recon = display_recon[
                            display_recon["Order Number"]
                            .astype(str)
                            .str.contains(search_q, case=False, na=False)
                            | display_recon.get("Phone (Billing)", pd.Series(dtype=str))
                            .astype(str)
                            .str.contains(search_q, case=False, na=False)
                            | display_recon.get("Item Name", pd.Series(dtype=str))
                            .astype(str)
                            .str.contains(search_q, case=False, na=False)
                        ]

                    st.markdown(
                        f"**Showing {len(display_recon)} audit records ({sel_filter}):**"
                    )
                    st.dataframe(
                        display_recon[
                            [
                                c
                                for c in [
                                    "Order Number",
                                    "Order Status",
                                    "Live Pathao Status",
                                    "Reconciliation Status",
                                    "Payment Method Title",
                                    "Payment Type",
                                    "Recommended Action",
                                    "Full Name (Billing)",
                                    "Phone (Billing)",
                                    "Item Name",
                                    "Item Cost",
                                ]
                                if c in display_recon.columns
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Order Status": st.column_config.TextColumn(
                                "WooCommerce Status"
                            ),
                            "Live Pathao Status": st.column_config.TextColumn(
                                "Pathao Status"
                            ),
                            "Reconciliation Status": st.column_config.TextColumn(
                                "Audit Status"
                            ),
                            "Payment Type": st.column_config.TextColumn(
                                "Payment Category"
                            ),
                            "Recommended Action": st.column_config.TextColumn(
                                "Recommended Action"
                            ),
                            "Item Cost": st.column_config.NumberColumn(
                                "Item Value", format="à§³ %d"
                            ),
                        },
                    )

                    st.divider()

                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                        full_recon_df.to_excel(
                            writer, index=False, sheet_name="Matched Returns Overview"
                        )

                        mismatches_df = full_recon_df[
                            full_recon_df["Reconciliation Status"]
                            .astype(str)
                            .str.contains("WC Status Mismatch", case=False, na=False)
                        ]
                        if not mismatches_df.empty:
                            mismatches_df.to_excel(
                                writer,
                                index=False,
                                sheet_name="WC Mismatch Action List",
                            )

                        prepaid_df = full_recon_df[
                            full_recon_df["Payment Type"]
                            .astype(str)
                            .str.contains("Prepaid", case=False, na=False)
                        ]
                        if not prepaid_df.empty:
                            prepaid_df.to_excel(
                                writer,
                                index=False,
                                sheet_name="Prepaid Refund Audit List",
                            )

                    excel_data = output.getvalue()

                    st.download_button(
                        label="ð"¥ Download Reconciliation & Action Audit Report (Multi-Sheet Excel)",
                        data=excel_data,
                        file_name="woocommerce_return_reconciliation_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                        use_container_width=True,
                        key="btn_download_recon_report",
                    )
                else:
                    st.info(
                        "â¹ï¸ Click **â¡ Fetch & Enrich Data** in the *Enriched Matches* tab to generate the WooCommerce Reconciliation Matrix."
                    )

        except Exception as e:
            st.error(
                f"Failed to fetch or parse Return Analytics data from the provided URL. Error: {e}"
            )


# ---------------------------------------------------------------------------
# Combined entry point - Return Analytics + Return Orders Extractor
# ---------------------------------------------------------------------------


def render_combined_returns_tab():
    """Unified Returns page: stacks Return Analytics and Return Orders Extractor."""
    from src.utils.safe_ops import safe_render

    st.markdown("## ?? Return Analytics")
    safe_render(render_return_analytics_tab, fallback_msg="Return Analytics unavailable.")

    st.divider()

    st.markdown("## ?? Return Orders Extractor")
    from src.pages.return_order_extractor import render_return_order_extractor_tab
    safe_render(render_return_order_extractor_tab, fallback_msg="Return Orders Extractor unavailable.")
