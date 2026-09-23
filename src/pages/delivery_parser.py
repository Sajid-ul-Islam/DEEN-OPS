import pandas as pd
import plotly.express as px
import streamlit as st

from src.components.ui.dataframe_search import render_dataframe_search
from src.components.ui.ui_components import render_premium_header
from src.components.ui.widgets import (
    render_action_bar,
    render_reset_confirm,
    section_card,
)
from src.config.constants import bd_today
from src.processing.delivery_parser import parse_data_fuzzy, parse_records
from src.processing.order_processor import normalize_manual_item_input
from src.state.persistence import clear_state_keys
from src.utils.file_io import to_excel_bytes


def _style_deliveries_sheet(ws, _wb):
    """Apply delivery-specific formatting to the exported Excel sheet."""
    ws.freeze_panes = "A2"
    widths = {
        "A": 18,
        "B": 10,
        "C": 12,
        "D": 18,
        "E": 20,
        "F": 60,
        "G": 14,
        "H": 30,
        "I": 16,
        "J": 12,
        "K": 10,
        "L": 10,
        "M": 14,
        "N": 14,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row in range(2, ws.max_row + 1):
        ws[f"J{row}"].number_format = "#,##0.00"
        ws[f"K{row}"].number_format = "#,##0.00"
        ws[f"L{row}"].number_format = "#,##0.00"


def _reset_parser_state():
    clear_state_keys(["standard_parsed_df", "fuzzy_parsed_df"])


def render_visual_report(df: pd.DataFrame):
    """Render a visual summary report for parsed delivery data."""
    if df is None or df.empty:
        return

    st.divider()
    st.subheader(":material/bar_chart: Visual Report")

    # ── KPI metrics ──────────────────────────────────────────────────────────
    total = len(df)
    payment_col = (
        df["Payment Status"] if "Payment Status" in df.columns else pd.Series(dtype=str)
    )
    paid_count = (payment_col.astype(str).str.lower() == "paid").sum()
    unpaid_count = total - paid_count
    total_cod = (
        float(pd.to_numeric(df["COD Amount"], errors="coerce").fillna(0).sum())
        if "COD Amount" in df.columns
        else 0.0
    )
    total_charge = (
        float(pd.to_numeric(df["Charge"], errors="coerce").fillna(0).sum())
        if "Charge" in df.columns
        else 0.0
    )
    total_discount = (
        float(pd.to_numeric(df["Discount"], errors="coerce").fillna(0).sum())
        if "Discount" in df.columns
        else 0.0
    )
    net_revenue = total_cod - total_charge + total_discount

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Parcels", total)
    c2.metric("Paid", int(paid_count))
    c3.metric("Unpaid", int(unpaid_count))
    c4.metric("Total COD", f"৳{total_cod:,.0f}")
    c5.metric("Net (COD − Charge + Disc.)", f"৳{net_revenue:,.0f}")

    st.write("")

    col_left, col_right = st.columns(2)

    # ── Payment status pie ────────────────────────────────────────────────────
    if "Payment Status" in df.columns and not df["Payment Status"].dropna().empty:
        with col_left:
            payment_counts = (
                df["Payment Status"].fillna("Unknown").value_counts().reset_index()
            )
            payment_counts.columns = ["Status", "Count"]
            fig_pay = px.pie(
                payment_counts,
                names="Status",
                values="Count",
                title="Payment Status Breakdown",
                color_discrete_sequence=px.colors.qualitative.Set2,
                hole=0.4,
            )
            fig_pay.update_traces(textposition="inside", textinfo="percent+label")
            fig_pay.update_layout(showlegend=False, margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig_pay, use_container_width=True)

    # ── Delivery status bar ───────────────────────────────────────────────────
    if "Delivery Status" in df.columns and not df["Delivery Status"].dropna().empty:
        with col_right:
            status_counts = (
                df["Delivery Status"]
                .replace("", "Unknown")
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            status_counts.columns = ["Delivery Status", "Count"]
            fig_status = px.bar(
                status_counts,
                x="Count",
                y="Delivery Status",
                orientation="h",
                title="Delivery Status Distribution",
                color="Count",
                color_continuous_scale="Blues",
                text="Count",
            )
            fig_status.update_traces(textposition="outside")
            fig_status.update_layout(
                yaxis=dict(autorange="reversed"),
                coloraxis_showscale=False,
                margin=dict(t=40, b=10, l=10, r=10),
            )
            st.plotly_chart(fig_status, use_container_width=True)

    # ── Store breakdown (only if multiple stores present) ────────────────────
    if "Store" in df.columns and df["Store"].nunique() > 1:
        store_counts = (
            df["Store"]
            .replace("", "Unknown")
            .fillna("Unknown")
            .value_counts()
            .reset_index()
        )
        store_counts.columns = ["Store", "Parcels"]
        fig_store = px.bar(
            store_counts,
            x="Store",
            y="Parcels",
            title="Parcels by Store",
            color="Store",
            color_discrete_sequence=px.colors.qualitative.Pastel,
            text="Parcels",
        )
        fig_store.update_traces(textposition="outside")
        fig_store.update_layout(showlegend=False, margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig_store, use_container_width=True)

    # ── Financial Distribution Chart ─────────────────────────────────────────
    if "COD Amount" in df.columns and not df["COD Amount"].dropna().empty:
        cod_series = pd.to_numeric(df["COD Amount"], errors="coerce").dropna()
        if not cod_series.empty:
            fig_cod = px.histogram(
                cod_series,
                x="COD Amount",
                nbins=20,
                title="COD Amount Distribution",
                color_discrete_sequence=["#3b82f6"],
            )
            fig_cod.update_layout(
                xaxis_title="COD Amount (৳)",
                yaxis_title="Number of Parcels",
                margin=dict(t=40, b=10, l=10, r=10),
            )
            st.plotly_chart(fig_cod, use_container_width=True)


def render_delivery_parser_content():
    """Render the Smart Delivery Data Parser feature."""
    render_reset_confirm("Delivery Data Parser", "parser", _reset_parser_state)

    st.markdown("### 🧩 Smart Delivery Data Parser")
    st.caption(
        "Paste copied courier or delivery detail blocks (standard or unstructured). "
        "The smart engine applies pattern recognition and automatic fuzzy fallback to extract parcels, COD amounts, and customer details."
    )

    raw_text = st.text_area(
        "Courier Data Input",
        value="",
        height=180,
        placeholder="Paste copied courier detail blocks (e.g., standard Pathao/courier logs or unstructured notes)...",
        key="delivery_parser_raw_text",
        label_visibility="collapsed",
    )

    col_btn, col_opt = st.columns([2, 1])
    with col_opt:
        force_fuzzy = st.checkbox(
            "Force Aggressive Fuzzy Mode",
            value=False,
            help="Bypasses standard parsing rules to handle heavily irregular or fragmented text directly with fuzzy pattern matching.",
            key="delivery_force_fuzzy",
        )
    with col_btn:
        parse_clicked, _ = render_action_bar(
            "Parse Delivery Records",
            "delivery_parse_btn",
        )

    if parse_clicked:
        if not raw_text.strip():
            st.warning("Please paste some text before parsing.")
        else:
            with st.status(
                "🧩 Processing delivery records...", expanded=True
            ) as parse_status:
                parsed_df = pd.DataFrame()
                if not force_fuzzy:
                    parse_status.update(label="🔍 Applying standard parsing rules...")
                    try:
                        parsed_df = parse_records(raw_text)
                    except Exception:
                        parsed_df = pd.DataFrame()

                if parsed_df.empty:
                    parse_status.update(
                        label="🔄 Applying intelligent fuzzy matching..."
                    )
                    try:
                        parsed_df = parse_data_fuzzy(raw_text)
                    except Exception:
                        parsed_df = pd.DataFrame()
                else:
                    parse_status.update(
                        label="✅ Standard parsing succeeded", state="complete"
                    )

                if not parsed_df.empty:
                    parse_status.update(
                        label=f"✅ Successfully parsed {len(parsed_df)} records",
                        state="complete",
                    )
                    st.session_state.parsed_delivery_df = parsed_df
                    st.toast(f"✅ Parsed {len(parsed_df)} delivery records!")
                else:
                    parse_status.update(
                        label="❌ No valid records detected", state="error"
                    )
                    st.error(
                        "No valid delivery records could be parsed from the provided input."
                    )

    parsed_df = st.session_state.get("parsed_delivery_df")
    if parsed_df is None:
        parsed_df = st.session_state.get("standard_parsed_df")
    if parsed_df is None:
        parsed_df = st.session_state.get("fuzzy_parsed_df")

    if parsed_df is not None and not parsed_df.empty:
        calc_height = min(800, max(400, len(parsed_df) * 35 + 43))
        search_df = render_dataframe_search(parsed_df, "delivery_parsed_search")
        st.dataframe(search_df, use_container_width=True, height=calc_height)
        render_visual_report(parsed_df)
        st.download_button(
            "📥 Download Parsed Deliveries (Excel)",
            to_excel_bytes(
                parsed_df,
                sheet_name="Deliveries",
                style_fn=_style_deliveries_sheet,
            ),
            f"deliveries_{bd_today().strftime('%d-%m-%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )


def render_item_description_content():
    """Item Description Helper — normalize, sort, and generate standard item descriptions."""
    section_card(
        "Item Description Helper",
        "Paste one item per line to normalize, sort, and generate standard item descriptions for bulk dispatch and order fulfillment.",
    )
    st.caption(
        "Supported formats: `2x Item Name`, `Item Name x2`, `Item Name (2 pcs)`, or `Item Name | SKU123`."
    )

    raw_items = st.text_area(
        "Manual item input",
        key="data_parser_manual_items",
        height=220,
        placeholder="2x Oxford Shirt - Navy | SKU123\nPolo Shirt x1\nJeans (2 pcs)",
    )

    if st.button(
        "Normalize and sort items",
        type="primary",
        use_container_width=True,
        key="data_parser_manual_normalize",
    ):
        if not raw_items.strip():
            st.warning("Enter at least one item line.")
        else:
            normalized_items, description = normalize_manual_item_input(raw_items)
            st.session_state.data_parser_manual_items_df = pd.DataFrame(
                normalized_items
            )
            st.session_state.data_parser_manual_desc = description

    normalized_df = st.session_state.get(
        "data_parser_manual_items_df"
    ) or st.session_state.get("pathao_manual_items_df")
    manual_desc = st.session_state.get(
        "data_parser_manual_desc"
    ) or st.session_state.get("pathao_manual_desc")

    if normalized_df is not None and not normalized_df.empty:
        display_df = normalized_df.rename(
            columns={"category": "Category", "label": "Normalized Item", "qty": "Qty"}
        )
        with st.expander("Normalized items", expanded=True):
            st.dataframe(display_df, use_container_width=True, hide_index=True)

    if manual_desc:
        from src.components.ui.clipboard import render_copy_button

        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown("#### Generated Item Description")
        with c2:
            render_copy_button(manual_desc, label="Copy ItemDesc")
        st.code(manual_desc)


def render_data_parser_tab():
    """Render unified Data Parser page with Delivery Data Parser and Item Description Helper features."""
    render_premium_header(
        "Data Parser",
        "Extract structured delivery courier records and normalize manual item descriptions for fulfillment",
        "🧩",
    )

    tab_delivery, tab_item_desc = st.tabs(
        [
            ":material/data_object: Delivery Data Parser",
            ":material/build: Item Description Helper",
        ]
    )
    with tab_delivery:
        render_delivery_parser_content()
    with tab_item_desc:
        render_item_description_content()


def render_fuzzy_parser_tab():
    """Backward-compatible entry point for Delivery Data Parser feature."""
    render_delivery_parser_content()
