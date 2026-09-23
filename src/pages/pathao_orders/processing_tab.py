"""Order Processing and Item Description Helper tabs."""

from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from src.components.ui.dataframe_search import render_dataframe_search
from src.components.ui.status import render_status_toggle
from src.components.ui.widgets import (
    render_reset_confirm,
    render_sticky_action_bar,
    section_card,
)
from src.pages.pathao_orders.shared import (
    REQUIRED_COLUMNS,
    SOURCE_UPLOAD,
    SOURCE_WOOCOM,
    _highlight_split_orders,
    _load_processing_orders_from_woocommerce,
    _reset_pathao_state,
    _sync_pathao_map,
)
from src.processing.order_processor import (
    normalize_manual_item_input,
    process_orders_dataframe,
)
from src.services.exports.excel_exporter import export_to_styled_excel
from src.state.persistence import save_state
from src.utils.file_io import read_uploaded
from src.utils.logging import log_error


# Standard column names the processor expects
STANDARD_COLUMNS = [
    "Phone (Billing)",
    "Full Name (Shipping)",
    "First Name (Shipping)",
    "Last Name (Shipping)",
    "Address 1&2 (Shipping)",
    "City (Shipping)",
    "State Code (Shipping)",
    "Order ID",
    "Order Number",
    "Item Name",
    "Quantity",
    "Item Cost",
    "Order Total Amount",
    "Payment Method Title",
    "SIP",
    "Item Outlet",
    "SKU",
    "Dispatch Suggestion",
]

ORDER_ID_ALIASES = [
    "Order ID",
    "Order Number",
    "Order #",
    "Order No",
    "Order No.",
    "ID",
    "Order_ID",
    "Order_Number",
    "Order_No",
    "order_id",
    "order_number",
    "order no",
    "order #",
    "order id",
    "order number",
    "Invoice Number",
    "Invoice #",
    "Invoice No",
    "Invoice_No",
    "MerchantOrderId",
    "Merchant Order ID",
    "Merchant Order Id",
    "merchant_order_id",
]

# Common aliases found in uploaded files
COLUMN_ALIASES: Dict[str, List[str]] = {
    "Phone (Billing)": [
        "Phone",
        "Phone (Shipping)",
        "Billing Phone",
        "Customer Phone",
        "Phone Number",
        "Mobile",
        "Contact",
    ],
    "Full Name (Shipping)": [
        "Full Name",
        "Full Name (Shipping)",
        "Full Name (Billing)",
        "Customer Name",
        "Recipient Name",
        "Billing Name",
        "Name",
        "Customer",
    ],
    "First Name (Shipping)": [
        "First Name",
        "Shipping First Name",
        "First Name (Shipping)",
        "First Name (Billing)",
        "Billing First Name",
    ],
    "Last Name (Shipping)": [
        "Last Name",
        "Shipping Last Name",
        "Last Name (Shipping)",
        "Last Name (Billing)",
        "Billing Last Name",
        "Surname",
    ],
    "Address 1&2 (Shipping)": [
        "Address",
        "Shipping Address",
        "Delivery Address",
        "Address (Shipping)",
    ],
    "City (Shipping)": ["City", "Shipping City", "Town", "Area"],
    "State Code (Shipping)": [
        "State",
        "State Code",
        "Shipping State",
        "District",
        "Zone",
        "Region",
    ],
    "Order ID": ORDER_ID_ALIASES,
    "Order Number": ORDER_ID_ALIASES,
    "Item Name": ["Item Name", "Product Name", "Product", "Item", "SKU Name"],
    "Quantity": [
        "Quantity",
        "Qty",
        "Item Qty",
        "Quantity (- Refund)",
        "Quantity (Refund)",
        "Quantity(-Refund)",
    ],
    "Item Cost": [
        "Item Cost",
        "Price",
        "Unit Price",
        "Line Item Price",
        "Item Price",
        "Cost",
        "Line Total",
    ],
    "Order Total Amount": [
        "Order Total Amount",
        "Total",
        "Grand Total",
        "Order Total",
        "Total Amount",
        "Order Amount",
    ],
    "Payment Method Title": ["Payment Method", "Payment", "Payment Method Title"],
    "SIP": [
        "SIP",
        "sip",
        "SIP Stock",
        "Outlet SIP",
        "Outlet Stock",
        "SIP Outlet",
        "Routing",
        "Outlet Routing",
    ],
    "Item Outlet": [
        "Item Outlet",
        "item_outlet",
        "Outlet",
        "outlet",
        "Dispatch Outlet",
        "Fulfillment Outlet",
        "Branch",
        "Store",
    ],
    "SKU": [
        "SKU",
        "Item SKU",
        "Product SKU",
        "SKU Code",
        "sku",
        "Item_SKU",
        "Product_SKU",
    ],
    "Dispatch Suggestion": [
        "Dispatch Suggestion",
        "Dispatch",
        "Location",
        "Outlet Location",
    ],
}


