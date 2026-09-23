"""Auto-Dispatch: validate parcels, select pickup stores, and track creation results."""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import streamlit as st

from src.components.ui.widgets import section_card
from src.pages.pathao_orders.shared import SOURCE_WOOCOM, _get_pathao_client
from src.services.pathao.dispatch_ledger import DispatchLedger, ledger_key
from src.services.pathao.orders import PathaoOrderError, build_order_payload
from src.services.woocommerce.orders import extract_order_id, update_order_status


def _warehouse(row):
    value = row.get("WarehouseOutlet", "")
    return (
        str(value).strip()
        if pd.notna(value) and str(value).strip()
        else "Default pickup"
    )


def _prepare_dispatch(result_df, stores, account_scope, **settings):
    """Validate the entire batch before permitting any order creation."""
    prepared, errors, seen = [], [], set()
    for position, (_, row) in enumerate(result_df.iterrows(), start=1):
        outlet = _warehouse(row)
        try:
            store_id = stores.get(outlet)
            if store_id is None and outlet in ("Warehouse", "Ecom Mirpur"):
                store_id = stores.get("Ecom Mirpur") or stores.get("Warehouse")
            payload = build_order_payload(row, store_id, **settings)
            key = ledger_key(account_scope, payload["merchant_order_id"], outlet)
            if key in seen:
                raise ValueError(
                    "Duplicate merchant order ID for the same pickup outlet."
                )
            seen.add(key)
            prepared.append({"key": key, "outlet": outlet, "payload": payload})
        except (ValueError, TypeError) as exc:
            errors.append(
                {
                    "Row": position,
                    "Order": str(row.get("MerchantOrderId", "")),
                    "Error": str(exc),
                }
            )
    return prepared, errors


def _dispatch_batch(client, ledger, prepared, progress=None):
    """Reserve each parcel durably before POST; never resend an uncertain attempt."""
    report = []
    for index, entry in enumerate(prepared):
        payload, key = entry["payload"], entry["key"]
        record = {
            "Order": payload["merchant_order_id"],
            "Outlet": entry["outlet"],
            "Consignment": "",
            "Status": "",
            "Message": "",
        }
        if not ledger.reserve(key, record["Order"]):
            previous = ledger.get(key) or {}
            record.update(
                Status="Already created"
                if previous.get("status") == "created"
                else "Check Pathao",
                Consignment=previous.get("consignment_id", ""),
                Message=previous.get("message", "")
                or "Earlier attempt recorded; no new request sent.",
            )
        else:
            try:
                data = client.create_order(payload)
            except PathaoOrderError as exc:
                status = "uncertain" if exc.uncertain else "failed"
                ledger.finish(key, status, message=str(exc))
                record.update(
                    Status="Check Pathao" if exc.uncertain else "Failed",
                    Message=str(exc),
                )
            except Exception:
                # An unexpected failure could occur after the server accepted the POST.
                message = "Creation could not be confirmed. Check this merchant order ID in Pathao before retrying."
                ledger.finish(key, "uncertain", message=message)
                record.update(Status="Check Pathao", Message=message)
            else:
                consignment = data["consignment_id"]
                ledger.finish(key, "created", consignment_id=consignment)
                record.update(Status="Created", Consignment=consignment)
        report.append(record)
        if progress:
            progress((index + 1) / len(prepared))
    return report


def _sync_created_orders(report):
    """Update a grouped WooCommerce order only when all its parcels succeeded."""
    grouped = {}
    messages = []
    for parcel in report:
        # The processor joins merged WooCommerce references with commas.
        for reference in parcel["Order"].split(","):
            order_id = extract_order_id(reference)
            if order_id:
                grouped.setdefault(order_id, []).append(parcel)
    for order_id, parcels in grouped.items():
        if not all(p["Status"] in {"Created", "Already created"} for p in parcels):
            messages.append(
                {
                    "Order": order_id,
                    "Result": "Not updated: one or more parcels were not created.",
                }
            )
            continue
        # An all-already-created batch is a rerun, not another WC update request.
        if not any(p["Status"] == "Created" for p in parcels):
            continue
        consignments = ", ".join(dict.fromkeys(p["Consignment"] for p in parcels))
        try:
            ok, message = update_order_status(
                order_id,
                "confirmed",
                note=f"Dispatched via Pathao — Consignments: {consignments}",
            )
        except Exception:
            ok, message = (
                False,
                "Status update failed. Check WooCommerce before updating manually.",
            )
        messages.append(
            {"Order": order_id, "Result": "Updated to confirmed" if ok else message}
        )
    return messages


