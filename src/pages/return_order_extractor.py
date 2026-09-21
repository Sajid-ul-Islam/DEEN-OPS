"""Return Orders Extractor — Streamlit page.

Provides a self-contained UI to extract return order information by:
- Time range (with quick presets)
- Optional order number filter(s)
- Optional Pathao consignment ID filter(s)
- WC return status filter

Results include: Order Number, Consignment ID, Product Description,
WC Return Status, Pathao Status, Return Reason — with Excel export.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from src.components.ui.ui_components import render_metric_grid, render_premium_header
from src.config.constants import BD_TZ, bd_today
from src.services.woocommerce.returns import (
    DEFAULT_RETURN_STATUSES,
    fetch_pathao_returned_orders,
    fetch_wc_return_orders,
)


# ── Column ordering & display labels ────────────────────────────────────────

_DISPLAY_COLUMNS = [
    "Order Number",
    "Order Date",
    "WC Return Status",
    "Pathao Status",
    "Return Reason (Pathao)",
    "Refund Reason (WC)",
    "Product Description",
    "SKU",
    "Quantity",
    "Item Price",
    "Order Total",
    "Consignment ID",
    "Customer Name",
    "Phone",
    "City",
    "Payment Method",
]

_COLUMN_CONFIG = {
    "Item Price": st.column_config.NumberColumn("Item Price", format="৳ %.2f"),
    "Order Total": st.column_config.NumberColumn("Order Total", format="৳ %.0f"),
    "Quantity": st.column_config.NumberColumn("Qty", format="%d"),
    "Order Number": st.column_config.TextColumn("Order #"),
    "WC Return Status": st.column_config.TextColumn("WC Status"),
    "Pathao Status": st.column_config.TextColumn("Pathao Status"),
    "Return Reason (Pathao)": st.column_config.TextColumn("Return Reason (Pathao)"),
    "Refund Reason (WC)": st.column_config.TextColumn("Refund Reason (WC)"),
    "Product Description": st.column_config.TextColumn("Product", width="large"),
    "Consignment ID": st.column_config.TextColumn("Consignment ID"),
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_multivalue_input(raw: str) -> list[str]:
    """Split comma/newline-separated user input into clean strings."""
    if not raw or not raw.strip():
        return []
    parts = raw.replace("\n", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _build_date_defaults(preset: str) -> tuple[date, date]:
    """Return (start_date, end_date) based on the selected quick preset."""
    today = bd_today()
    if preset == "Last 7 Days":
        return today - timedelta(days=7), today
    elif preset == "Last 30 Days":
        return today - timedelta(days=30), today
    elif preset == "Last 3 Months":
        return today - timedelta(days=90), today
    elif preset == "Last Month (Calendar)":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    else:
        # "Today" default
        return today, today


def _status_badge(status: str) -> str:
    """Return a coloured emoji prefix for well-known statuses."""
    sl = status.lower()
    if any(k in sl for k in ("refund",)):
        return "💸 " + status
    elif any(k in sl for k in ("cancel",)):
        return "❌ " + status
    elif any(k in sl for k in ("return",)):
        return "🔁 " + status
    elif any(k in sl for k in ("fail",)):
        return "⚠️ " + status
    return status


def _compute_summary_metrics(df: pd.DataFrame) -> dict:
    """Derive KPI metrics from the results DataFrame."""
    total_rows = len(df)
    unique_orders = df["Order Number"].nunique() if "Order Number" in df.columns else 0

    total_value = 0.0
    if "Order Total" in df.columns:
        # Sum unique order totals to avoid double-counting multi-line-item orders
        if "Order Number" in df.columns:
            dedup = df.drop_duplicates("Order Number")
            total_value = pd.to_numeric(dedup["Order Total"], errors="coerce").sum()
        else:
            total_value = pd.to_numeric(df["Order Total"], errors="coerce").sum()

    # WC ↔ Pathao status mismatches: order is cancelled/refunded in WC but
    # Pathao shows "delivered" (i.e., courier claims delivery succeeded)
    mismatches = 0
    if "WC Return Status" in df.columns and "Pathao Status" in df.columns:
        wc_lower = df["WC Return Status"].astype(str).str.lower()
        pa_lower = df["Pathao Status"].astype(str).str.lower()
        is_return = wc_lower.str.contains("refund|cancel|return|fail", regex=True, na=False)
        is_delivered_pathao = pa_lower.str.contains("delivered", na=False)
        mismatches = int((is_return & is_delivered_pathao).sum())

    has_reason = 0
    if "Return Reason (Pathao)" in df.columns:
        has_reason = int(df["Return Reason (Pathao)"].astype(str).str.strip().ne("").sum())

    return {
        "unique_orders": unique_orders,
        "total_line_items": total_rows,
        "total_value": total_value,
        "mismatches": mismatches,
        "has_reason": has_reason,
    }


def _df_to_excel(df: pd.DataFrame) -> bytes:
    """Serialize the results DataFrame to a multi-sheet Excel file."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Return Orders")

        # Summary pivot by WC status
        if "WC Return Status" in df.columns and "Order Number" in df.columns:
            status_summary = (
                df.groupby("WC Return Status")
                .agg(
                    Total_Orders=("Order Number", "nunique"),
                    Total_Items=("Order Number", "count"),
                )
                .reset_index()
            )
            status_summary.to_excel(writer, index=False, sheet_name="By WC Status")

        # Pathao return-reason breakdown
        if "Return Reason (Pathao)" in df.columns:
            reason_df = df[df["Return Reason (Pathao)"].astype(str).str.strip() != ""]
            if not reason_df.empty:
                reason_summary = (
                    reason_df.groupby("Return Reason (Pathao)")
                    .agg(Count=("Order Number", "count"))
                    .reset_index()
                    .sort_values("Count", ascending=False)
                )
                reason_summary.to_excel(writer, index=False, sheet_name="Return Reasons")

    return output.getvalue()