REQUIRED_UPLOAD_COLUMNS = [
    "Phone (Billing)",
    "Address 1&2 (Shipping)",
    "Item Name",
    "Quantity",
    "Item Cost",
    "Order Total Amount",
]

OPTIONAL_UPLOAD_COLUMNS = {
    "SIP",
    "Item Outlet",
    "SKU",
    "Dispatch Suggestion",
    "Payment Method Title",
    "Last Name (Shipping)",
    "City (Shipping)",
    "State Code (Shipping)",
}


def _invalidate_processing_result():
    """Discard output that no longer belongs to the currently approved input."""
    had_result = st.session_state.get("pathao_res_df") is not None
    st.session_state.pathao_res_df = None
    st.session_state.pathao_vlink_df = None
    st.session_state.show_vlink_gen = False
    st.session_state.pathao_auto_process = False
    if had_result:
        save_state()


def _clear_processing_source():
    _invalidate_processing_result()
    st.session_state.pathao_preview_df = None
    st.session_state.pathao_preview_source = None
    st.session_state.pathao_upload_fingerprint = None
    st.session_state.pathao_mapping_confirmation = None
    for key in list(st.session_state):
        if key.startswith("pathao_map_"):
            del st.session_state[key]


def _upload_fingerprint(uploaded_file):
    """Use file contents as well as its name; uploader objects change on reruns."""
    return (
        uploaded_file.name,
        hashlib.sha256(uploaded_file.getvalue()).hexdigest(),
    )


