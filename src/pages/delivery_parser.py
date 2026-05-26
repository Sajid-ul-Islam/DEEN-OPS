import pandas as pd
import streamlit as st
from datetime import datetime

from src.state.persistence import clear_state_keys
from src.components.widgets import render_action_bar, render_reset_confirm
from src.processing.delivery_parser import parse_records, parse_data_fuzzy, df_to_excel_bytes


def _reset_parser_state():
    clear_state_keys(["standard_parsed_df", "fuzzy_parsed_df"])


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
            st.download_button(
                "Download fuzzy parser output",
                df_to_excel_bytes(st.session_state.fuzzy_parsed_df),
                f"fuzzy_deliveries_{datetime.now().strftime('%d-%m-%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
