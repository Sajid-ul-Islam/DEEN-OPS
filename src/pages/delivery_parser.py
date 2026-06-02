import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import datetime

from src.state.persistence import clear_state_keys
from src.components.widgets import render_action_bar, render_reset_confirm
from src.processing.delivery_parser import parse_records, parse_data_fuzzy, df_to_excel_bytes


def _reset_parser_state():
    clear_state_keys(["standard_parsed_df", "fuzzy_parsed_df"])


def render_visual_report(df: pd.DataFrame):
    """Render a visual summary report for parsed delivery data."""
    st.divider()
    st.subheader(":material/bar_chart: Visual Report")

    # ── KPI metrics ──────────────────────────────────────────────────────────
    total = len(df)
    paid_count = (df["Payment Status"].str.lower() == "paid").sum()
    unpaid_count = total - paid_count
    total_cod = df["COD Amount"].sum()
    total_charge = df["Charge"].sum()
    total_discount = df["Discount"].sum()
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
    with col_left:
        payment_counts = df["Payment Status"].value_counts().reset_index()
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
    with col_right:
        status_counts = (
            df["Delivery Status"]
            .replace("", "Unknown")
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
    if df["Store"].nunique() > 1:
        store_counts = df["Store"].replace("", "Unknown").value_counts().reset_index()
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

    # ── COD amount distribution histogram ────────────────────────────────────
    cod_nonzero = df[df["COD Amount"] > 0]["COD Amount"]
    if not cod_nonzero.empty:
        fig_cod = px.histogram(
            cod_nonzero,
            x=cod_nonzero,
            nbins=20,
            title="COD Amount Distribution",
            labels={"x": "COD Amount (৳)"},
            color_discrete_sequence=["#636EFA"],
        )
        fig_cod.update_layout(
            bargap=0.05,
            xaxis_title="COD Amount (৳)",
            yaxis_title="Number of Parcels",
            margin=dict(t=40, b=10, l=10, r=10),
        )
        st.plotly_chart(fig_cod, use_container_width=True)


def render_fuzzy_parser_tab():
    render_reset_confirm("Delivery Data Parser", "parser", _reset_parser_state)
    # section_card("Delivery Text Parser", "")

    sample = """Cons. ID
DD040326KR9NUU
Type:
Parcel
193252
Deen Commerce
Raafin
House 10, Road 15, Sector 11, Uttara West, Dhaka
01745166722
At Delivery Hub
Updated on 05/03/2026
COD 0
Charge 50
Discount 10
Unpaid
View
POD"""

    tab1, tab2 = st.tabs([":material/rule: Standard Parser", ":material/psychology_alt: Fuzzy Parser"])

    with tab1:
        raw_text = st.text_area(
            "",
            value="",
            height=150,
            placeholder="Paste copied courier detail blocks...",
            key="standard_raw_text",
        )
        parse_clicked, _ = render_action_bar(
            "Parse with standard rules",
            "standard_btn",
        )

        if parse_clicked:
            parsed_df = parse_records(raw_text)
            if parsed_df.empty:
                st.error("No records were found from standard parser input.")
            else:
                st.session_state.standard_parsed_df = parsed_df
                st.success(f"Parsed {len(parsed_df)} records.")

        if st.session_state.get("standard_parsed_df") is not None:
            df_to_show = st.session_state.standard_parsed_df
            calc_height = min(800, max(400, len(df_to_show) * 35 + 43))
            st.dataframe(df_to_show, use_container_width=True, height=calc_height)
            render_visual_report(df_to_show)
            st.download_button(
                "Download standard parser output",
                df_to_excel_bytes(st.session_state.standard_parsed_df),
                f"deliveries_{datetime.now().strftime('%d-%m-%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )

    with tab2:
        fuzzy_raw_text = st.text_area(
            "",
            value="",
            height=150,
            placeholder="Paste loosely structured text here...",
            key="fuzzy_raw_text",
        )
        fuzzy_parse_clicked, _ = render_action_bar(
            "Parse with fuzzy fallback",
            "fuzzy_btn",
        )

        if fuzzy_parse_clicked:
            if not fuzzy_raw_text.strip():
                st.warning("Paste some text before parsing.")
            else:
                with st.spinner("Processing text..."):
                    try:
                        parsed_df = parse_records(fuzzy_raw_text)
                    except Exception:
                        parsed_df = pd.DataFrame()
                    if parsed_df.empty:
                        try:
                            parsed_df = parse_data_fuzzy(fuzzy_raw_text)
                        except Exception:
                            parsed_df = pd.DataFrame()

                if parsed_df.empty:
                    st.error("No valid records found from fuzzy parser input.")
                else:
                    st.session_state.fuzzy_parsed_df = parsed_df
                    st.success(f"Parsed {len(parsed_df)} records using fuzzy fallback.")

        if st.session_state.get("fuzzy_parsed_df") is not None:
            df_to_show_fuzzy = st.session_state.fuzzy_parsed_df
            calc_height_fuzzy = min(800, max(400, len(df_to_show_fuzzy) * 35 + 43))
            st.dataframe(df_to_show_fuzzy, use_container_width=True, height=calc_height_fuzzy)
            render_visual_report(df_to_show_fuzzy)
            st.download_button(
                "Download fuzzy parser output",
                df_to_excel_bytes(st.session_state.fuzzy_parsed_df),
                f"fuzzy_deliveries_{datetime.now().strftime('%d-%m-%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