def _detect_and_map_columns(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, Dict[str, str], List[str]]:
    """
    Detect columns in uploaded file and map them to standard names.
    Accepts recipient name either as Full Name or First Name + Last Name (merging them).
    Treats Order ID and Order Number as interchangeable equivalents.
    Returns: (mapped_df, mapping_dict, missing_columns)
    """
    df_mapped = df.copy()
    mapping = {}
    missing = []

    available_cols = set(df.columns)
    col_lookup = {str(c).strip().lower(): c for c in df.columns}

    for standard, aliases in COLUMN_ALIASES.items():
        # Check if standard column already exists
        if standard in available_cols:
            mapping[standard] = standard
            continue
        elif standard.lower() in col_lookup:
            matched = col_lookup[standard.lower()]
            df_mapped[standard] = df[matched].copy()
            mapping[standard] = matched
            continue

        # Try to find an alias
        found = False
        for alias in aliases:
            if alias in available_cols:
                df_mapped[standard] = df[alias].copy()
                mapping[standard] = alias
                found = True
                break
            elif alias.strip().lower() in col_lookup:
                matched = col_lookup[alias.strip().lower()]
                df_mapped[standard] = df[matched].copy()
                mapping[standard] = matched
                found = True
                break

        if not found:
            missing.append(standard)
            mapping[standard] = None

    # Name resolution:
    # 1. If Full Name is present: take it!
    # 2. If Full Name is NOT present, but First Name and/or Last Name are present: merge them into Full Name!
    has_full_name = (
        mapping.get("Full Name (Shipping)") is not None
        and (
            df_mapped["Full Name (Shipping)"].notna()
            & df_mapped["Full Name (Shipping)"].astype(str).str.strip().ne("")
        ).any()
    )
    first_mapped = mapping.get("First Name (Shipping)")
    last_mapped = mapping.get("Last Name (Shipping)")

    if not has_full_name and (first_mapped or last_mapped):
        first_s = (
            df_mapped["First Name (Shipping)"].fillna("").astype(str).str.strip()
            if first_mapped
            else pd.Series("", index=df_mapped.index)
        )
        last_s = (
            df_mapped["Last Name (Shipping)"].fillna("").astype(str).str.strip()
            if last_mapped
            else pd.Series("", index=df_mapped.index)
        )
        merged = (first_s + " " + last_s).str.strip()
        df_mapped["Full Name (Shipping)"] = merged
        parts = [p for p in (first_mapped, last_mapped) if p]
        mapping["Full Name (Shipping)"] = " + ".join(parts)
        if "Full Name (Shipping)" in missing:
            missing.remove("Full Name (Shipping)")
    elif has_full_name:
        # Also ensure First Name (Shipping) is populated from Full Name for legacy downstream readers
        if not first_mapped:
            df_mapped["First Name (Shipping)"] = df_mapped["Full Name (Shipping)"]
            mapping["First Name (Shipping)"] = mapping["Full Name (Shipping)"]
            if "First Name (Shipping)" in missing:
                missing.remove("First Name (Shipping)")

    # Order ID / Order Number equivalence resolution:
    # "Order ID" and "Order Number" are interchangeable in order processing.
    # If either one is present, automatically populate the other.
    id_mapped = mapping.get("Order ID")
    num_mapped = mapping.get("Order Number")

    if id_mapped and not num_mapped:
        df_mapped["Order Number"] = df_mapped["Order ID"].copy()
        mapping["Order Number"] = id_mapped
        if "Order Number" in missing:
            missing.remove("Order Number")
    elif num_mapped and not id_mapped:
        df_mapped["Order ID"] = df_mapped["Order Number"].copy()
        mapping["Order ID"] = num_mapped
        if "Order ID" in missing:
            missing.remove("Order ID")

    return df_mapped, mapping, missing