def _render_auto_dispatch_tab():
    section_card(
        "Auto-Dispatch to Pathao",
        "Review processed parcels, choose their pickup stores, and create consignments.",
    )
    for key, default in (
        ("pathao_dispatch_report", []),
        ("pathao_dispatch_wc_report", []),
        ("pathao_dispatch_stores", []),
        ("pathao_dispatch_account", ""),
    ):
        if key not in st.session_state:
            st.session_state[key] = default

    result_df = st.session_state.get("pathao_res_df")
    if result_df is None or result_df.empty:
        st.info("Go to Order Processing and process orders first.")
        return

    client = _get_pathao_client()
    if client is None:
        return
    account_scope = hashlib.sha256(
        json.dumps(
            [client.base_url, client.client_id, client.username], ensure_ascii=False
        ).encode()
    ).hexdigest()
    if st.session_state["pathao_dispatch_account"] != account_scope:
        st.session_state["pathao_dispatch_account"] = account_scope
        st.session_state["pathao_dispatch_stores"] = []
        st.session_state["pathao_dispatch_report"] = []
        st.session_state["pathao_dispatch_wc_report"] = []

    with st.expander("Preview all parcels for dispatch", expanded=True):
        st.dataframe(result_df, use_container_width=True)
        st.caption(
            "Every row above is a parcel. Review recipient details, COD, and split-parcel instructions before dispatch."
        )

    if st.button(
        "Load pickup stores", key="pathao_load_stores", use_container_width=True
    ):
        stores, error = client.get_stores()
        st.session_state["pathao_dispatch_stores"] = stores if not error else []
        if error:
            st.error(error)
        elif not stores:
            st.warning("No pickup stores are available on this Pathao account.")

    store_options = {}
    for store in st.session_state["pathao_dispatch_stores"]:
        if str(store.get("is_active", 1)).lower() in {"0", "false"}:
            continue
        try:
            store_id = int(store["store_id"])
            if store_id > 0:
                store_options[store_id] = (
                    f"{store.get('store_name', store.get('name', 'Store'))} (ID {store_id})"
                )
        except (KeyError, TypeError, ValueError):
            continue

    stores_by_outlet = {}
    for outlet in dict.fromkeys(_warehouse(row) for _, row in result_df.iterrows()):
        widget_key = (
            "pathao_store_"
            + hashlib.sha256(f"{account_scope}:{outlet}".encode()).hexdigest()[:16]
        )
        stores_by_outlet[outlet] = st.selectbox(
            f"Pickup store for {outlet}",
            [None, *store_options],
            format_func=lambda value: (
                "Select a pickup store" if value is None else store_options[value]
            ),
            key=widget_key,
        )
    if not store_options:
        st.info("Load pickup stores, then select the correct store for each outlet.")

    dc1, dc2 = st.columns(2)
    with dc1:
        item_type = st.selectbox(
            "Item Type",
            [2, 1],
            format_func=lambda value: {2: "Parcel", 1: "Document"}[value],
            key="pathao_dispatch_item_type",
        )
    with dc2:
        delivery_type = st.selectbox(
            "Delivery Type",
            [48, 12],
            format_func=lambda value: {48: "Normal", 12: "On demand"}[value],
            key="pathao_dispatch_delivery_type",
        )
    instructions = st.text_input(
        "Special Instructions",
        placeholder="Handle with care...",
        key="pathao_dispatch_instructions",
    )
    st.caption(
        "Pathao resolves delivery locations from the full address. Pickup selection does not change the recipient address."
    )
    source_is_wc = st.session_state.get("pathao_preview_source") == SOURCE_WOOCOM
    sync_wc = st.checkbox(
        "Update matching WooCommerce orders to confirmed after creation",
        value=source_is_wc,
        key=f"pathao_dispatch_sync_wc_{source_is_wc}",
        help="Enable only if these merchant order IDs belong to the connected WooCommerce store. An order is updated after all of its parcels succeed.",
    )

    prepared, errors = _prepare_dispatch(
        result_df,
        stores_by_outlet,
        account_scope,
        item_type=item_type,
        delivery_type=delivery_type,
        special_instructions=instructions,
    )
    if errors and all(stores_by_outlet.values()):
        st.error(
            "Correct the following source data and process again before dispatching."
        )
        st.dataframe(pd.DataFrame(errors), use_container_width=True)

    if st.button(
        "🚀 Push to Pathao API",
        type="primary",
        use_container_width=True,
        key="pathao_autodispatch_btn",
        disabled=bool(errors) or not prepared,
    ):
        st.session_state["pathao_dispatch_wc_report"] = []
        try:
            with (
                DispatchLedger() as ledger,
                st.status("Creating Pathao consignments...", expanded=True) as status,
            ):
                progress = st.progress(0)
                report = _dispatch_batch(client, ledger, prepared, progress.progress)
                st.session_state["pathao_dispatch_report"] = report
                if sync_wc:
                    st.session_state["pathao_dispatch_wc_report"] = (
                        _sync_created_orders(report)
                    )
                failed = sum(
                    r["Status"] not in {"Created", "Already created"} for r in report
                )
                created = sum(r["Status"] == "Created" for r in report)
                status.update(
                    label=f"{created} consignments created; {failed} need attention.",
                    state="error" if failed else "complete",
                    expanded=bool(failed),
                )
        except Exception:
            st.error(
                "Dispatch stopped because its results could not be saved. Check Pathao before retrying; recorded attempts will not be sent again."
            )

    report = st.session_state["pathao_dispatch_report"]
    if report:
        st.caption("Most recent dispatch attempt")
        report_df = pd.DataFrame(report)
        st.dataframe(report_df, use_container_width=True)
        st.download_button(
            "Download dispatch results",
            report_df.to_csv(index=False).encode("utf-8-sig"),
            "Pathao_Dispatch_Results.csv",
            mime="text/csv",
            key="pathao_dispatch_download",
        )
        if any(r["Status"] == "Check Pathao" for r in report):
            st.warning(
                "Some requests could have reached Pathao. Search their merchant order IDs in Order Tracking or the Pathao portal. These parcels are blocked from being sent again."
            )
        if any(r["Status"] == "Failed" for r in report):
            st.info(
                "Correct rejected orders and retry. Previously created parcels will be skipped."
            )
    if st.session_state["pathao_dispatch_wc_report"]:
        st.caption(
            "WooCommerce status results; Pathao creations are retained even if a status update fails."
        )
        st.dataframe(
            pd.DataFrame(st.session_state["pathao_dispatch_wc_report"]),
            use_container_width=True,
        )
