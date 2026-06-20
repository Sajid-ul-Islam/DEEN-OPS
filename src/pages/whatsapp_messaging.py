import pandas as pd
import streamlit as st

from src.utils.logging import log_error
from src.state.persistence import clear_state_keys
from src.components.widgets import (
    render_action_bar,
    render_file_summary,
    render_reset_confirm,
)
from src.utils.file_io import to_excel_bytes, read_uploaded
from src.processing.whatsapp_processor import WhatsAppOrderProcessor

FUZZY_REQUIRED_FIELDS = {
    "phone": ["phone", "mobile", "contact", "billing phone"],
    "name": ["full name", "billing name", "name", "first name", "customer"],
    "product": ["product name", "item name", "product", "item"],
}


def _reset_wp_state():
    clear_state_keys(["wp_links_df", "wp_preview_df"])


def _has_fuzzy_column(columns: list[str], aliases: list[str]) -> bool:
    cols_lower = [str(col).strip().lower() for col in columns]
    for alias in aliases:
        alias = alias.lower()
        if alias in cols_lower:
            return True
    for alias in aliases:
        alias = alias.lower()
        if any(alias in col for col in cols_lower):
            return True
    return False


def _validate_wp_columns(df: pd.DataFrame):
    missing = []
    for field, aliases in FUZZY_REQUIRED_FIELDS.items():
        if not _has_fuzzy_column(list(df.columns), aliases):
            missing.append(field)
    return len(missing) == 0, missing


def render_wp_tab():
    render_reset_confirm("WhatsApp Messenger", "wp", _reset_wp_state)
    with st.expander("Message template customization", expanded=False):
        custom_msg = st.text_area(
            "Custom message template",
            value="",
            height=200,
            placeholder="Assalamu Alaikum, {salutation}!\n\nDear {name}, your order {order_id} is being processed.\n\nItems:\n{products_list}\n\nTotal: {total}\nAddress: {address}",
        )

    wp_file = st.file_uploader("", key="wp_up_2", type=["xlsx", "csv"])

    st.markdown('<div style="margin-top: -12px;"></div>', unsafe_allow_html=True)
    c_live, c_url = st.columns(2)
    with c_live:
        fetch_live_clicked = st.button(
            "🔗 Pull from Live Dash",
            type="secondary",
            use_container_width=True,
            key="wp_live",
        )
    with c_url:
        url_input = st.text_input("Paste public CSV/XLSX URL", key="wp_url_input", label_visibility="collapsed", placeholder="Paste public CSV/XLSX URL...")
        if url_input and st.button("Fetch URL", use_container_width=True, type="secondary", key="wp_url_fetch"):
            try:
                from src.utils.url_fetch import fetch_dataframe_from_url
                with st.spinner("Fetching from URL..."):
                    df_res = fetch_dataframe_from_url(url_input)
                    st.session_state.wp_preview_df = df_res
                    st.session_state.wp_auto_generate = True
                    st.rerun()
            except Exception as e:
                st.error(f"URL fetch failed: {e}")

    preview_df = None
    valid_file = False

    if fetch_live_clicked:
        try:
            # v9.8 Rapid In-Memory Pull
            if st.session_state.get("wc_curr_df") is not None:
                df_live = st.session_state.wc_curr_df.copy()
                source_name = "Dashboard_Live_Today"
                st.info("⚡ Instant Pull: Using Today's Active Shift data from Dashboard.")
            else:
                from src.services.woocommerce.client import load_live_source
                with st.spinner("Connecting to WooCommerce API..."):
                    df_live, source_name, _ = load_live_source()

            preview_df = df_live
            st.session_state.wp_preview_df = preview_df
            st.session_state.wp_auto_generate = True

            valid_file, missing_fields = _validate_wp_columns(preview_df)
            if valid_file:
                st.success(f"Successfully pulled {len(df_live)} records.")
            else:
                st.error(
                    f"Required fields missing in dataset: {', '.join(missing_fields)}"
                )
        except Exception as exc:
            log_error(exc, context="WP WooCommerce Pull")
            st.error(f"Failed to fetch data: {exc}")
    elif wp_file:
        try:
            preview_df = read_uploaded(wp_file)
            st.session_state.wp_preview_df = preview_df
            # Keep the summary card and use a fuzzy requirement check to avoid strict header dependence.
            render_file_summary(wp_file, preview_df, [])
            valid_file, missing_fields = _validate_wp_columns(preview_df)
            if valid_file:
                st.success("Fuzzy required-column check passed.")
            else:
                st.error(
                    f"Missing required fields (fuzzy check): {', '.join(missing_fields)}"
                )
                st.caption("Required logical fields: phone, customer name, product.")
        except Exception as exc:
            log_error(exc, context="WP Upload")
            st.error("Failed to read uploaded file.")

    generate_clicked, clear_clicked = render_action_bar(
        primary_label="Generate WhatsApp links",
        primary_key="wp_generate_btn",
        secondary_label="Clear upload",
        secondary_key="wp_clear_btn",
    )

    if clear_clicked:
        _reset_wp_state()
        st.rerun()

    if st.session_state.get("wp_auto_generate"):
        generate_clicked = True
        valid_file, _ = _validate_wp_columns(st.session_state.wp_preview_df)
        preview_df = st.session_state.wp_preview_df
        st.session_state.wp_auto_generate = False

    if generate_clicked:
        if (
            not wp_file and st.session_state.get("wp_preview_df") is None
        ) or not valid_file:
            st.warning(
                "Upload a valid verification file or pull from live dash before generating links."
            )
        else:
            try:
                processor = WhatsAppOrderProcessor()
                processed = processor.process_orders(preview_df)
                links_df = processor.create_whatsapp_links(
                    processed,
                    custom_template=custom_msg if custom_msg.strip() else None,
                )
                st.session_state.wp_links_df = links_df
                st.success(f"Generated {len(links_df)} WhatsApp links.")
            except Exception as exc:
                log_error(exc, context="WP Bulk")
                st.error("Failed to generate WhatsApp links.")

    links_df = st.session_state.get("wp_links_df")
    if links_df is not None:
        st.dataframe(links_df.head(25), use_container_width=True)

        bulk_blocks = []
        for _, row in links_df.iterrows():
            to_name = row.get("Full Name (Billing)", "Unknown")
            to_phone = row.get("Phone (Billing)", "")
            bulk_blocks.append(
                f"TO: {to_name} ({to_phone})\n{row.get('whatsapp_link', '')}"
            )

        st.download_button(
            "Export bulk message text",
            "\n\n".join(bulk_blocks),
            "Bulk_WhatsApp_Messages.txt",
            use_container_width=True,
        )
        st.download_button(
            "Download WhatsApp links (Excel)",
            to_excel_bytes(links_df, sheet_name="WhatsAppLinks"),
            "WhatsApp_Verification_Links.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

        with st.expander("📝 Copy Individual Summaries", expanded=True):
            for _, row in links_df.head(20).iterrows():
                summary = row.get("order_summary", "No summary available")
                st.code(summary, language="text")

        with st.expander("Open first 10 links", expanded=False):
            preview_rows = links_df.head(10)
            for _, row in preview_rows.iterrows():
                label = f"{row.get('Full Name (Billing)', 'Unknown')} ({row.get('Phone (Billing)', '')})"
                st.link_button(label, row.get("whatsapp_link", ""))