# ── Main page render ─────────────────────────────────────────────────────────


def render_return_order_extractor_tab() -> None:
    """Render the Return Orders Extractor page."""
    render_premium_header(
        "Return Orders Extractor",
        "Extract return & cancellation order info from WooCommerce + Pathao APIs by date range",
        "🔎",
    )

    # ── Step 1: Return Source selector ────────────────────────────────────
    st.markdown("### 🔄 Return Source")

    source_mode = st.radio(
        "Select return data source",
        [
            "📦 WooCommerce Returns (refunded / cancelled / failed)",
            "🚢 Pathao Returns (courier-returned orders → matched in WooCommerce)",
        ],
        key="ret_ext_source_mode",
        horizontal=True,
        label_visibility="collapsed",
        help=(
            "**WooCommerce Returns**: fetches orders with status = refunded / cancelled / failed.\n\n"
            "**Pathao Returns**: fetches parcels that Pathao marked as \u2018returned\u2019 in the given "
            "date range, then looks up the corresponding WooCommerce orders (which appear as "
            "\u2018completed\u2019 in WC)."
        ),
    )
    is_pathao_mode = "🚢" in source_mode

    st.divider()

    # ── Step 2: Filter Panel ────────────────────────────────────────────────
    st.markdown("### 🗂️ Extraction Filters")

    with st.container():
        col_preset, col_dates = st.columns([1, 2])

        with col_preset:
            preset = st.selectbox(
                "Quick Date Range",
                [
                    "Last 7 Days",
                    "Last 30 Days",
                    "Last 3 Months",
                    "Last Month (Calendar)",
                    "Custom",
                ],
                key="ret_ext_preset",
                help="Choose a preset to auto-fill start/end dates, or pick 'Custom' for manual entry.",
            )

        # Detect preset change and update date keys imperatively before rendering.
        # st.date_input with key= ignores value= on reruns, so we must write to
        # session_state explicitly when the selected preset changes.
        _prev_preset = st.session_state.get("ret_ext_last_preset")
        if preset != "Custom" and preset != _prev_preset:
            new_start, new_end = _build_date_defaults(preset)
            st.session_state["ret_ext_start"] = new_start
            st.session_state["ret_ext_end"] = new_end
            st.session_state["ret_ext_last_preset"] = preset

        # Ensure defaults on first load
        if "ret_ext_start" not in st.session_state:
            default_start, default_end = _build_date_defaults("Last 7 Days")
            st.session_state["ret_ext_start"] = default_start
            st.session_state["ret_ext_end"] = default_end
            st.session_state["ret_ext_last_preset"] = "Last 7 Days"

        with col_dates:
            col_sd, col_ed = st.columns(2)
            with col_sd:
                start_date = st.date_input(
                    "From Date",
                    key="ret_ext_start",
                    help="Start of the return order date range (BD timezone).",
                )
            with col_ed:
                end_date = st.date_input(
                    "To Date",
                    key="ret_ext_end",
                    help="End of the return order date range (BD timezone, inclusive).",
                )

    # ── Advanced filters (WC mode only) ───────────────────────────────────
    order_numbers_raw = ""
    selected_statuses = ["refunded", "cancelled", "failed"]
    enable_pathao = True

    if not is_pathao_mode:
        with st.expander("🔧 Advanced Filters", expanded=False):
            order_numbers_raw = st.text_area(
                "Order Numbers (comma-separated)",
                placeholder="e.g. 1234, 1235, 1236",
                key="ret_ext_order_numbers",
                height=80,
                help="Leave blank to include all orders in the date range.",
            )

            st.markdown("##### WC Return Status Filter")
            available_statuses = ["refunded", "cancelled", "failed"]
            selected_statuses = st.multiselect(
                "Include WC Statuses",
                options=available_statuses,
                default=available_statuses,
                key="ret_ext_statuses",
                help="Which WooCommerce order statuses to include (refunded / cancelled / failed).",
            )

            enable_pathao = st.toggle(
                "✈️ Enrich with Pathao Status & Return Reason",
                value=True,
                key="ret_ext_pathao_enabled",
                help="Fetch live Pathao tracking status and return reason for each consignment ID. "
                     "Disable to speed up extraction when Pathao data is not needed.",
            )
    else:
        # Pathao mode: Pathao data is inherent, no WC status filter needed
        st.info(
            "🚢 **Pathao Returns mode**: Fetches all parcels that Pathao has marked as **returned** "
            "in the selected date range, then enriches each with the matching WooCommerce order "
            "details (product, payment, etc.). The WC order status will show as **completed**."
        )

    # ── Validate inputs ─────────────────────────────────────────────────────
    date_valid = isinstance(start_date, date) and isinstance(end_date, date) and start_date <= end_date

    if not date_valid:
        st.error("⚠️ Start date must be before or equal to end date.")

    # ── Extract button ──────────────────────────────────────────────────────
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        extract_clicked = st.button(
            "🔍 Extract Return Orders",
            type="primary",
            use_container_width=True,
            disabled=not date_valid,
            key="btn_ret_ext_extract",
        )
    with col_clear:
        if st.button("🗑️ Clear Results", use_container_width=True, key="btn_ret_ext_clear"):
            for key in ("ret_ext_results_df", "ret_ext_last_params"):
                st.session_state.pop(key, None)
            st.rerun()

    # ── Fetch & enrich ──────────────────────────────────────────────────────
    if extract_clicked and date_valid:
        order_numbers = _parse_multivalue_input(order_numbers_raw)
        statuses_to_use = selected_statuses or DEFAULT_RETURN_STATUSES

        after_dt = datetime.combine(start_date, datetime.min.time())
        before_dt = datetime.combine(end_date, datetime.max.time())

        with st.status("🔄 Extracting return orders...", expanded=True) as status_box:
            try:
                if is_pathao_mode:
                    status_box.update(
                        label=f"📡 Querying Pathao API for returned parcels ({start_date} → {end_date})..."
                    )
                    rows, err = fetch_pathao_returned_orders(
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if err:
                        st.error(f"Pathao error: {err}")
                        return
                else:
                    # Standard date-range fetch
                    status_box.update(
                        label=f"📡 Fetching WC return orders ({start_date} → {end_date})..."
                    )
                    rows, err = fetch_wc_return_orders(
                        after_dt=after_dt,
                        before_dt=before_dt,
                        order_numbers=order_numbers if order_numbers else None,
                        statuses=statuses_to_use,
                    )
                    if err:
                        st.error(f"WooCommerce error: {err}")
                        return

                if not rows:
                    status_box.update(
                        label="ℹ️ No return orders found for the selected filters.",
                        state="complete",
                    )
                    mode_hint = (
                        "Pathao may not have any returned parcels in this date range."
                        if is_pathao_mode
                        else "Try widening the date range or checking different statuses."
                    )
                    st.info(
                        f"No return orders found for the selected date range. {mode_hint}"
                    )
                    st.session_state.pop("ret_ext_results_df", None)
                    return

                source_label = "Pathao" if is_pathao_mode else "WooCommerce"
                status_box.update(
                    label=f"✅ Loaded {len(rows)} line items from {source_label}"
                )

                # Pathao enrichment (WC mode only — Pathao mode already has status/reason)
                if not is_pathao_mode and enable_pathao:
                    cids = list({r.get("Consignment ID", "") for r in rows if r.get("Consignment ID")})
                    if cids:
                        status_box.update(
                            label=f"🔄 Enriching {len(cids)} consignment ID(s) with Pathao data..."
                        )
                        from src.services.pathao.returns import enrich_return_orders_with_pathao

                        rows = enrich_return_orders_with_pathao(rows)
                        status_box.update(
                            label=f"✅ Pathao enrichment complete for {len(cids)} consignment(s)"
                        )
                    else:
                        for r in rows:
                            r["Pathao Status"] = "N/A (No Consignment ID)"
                            r["Return Reason (Pathao)"] = ""
                elif not is_pathao_mode:
                    for r in rows:
                        r["Pathao Status"] = "N/A (Pathao disabled)"
                        r["Return Reason (Pathao)"] = ""

                df_results = pd.DataFrame(rows)
                # Coerce Order Total to numeric for calculations
                if "Order Total" in df_results.columns:
                    df_results["Order Total"] = pd.to_numeric(
                        df_results["Order Total"], errors="coerce"
                    ).fillna(0.0)

                # Sort: newest first
                if "Order Date" in df_results.columns:
                    df_results["Order Date"] = pd.to_datetime(
                        df_results["Order Date"], errors="coerce", utc=True
                    ).dt.tz_convert(BD_TZ).dt.tz_localize(None)
                    df_results = df_results.sort_values("Order Date", ascending=False)

                st.session_state["ret_ext_results_df"] = df_results
                status_box.update(
                    label=f"✅ Extraction complete — {len(df_results)} line items from "
                          f"{df_results['Order Number'].nunique() if 'Order Number' in df_results.columns else '?'} orders",
                    state="complete",
                )

            except Exception as exc:
                status_box.update(label="❌ Extraction failed", state="error")
                st.error(f"Extraction failed: {exc}")
                return

    # ── Display results ─────────────────────────────────────────────────────
    if "ret_ext_results_df" in st.session_state:
        df = st.session_state["ret_ext_results_df"].copy()

        if df.empty:
            st.info("No results to display.")
            return

        st.divider()

        # KPI Metrics
        metrics = _compute_summary_metrics(df)
        render_metric_grid(
            [
                {
                    "label": "Unique Return Orders",
                    "value": str(metrics["unique_orders"]),
                    "icon": "🔁",
                },
                {
                    "label": "Total Line Items",
                    "value": str(metrics["total_line_items"]),
                    "icon": "📦",
                },
                {
                    "label": "Estimated Value",
                    "value": f"৳ {metrics['total_value']:,.0f}",
                    "icon": "💰",
                },
                {
                    "label": "WC↔Pathao Mismatches",
                    "value": str(metrics["mismatches"]),
                    "icon": "⚠️",
                },
                {
                    "label": "With Return Reason",
                    "value": str(metrics["has_reason"]),
                    "icon": "📝",
                },
            ]
        )

        st.divider()

        # ── Inline search filter ────────────────────────────────────────────
        st.markdown("#### 📋 Extracted Return Orders")
        col_search, col_status_filter = st.columns([2, 1])

        with col_search:
            search_q = st.text_input(
                "🔍 Search results",
                placeholder="Order number, product name, phone, consignment ID…",
                key="ret_ext_inline_search",
            ).strip()

        with col_status_filter:
            if "WC Return Status" in df.columns:
                all_statuses = ["All"] + sorted(df["WC Return Status"].dropna().unique().tolist())
                status_filter_val = st.selectbox(
                    "Filter by WC Status",
                    all_statuses,
                    key="ret_ext_status_filter",
                )

        # Apply filters
        filtered_df = df.copy()
        if search_q:
            search_cols = [
                c for c in ["Order Number", "Product Description", "Phone",
                             "Consignment ID", "Customer Name", "SKU"]
                if c in filtered_df.columns
            ]
            mask = pd.Series(False, index=filtered_df.index)
            for col in search_cols:
                mask |= filtered_df[col].astype(str).str.contains(search_q, case=False, na=False)
            filtered_df = filtered_df[mask]

        if "WC Return Status" in df.columns and status_filter_val != "All":
            filtered_df = filtered_df[filtered_df["WC Return Status"] == status_filter_val]

        st.caption(f"Showing **{len(filtered_df)}** of **{len(df)}** line items")

        # Reorder columns: show available display columns in preferred order
        display_cols = [c for c in _DISPLAY_COLUMNS if c in filtered_df.columns]
        extra_cols = [c for c in filtered_df.columns if c not in display_cols]
        final_df = filtered_df[display_cols + extra_cols]

        st.dataframe(
            final_df,
            use_container_width=True,
            hide_index=True,
            column_config=_COLUMN_CONFIG,
        )

        # ── Charts ──────────────────────────────────────────────────────────
        st.divider()
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.markdown("##### 📊 WC Return Status Distribution")
            if "WC Return Status" in df.columns:
                try:
                    import plotly.express as px

                    status_counts = (
                        df.groupby("WC Return Status")["Order Number"]
                        .nunique()
                        .reset_index()
                        .rename(columns={"Order Number": "Count"})
                        .sort_values("Count", ascending=False)
                    )
                    fig = px.bar(
                        status_counts,
                        x="WC Return Status",
                        y="Count",
                        color="WC Return Status",
                        color_discrete_sequence=px.colors.qualitative.Pastel,
                    )
                    fig.update_layout(
                        showlegend=False,
                        margin=dict(t=10, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        xaxis_title=None,
                        yaxis_title="Unique Orders",
                    )
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                except ImportError:
                    st.info("Install plotly to see charts.")
            else:
                st.info("No status data available for chart.")

        with col_chart2:
            st.markdown("##### 🔄 Pathao Return Reasons")
            if "Return Reason (Pathao)" in df.columns:
                try:
                    import plotly.express as px

                    reasons = df[df["Return Reason (Pathao)"].astype(str).str.strip() != ""]
                    if not reasons.empty:
                        reason_counts = (
                            reasons["Return Reason (Pathao)"]
                            .value_counts()
                            .reset_index()
                        )
                        reason_counts.columns = ["Return Reason", "Count"]
                        fig2 = px.pie(
                            reason_counts,
                            names="Return Reason",
                            values="Count",
                            hole=0.55,
                            color_discrete_sequence=px.colors.qualitative.Set3,
                        )
                        fig2.update_layout(
                            margin=dict(t=10, b=10, l=10, r=10),
                            showlegend=True,
                            legend=dict(
                                orientation="h",
                                yanchor="bottom",
                                y=-0.3,
                                xanchor="center",
                                x=0.5,
                            ),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                        )
                        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.info("No Pathao return reasons available for this dataset. "
                                "Return reasons are provided by Pathao only for courier-returned parcels.")
                except ImportError:
                    st.info("Install plotly to see charts.")
            else:
                st.info("Pathao return reason data not available.")

        # ── Export ───────────────────────────────────────────────────────────
        st.divider()
        st.markdown("#### 📥 Export Results")
        col_xl, col_csv = st.columns(2)

        with col_xl:
            try:
                excel_bytes = _df_to_excel(df)
                today_str = bd_today().strftime("%Y-%m-%d")
                st.download_button(
                    label="📊 Download Excel Report (Multi-Sheet)",
                    data=excel_bytes,
                    file_name=f"return_orders_{today_str}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                    key="btn_ret_ext_excel",
                )
            except Exception as exc:
                st.warning(f"Excel export failed: {exc}")

        with col_csv:
            csv_data = df.to_csv(index=False).encode("utf-8-sig")
            today_str = bd_today().strftime("%Y-%m-%d")
            st.download_button(
                label="📄 Download CSV",
                data=csv_data,
                file_name=f"return_orders_{today_str}.csv",
                mime="text/csv",
                use_container_width=True,
                key="btn_ret_ext_csv",
            )