def _render_column_mapping_ui(df: pd.DataFrame) -> tuple[Optional[pd.DataFrame], bool]:
    """
    Render UI for users to confirm/change column mappings.
    Returns: (mapped_df, is_confirmed)
    """
    st.markdown("### 🔍 Column Detection")

    # Auto-detect columns
    df_mapped, mapping, _ = _detect_and_map_columns(df)

    # Show detection results
    detected_cols = {k: v for k, v in mapping.items() if v is not None}
    undetected_cols = [k for k, v in mapping.items() if v is None]

    # If customer name is already mapped (via Full Name or First/Last), do not display
    # the unused name variations as undetected missing columns.
    has_name_mapped = (
        mapping.get("Full Name (Shipping)") is not None
        or mapping.get("First Name (Shipping)") is not None
    )
    if has_name_mapped:
        undetected_cols = [
            k
            for k in undetected_cols
            if k
            not in (
                "Full Name (Shipping)",
                "First Name (Shipping)",
                "Last Name (Shipping)",
            )
        ]

    # If Order ID or Order Number is mapped, do not display the other as undetected
    has_order_mapped = (
        mapping.get("Order ID") is not None or mapping.get("Order Number") is not None
    )
    if has_order_mapped:
        undetected_cols = [
            k for k in undetected_cols if k not in ("Order ID", "Order Number")
        ]
    # Exclude optional columns (SIP, Item Outlet, SKU, etc.) from undetected prompt
    undetected_cols = [k for k in undetected_cols if k not in OPTIONAL_UPLOAD_COLUMNS]

    if detected_cols:
        st.success(f"✅ Detected {len(detected_cols)} columns automatically")
        with st.expander("View detected mappings", expanded=False):
            for standard, source in detected_cols.items():
                if standard == source:
                    st.text(f"✓ {standard}")
                else:
                    st.text(f"✓ {standard} ← mapped from '{source}'")

    if undetected_cols:
        st.warning(
            f"⚠️ {len(undetected_cols)} columns not found: {', '.join(undetected_cols[:5])}"
        )
        if len(undetected_cols) > 5:
            st.caption(f"...and {len(undetected_cols) - 5} more")

    # Show manual mapping interface for missing columns
    if undetected_cols:
        st.markdown("#### Manual Column Mapping")
        st.caption(
            "Map the missing fields below. Last name, city, state and payment method "
            "are optional; either order ID or order number is required."
        )

        all_file_cols = list(df.columns)
        custom_mapping = {}

        cols_grid = st.columns(2)
        for idx, required_col in enumerate(undetected_cols):
            with cols_grid[idx % 2]:
                selected = st.selectbox(
                    f"Select column for '{required_col}'",
                    options=["-- None --"] + all_file_cols,
                    key=f"pathao_map_{required_col}",
                    index=0,
                )
                if selected != "-- None --":
                    custom_mapping[required_col] = selected

        # Apply custom mappings
        if custom_mapping:
            st.info(f"🔧 Applying {len(custom_mapping)} custom mappings...")
            for required_col, source_col in custom_mapping.items():
                df_mapped[required_col] = df[source_col].copy()
                mapping[required_col] = source_col

            # Sync Order ID and Order Number if either was custom mapped
            if "Order ID" in custom_mapping and "Order Number" not in custom_mapping:
                df_mapped["Order Number"] = df[custom_mapping["Order ID"]].copy()
                mapping["Order Number"] = custom_mapping["Order ID"]
            elif "Order Number" in custom_mapping and "Order ID" not in custom_mapping:
                df_mapped["Order ID"] = df[custom_mapping["Order Number"]].copy()
                mapping["Order ID"] = custom_mapping["Order Number"]

            # Re-evaluate name merging if custom mapping changed name columns
            if "Full Name (Shipping)" in custom_mapping:
                df_mapped["First Name (Shipping)"] = df_mapped["Full Name (Shipping)"]
            elif (
                "First Name (Shipping)" in custom_mapping
                or "Last Name (Shipping)" in custom_mapping
            ):
                f_col = custom_mapping.get(
                    "First Name (Shipping)", mapping.get("First Name (Shipping)")
                )
                l_col = custom_mapping.get(
                    "Last Name (Shipping)", mapping.get("Last Name (Shipping)")
                )
                f_s = (
                    df[f_col].fillna("").astype(str).str.strip()
                    if f_col and f_col in df.columns
                    else pd.Series("", index=df.index)
                )
                l_s = (
                    df[l_col].fillna("").astype(str).str.strip()
                    if l_col and l_col in df.columns
                    else pd.Series("", index=df.index)
                )
                df_mapped["Full Name (Shipping)"] = (f_s + " " + l_s).str.strip()

            # Refresh missing list
            undetected_cols = [k for k, v in mapping.items() if v is None]
            if (
                mapping.get("Full Name (Shipping)") is not None
                or mapping.get("First Name (Shipping)") is not None
            ):
                undetected_cols = [
                    k
                    for k in undetected_cols
                    if k
                    not in (
                        "Full Name (Shipping)",
                        "First Name (Shipping)",
                        "Last Name (Shipping)",
                    )
                ]
            if (
                mapping.get("Order ID") is not None
                or mapping.get("Order Number") is not None
            ):
                undetected_cols = [
                    k for k in undetected_cols if k not in ("Order ID", "Order Number")
                ]
            undetected_cols = [
                k for k in undetected_cols if k not in OPTIONAL_UPLOAD_COLUMNS
            ]

    def has_values(column):
        return (
            column in df_mapped
            and (
                df_mapped[column].notna()
                & df_mapped[column].astype(str).str.strip().ne("")
            ).any()
        )

    required_missing = [col for col in REQUIRED_UPLOAD_COLUMNS if not has_values(col)]
    has_name = has_values("Full Name (Shipping)") or has_values("First Name (Shipping)")
    if not has_name:
        required_missing.append("Customer Name (Full Name or First/Last Name)")

    if not any(has_values(col) for col in ("Order ID", "Order Number")):
        required_missing.append("Order ID or Order Number")
    if df.empty:
        st.error("The uploaded file has no order rows.")
    if required_missing:
        st.error("Map columns containing values for: " + ", ".join(required_missing))

    confirmation = (
        st.session_state.get("pathao_upload_fingerprint"),
        tuple(mapping.items()),
    )
    if st.session_state.get("pathao_mapping_confirmation") != confirmation:
        st.session_state.pathao_mapping_confirmation = None
        _invalidate_processing_result()

    # User confirmation
    st.markdown("---")
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(
            f"Ready to process {len(df)} rows with {len([k for k, v in mapping.items() if v])} mapped columns"
        )
    with c2:
        confirm_btn = st.button(
            "✓ Confirm & Process",
            type="primary",
            use_container_width=True,
            key="confirm_columns",
            disabled=bool(required_missing) or df.empty,
        )

    if confirm_btn and not required_missing and not df.empty:
        st.session_state.pathao_mapping_confirmation = confirmation
        st.session_state.pathao_auto_process = True

    if (
        st.session_state.get("pathao_mapping_confirmation") == confirmation
        and not required_missing
        and not df.empty
    ):
        return df_mapped, True

    return None, False


