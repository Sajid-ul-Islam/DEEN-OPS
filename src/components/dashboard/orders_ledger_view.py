"""Live Orders Ledger & Parcel Audit Component.

Interactive order inspection engine with:
1. View Mode Switcher: Order-Wise (Consolidated) vs Item-Wise (Granular Line Items)
2. Courier & Lifecycle Filter Pills: All, Delivered, In Transit, Returned, Untracked, Exchanges, Discrepancies
3. Customer Risk Classification Badges (VIP / Excellent, Good, Moderate, Risky, New)
4. Pathao Tracking Links
5. Multi-item Partial Return Knapsack Solver inspector
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import streamlit as st

from src.processing.orders.customer_risk import (
    score_customer_delivery_risk,
)
from src.processing.orders.discrepancy_auditor import audit_order_discrepancies
from src.processing.orders.exchange_detector import detect_order_exchange
from src.processing.orders.date_utils import safe_coerce_datetime_naive
from src.processing.orders.partial_knapsack import match_partial_items_advanced


def render_orders_ledger_view(
    orders_df: pd.DataFrame,
    title: str = "Live Orders Ledger & Parcel Audit",
    key_prefix: str = "orders_ledger",
) -> None:
    """Render the interactive orders ledger view.

    Args:
        orders_df: Full or filtered orders DataFrame.
        title: Title of the ledger section.
        key_prefix: Session state key prefix.
    """
    if orders_df is None or orders_df.empty:
        st.info("No orders data available to display in ledger.")
        return

    df = orders_df.copy()

    # Normalize column names
    col_map = {
        "order_id": "Order ID",
        "order_number": "Order ID",
        "customer": "Customer",
        "customer_name": "Customer",
        "billing_phone": "Phone",
        "Phone (Billing)": "Phone",
        "city": "City",
        "billing_city": "City",
        "status": "Status",
        "order_status": "Status",
        "Order Status": "Status",
        "item_name": "Product Name",
        "product_name": "Product Name",
        "sku": "SKU",
        "quantity": "Quantity",
        "qty": "Quantity",
        "item_cost": "Item Cost",
        "price": "Item Cost",
        "line_total": "Line Total",
        "total": "Line Total",
        "consignment_id": "Pathao Consignment ID",
        "courier_status": "Courier Status",
        "Pathao Status": "Courier Status",
    }
    for old_c, new_c in col_map.items():
        if old_c in df.columns and new_c not in df.columns:
            df[new_c] = df[old_c]

    # Normalize and format Date column for consistent BDT display
    date_src_col = next(
        (
            c
            for c in [
                "dt_parsed",
                "Order Date",
                "date_created",
                "Date",
                "mod_dt_parsed",
                "Order Date Modified",
                "date_completed",
            ]
            if c in df.columns
        ),
        None,
    )
    if date_src_col:
        parsed_dates = safe_coerce_datetime_naive(df[date_src_col])
        df["Order Date"] = parsed_dates.dt.strftime("%d %b %Y, %I:%M %p").fillna("—")
        df["_date_iso"] = parsed_dates.dt.strftime("%Y-%m-%d").fillna("")
    else:
        df["Order Date"] = "—"
        df["_date_iso"] = ""

    # Pre-audit discrepancies
    audit_res = audit_order_discrepancies(df)
    discrepant_ids = audit_res.discrepant_order_ids

    # ── Top Controls: View Mode & Filters ──────────────────────────────────────
    st.markdown(f"#### 📑 {title}")

    ctrl_col1, ctrl_col2 = st.columns([1, 2])
    with ctrl_col1:
        view_mode = st.radio(
            "Ledger Mode",
            ["Order-Wise (Consolidated)", "Item-Wise (Granular)"],
            horizontal=True,
            key=f"{key_prefix}_mode",
        )

    with ctrl_col2:
        filter_pills = [
            "All Orders",
            "Delivered",
            "In Transit",
            "Returned",
            "Untracked",
            "Exchanges Only",
            "Discrepancies Only",
        ]
        active_filter = st.radio(
            "Courier & Status Filter",
            filter_pills,
            horizontal=True,
            key=f"{key_prefix}_status_filter",
        )

    # Search Bar
    search_q = st.text_input(
        "🔍 Search orders by ID, Customer Name, Phone, SKU, or City",
        key=f"{key_prefix}_search",
    ).strip()

    # ── Apply Status Filters ──────────────────────────────────────────────────
    filtered_df = df

    c_status_col = "Courier Status" if "Courier Status" in filtered_df.columns else None
    c_id_col = (
        "Pathao Consignment ID"
        if "Pathao Consignment ID" in filtered_df.columns
        else None
    )
    oid_col = "Order ID" if "Order ID" in filtered_df.columns else None

    if active_filter == "Delivered" and c_status_col:
        filtered_df = filtered_df[
            filtered_df[c_status_col]
            .astype(str)
            .str.lower()
            .str.strip()
            .isin({"delivered", "successful", "successful_delivery"})
        ]
    elif active_filter == "In Transit" and c_status_col:
        filtered_df = filtered_df[
            filtered_df[c_status_col]
            .astype(str)
            .str.lower()
            .str.strip()
            .isin(
                {
                    "in_transit",
                    "in transit",
                    "picked_up",
                    "at_sorting_hub",
                    "on_the_way",
                }
            )
        ]
    elif active_filter == "Returned" and c_status_col:
        filtered_df = filtered_df[
            filtered_df[c_status_col]
            .astype(str)
            .str.lower()
            .str.strip()
            .isin({"returned", "rto", "failed", "return", "cancelled_at_courier"})
        ]
    elif active_filter == "Untracked":
        if c_id_col:
            filtered_df = filtered_df[
                filtered_df[c_id_col].isna()
                | (
                    filtered_df[c_id_col]
                    .astype(str)
                    .str.strip()
                    .isin({"", "nan", "None"})
                )
            ]
    elif active_filter == "Exchanges Only":
        # Check exchange status / prefixes
        ex_mask = filtered_df.apply(
            lambda r: detect_order_exchange(r).is_exchange, axis=1
        )
        filtered_df = filtered_df[ex_mask]
    elif active_filter == "Discrepancies Only":
        if oid_col:
            filtered_df = filtered_df[
                filtered_df[oid_col].astype(str).isin(discrepant_ids)
            ]

    # Apply Search Filter
    if search_q and not filtered_df.empty:
        search_cols = [
            c
            for c in ["Order ID", "Customer", "Phone", "SKU", "Product Name", "City"]
            if c in filtered_df.columns
        ]
        if search_cols:
            mask = pd.Series(False, index=filtered_df.index)
            for sc in search_cols:
                mask = mask | filtered_df[sc].astype(str).str.contains(
                    search_q, case=False, na=False
                )
            filtered_df = filtered_df[mask]

    # ── Interactive 7-Day Timeline Scoping ───────────────────────────
    timeline_selected = st.session_state.get("dispatch_timeline_7d_selected")
    if timeline_selected and "_date_iso" in filtered_df.columns:
        date_mask = filtered_df["_date_iso"] == timeline_selected
        if date_mask.any():
            c_info, c_clear = st.columns([0.8, 0.2])
            with c_info:
                st.info(
                    f"🗓️ **Scoped to Timeline Date:** `{timeline_selected}` "
                    f"({int(date_mask.sum())} matching order records)"
                )
            with c_clear:
                if st.button(
                    "Clear Date Scope",
                    key=f"{key_prefix}_clear_date",
                    use_container_width=True,
                ):
                    st.session_state.pop("dispatch_timeline_7d_selected", None)
                    st.rerun()
            filtered_df = filtered_df[date_mask]

    st.caption(
        f"Displaying **{len(filtered_df)}** records matching filter `{active_filter}`"
        + (f' and search `"{search_q}"`' if search_q else "")
    )

    if filtered_df.empty:
        st.info("No matching orders found for current filter criteria.")
        return

    # ── Render Modes ──────────────────────────────────────────────────────────
    if view_mode.startswith("Order-Wise"):
        _render_order_wise_table(filtered_df, discrepant_ids, key_prefix)
    else:
        _render_item_wise_table(filtered_df, key_prefix)


def _render_order_wise_table(
    df: pd.DataFrame,
    discrepant_ids: set[str],
    key_prefix: str,
) -> None:
    """Render consolidated order-level ledger with risk ratings and tracking links."""
    oid_col = "Order ID" if "Order ID" in df.columns else None
    if not oid_col:
        st.dataframe(df, use_container_width=True)
        return

    # Group by Order ID to aggregate items and sums
    agg_funcs: dict[str, Any] = {}
    if "Quantity" in df.columns:
        agg_funcs["Quantity"] = "sum"
    if "Line Total" in df.columns:
        agg_funcs["Line Total"] = "sum"
    elif "Item Cost" in df.columns:
        agg_funcs["Line Total"] = lambda x: (
            (
                pd.to_numeric(x, errors="coerce")
                * pd.to_numeric(df.loc[x.index, "Quantity"], errors="coerce")
            ).sum()
            if "Quantity" in df.columns
            else pd.to_numeric(x, errors="coerce").sum()
        )

    first_cols = [
        "Customer",
        "Phone",
        "City",
        "Status",
        "Pathao Consignment ID",
        "Courier Status",
        "Date",
        "Order Date",
    ]
    for fc in first_cols:
        if fc in df.columns:
            agg_funcs[fc] = "first"

    order_headers = (
        df.groupby(oid_col, as_index=False)
        .agg(agg_funcs)
        .sort_values(by=oid_col, ascending=False)
    )

    # Enrich with Risk Rating & Exchange detection
    risk_ratings: list[str] = []
    has_discrepancy_list: list[str] = []
    tracking_urls: list[str] = []

    for _, row in order_headers.iterrows():
        oid = str(row.get(oid_col, ""))
        phone = str(row.get("Phone", ""))
        consignment = str(row.get("Pathao Consignment ID", "")).strip()

        # Customer risk score
        risk = score_customer_delivery_risk(phone)
        risk_ratings.append(f"{risk.tier} ({risk.success_rate}%)")

        # Discrepancy indicator
        if oid in discrepant_ids:
            has_discrepancy_list.append("⚠️ Discrepancy")
        else:
            has_discrepancy_list.append("✅ Sync")

        # Pathao URL
        if consignment and consignment.lower() not in {"", "nan", "none"}:
            tracking_urls.append(
                f"https://merchant.pathao.com/tracking?consignment_id={consignment}"
            )
        else:
            tracking_urls.append("")

    order_headers["Customer Risk"] = risk_ratings
    order_headers["Audit"] = has_discrepancy_list
    order_headers["Track URL"] = tracking_urls

    # Reorder columns
    display_cols = [
        c
        for c in [
            oid_col,
            "Order Date",
            "Customer",
            "Phone",
            "City",
            "Status",
            "Courier Status",
            "Quantity",
            "Line Total",
            "Customer Risk",
            "Audit",
            "Track URL",
        ]
        if c in order_headers.columns
    ]

    st.dataframe(
        order_headers[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            oid_col: st.column_config.NumberColumn("Order ID", format="%d"),
            "Order Date": st.column_config.TextColumn(
                "Order Date", help="Order timestamp in Bangladesh Time (BDT, UTC+6)"
            ),
            "Quantity": st.column_config.NumberColumn("Items", format="%d"),
            "Line Total": st.column_config.NumberColumn("Total (৳)", format="%.2f"),
            "Track URL": st.column_config.LinkColumn(
                "Pathao Tracking", display_text="Track 📦"
            ),
            "Customer Risk": st.column_config.TextColumn(
                "Delivery Risk", help="Customer historical delivery completion rating"
            ),
            "Audit": st.column_config.TextColumn("Audit Status"),
        },
    )

    # Knapsack Partial Delivery Inspector Expander
    with st.expander("🧮 Partial Return Knapsack Calculator (Subset-Sum)"):
        st.caption(
            "Solve multi-item partial returns: determine which specific garments were kept vs returned "
            "based on the courier's collected COD amount minus delivery fee."
        )
        col_k1, col_k2 = st.columns([1, 2])
        with col_k1:
            inspect_oid = st.text_input(
                "Enter Order ID to inspect", key=f"{key_prefix}_k_oid"
            )
            collected_input = st.number_input(
                "Collected COD Amount (৳)",
                min_value=0.0,
                step=50.0,
                key=f"{key_prefix}_k_cod",
            )
        with col_k2:
            if inspect_oid:
                order_items = df[df[oid_col].astype(str) == str(inspect_oid).strip()]
                if not order_items.empty:
                    st.write(f"Line items for #{inspect_oid}:")
                    st.dataframe(
                        order_items[
                            [
                                c
                                for c in [
                                    "Product Name",
                                    "SKU",
                                    "Quantity",
                                    "Item Cost",
                                    "Line Total",
                                ]
                                if c in order_items.columns
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    if collected_input > 0:
                        items_payload = []
                        for idx, (_, it) in enumerate(order_items.iterrows()):
                            items_payload.append(
                                {
                                    "idx": idx,
                                    "cost": float(
                                        it.get("Item Cost", it.get("Line Total", 0.0))
                                    ),
                                    "qty": int(it.get("Quantity", 1)),
                                }
                            )
                        match_res = match_partial_items_advanced(
                            items_payload,
                            collected_cod=collected_input,
                            delivery_fees_to_try=[0.0, 50.0, 90.0, 60.0, 100.0, 130.0],
                        )
                        st.success(
                            f"**Match Result ({match_res.confidence}):** "
                            f"Kept Value: ৳ {match_res.kept_total_value:,.0f} | "
                            f"Returned Value: ৳ {match_res.returned_total_value:,.0f} | "
                            f"Target Used: ৳ {match_res.target_used:,.0f} ({match_res.target_label})"
                        )
                else:
                    st.warning(f"Order #{inspect_oid} not found in current dataset.")


def _render_item_wise_table(df: pd.DataFrame, key_prefix: str) -> None:
    """Render granular item-wise ledger with line items, SKU, collection, and prices."""
    cols_priority = [
        "Order ID",
        "Order Date",
        "Product Name",
        "Product Line",
        "SKU",
        "Category",
        "Sub-Category",
        "Quantity",
        "Item Cost",
        "Line Total",
        "Customer",
        "Phone",
        "City",
        "Status",
        "Courier Status",
        "Location",
    ]
    avail_cols = [c for c in cols_priority if c in df.columns]

    st.dataframe(
        df[avail_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Order ID": st.column_config.NumberColumn("Order ID", format="%d"),
            "Quantity": st.column_config.NumberColumn("Qty", format="%d"),
            "Item Cost": st.column_config.NumberColumn("Price (৳)", format="%.2f"),
            "Line Total": st.column_config.NumberColumn("Total (৳)", format="%.2f"),
        },
    )