def _render_processing_tab():
    for key, default in {
        "pathao_res_df": None,
        "pathao_preview_df": None,
        "pathao_preview_source": None,
        "pathao_vlink_df": None,
        "show_vlink_gen": False,
        "pathao_auto_process": False,
        "pathao_source_mode_last": None,
        "pathao_upload_fingerprint": None,
        "pathao_mapping_confirmation": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    render_reset_confirm("Pathao Processor", "pathao", _reset_pathao_state)

    with st.expander("Pathao API & Sync Settings", expanded=False):
        st.markdown("### Location Database Sync")

        pathao_map_path = "resources/pathao_map.json"
        if os.path.exists(pathao_map_path):
            from datetime import datetime

            modified_at = os.path.getmtime(pathao_map_path)
            updated_str = datetime.fromtimestamp(modified_at).strftime("%Y-%m-%d %H:%M")
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

        if st.button("🔄 Update Pathao Courier Zones", use_container_width=True):
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
            key="pathao_source_mode_pills",
            label_visibility="collapsed",
        )
        if not source_mode:
            source_mode = SOURCE_WOOCOM
    else:
        source_mode = st.radio(
            "Select input source",
            [SOURCE_WOOCOM, SOURCE_UPLOAD],
            horizontal=True,
            key="pathao_source_mode_radio",
            label_visibility="collapsed",
        )

    if st.session_state.get("pathao_source_mode_last") != source_mode:
        _clear_processing_source()
        st.session_state.pathao_source_mode_last = source_mode

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
        st.caption("Upload an Excel or CSV export.")

    if fetch_live_clicked:
        _clear_processing_source()
        try:
            preview_df, used_status_filter = _load_processing_orders_from_woocommerce()
            st.session_state.pathao_preview_df = preview_df
            st.session_state.pathao_preview_source = source_mode

            phone_cols_present = [
                c for c in REQUIRED_COLUMNS if c in preview_df.columns
            ]
            valid_file = len(phone_cols_present) > 0 and not preview_df.empty
            st.session_state.pathao_auto_process = valid_file

            if preview_df.empty and used_status_filter:
                st.warning("No WooCommerce rows are currently in `processing` status.")
            else:
                st.toast(f"📥 Successfully pulled {len(preview_df)} processing rows.")
        except Exception as exc:
            log_error(exc, context="Pathao WooCommerce Pull")
            st.error(f"Failed to fetch data: {exc}")
    elif uploaded_file:
        try:
            fingerprint = _upload_fingerprint(uploaded_file)
            if st.session_state.pathao_upload_fingerprint != fingerprint:
                _clear_processing_source()
                st.session_state.pathao_upload_fingerprint = fingerprint

            preview_df = read_uploaded(uploaded_file)
            st.session_state.pathao_preview_source = source_mode

            # Show column detection and mapping UI for uploaded files
            mapped_df, confirmed = _render_column_mapping_ui(preview_df)

            if confirmed and mapped_df is not None:
                preview_df = mapped_df
                valid_file = True
                st.session_state.pathao_preview_df = preview_df
                st.success("✅ Column mapping confirmed. Ready to process.")
            else:
                st.session_state.pathao_preview_df = None
                st.info(
                    "👆 Please confirm or adjust the column mappings above before processing."
                )
                valid_file = False
        except Exception as exc:
            _clear_processing_source()
            log_error(exc, context="Pathao Upload")
            st.error("Failed to read uploaded file.")
    elif source_mode == SOURCE_UPLOAD:
        _clear_processing_source()
    elif (
        st.session_state.get("pathao_preview_df") is not None
        and st.session_state.get("pathao_preview_source") == source_mode
    ):
        preview_df = st.session_state.pathao_preview_df
        phone_cols_present = [c for c in REQUIRED_COLUMNS if c in preview_df.columns]
        valid_file = len(phone_cols_present) > 0 and not preview_df.empty

    if preview_df is not None:
        if "SIP" in preview_df.columns or "Item Outlet" in preview_df.columns:
            st.info(
                "🏭 **Outlet-Wise Routing Active**: SIP JSON or Item Outlet data detected. "
                "Multi-outlet orders will automatically split into designated consignments "
                "(Warehouse primary, branch suffixes, and delivery fee allocated to parcel 1)."
            )
        with st.expander("Preview source data", expanded=False):
            preview_search = render_dataframe_search(
                preview_df, "pathao_preview", height=400
            )
            st.dataframe(preview_search.head(50), use_container_width=True)

    run_clicked, clear_clicked = render_sticky_action_bar(
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
        _invalidate_processing_result()
        if preview_df is None or not valid_file:
            st.warning("Load a valid source before processing orders.")
        else:
            try:
                with st.status("Processing orders...", expanded=True) as status:
                    st.write(
                        "Applying cleanup, district resolution, and address normalization..."
                    )
                    result_df = process_orders_dataframe(preview_df.copy())
                    st.session_state.pathao_res_df = result_df
                    save_state()
                    status.update(
                        label="Processing complete", state="complete", expanded=False
                    )
                st.toast(f"✅ Processed {len(result_df)} grouped orders.")
            except Exception as exc:
                log_error(exc, context="Pathao Processor")
                st.error("Pathao processing failed. Check System Logs for details.")

    result_df = st.session_state.get("pathao_res_df")
    if result_df is not None:
        with st.expander("Preview output", expanded=True):
            result_search = render_dataframe_search(
                result_df, "pathao_result", height=400
            )
            st.dataframe(
                result_search.style.apply(_highlight_split_orders, axis=1),
                use_container_width=True,
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            pathao_excel_bytes = export_to_styled_excel(
                {"Pathao": result_df}, group_by_col="MerchantOrderId"
            )

            st.download_button(
                "Download repaired file",
                pathao_excel_bytes,
                "Pathao_Final.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )

        with c2:
            pathao_csv_bytes = result_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download Pathao Bulk (.csv)",
                pathao_csv_bytes,
                "Pathao_Bulk.csv",
                mime="text/csv",
                type="secondary",
                use_container_width=True,
            )

        with c3:
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
                    order_id = str(
                        row.get(
                            "Order ID",
                            row.get(
                                "Order Number", row.get("MerchantOrderId", "VERIFY")
                            ),
                        )
                    )
                    links.append(f"{domain}/verify?id={order_id}&token={token}")
                df_v["Verification Link"] = links
                st.session_state.pathao_vlink_df = df_v
                st.toast("✅ Verification links generated.")

            vlink_df = st.session_state.get("pathao_vlink_df")
            if vlink_df is not None:
                vlink_excel_bytes = export_to_styled_excel(
                    {"Verification": vlink_df}, group_by_col="MerchantOrderId"
                )

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
    st.caption(
        "Supported formats: `2x Item Name`, `Item Name x2`, `Item Name (2 pcs)`, or `Item Name | SKU123`."
    )

    raw_items = st.text_area(
        "Manual item input",
        key="pathao_manual_items",
        height=220,
        placeholder="2x Oxford Shirt - Navy | SKU123\nPolo Shirt x1\nJeans (2 pcs)",
    )

    if st.button(
        "Normalize and sort items",
        type="primary",
        use_container_width=True,
        key="pathao_manual_normalize",
    ):
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
        from src.components.ui.clipboard import render_copy_button

        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown("#### Generated Item Description")
        with c2:
            render_copy_button(manual_desc, label="Copy ItemDesc")
        st.code(manual_desc)
