"""Courier Logistics Telemetry & Discrepancy Alert Component.

Renders real-time courier hand-off metrics and discrepancy audit warnings:
- Handed-over rate (%)
- In-transit, Delivered, and Returned parcel counters
- Cash on Delivery (COD) collection status
- Automated discrepancy detector warnings (Phantom deliveries, Delivered-in-Processing, COD mismatch)
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import streamlit as st

from src.processing.orders.discrepancy_auditor import (
    DiscrepancyAlert,
    DiscrepancyAuditSummary,
    audit_order_discrepancies,
)


def render_courier_telemetry_card(
    orders_df: pd.DataFrame | list[dict[str, Any]],
    title: str = "Courier Logistics Telemetry",
    expanded_discrepancies: bool = False,
) -> DiscrepancyAuditSummary:
    """Render courier telemetry KPI cards and automated discrepancy alerts.

    Args:
        orders_df: Raw or prepared orders DataFrame/records.
        title: Header text for the telemetry block.
        expanded_discrepancies: Whether the discrepancy expander is open by default.

    Returns:
        DiscrepancyAuditSummary containing discrepancies found.
    """
    if orders_df is None or (isinstance(orders_df, pd.DataFrame) and orders_df.empty):
        return DiscrepancyAuditSummary()

    # 1. Audit discrepancies
    audit_summary = audit_order_discrepancies(orders_df)

    # 2. Extract telemetry counts
    if isinstance(orders_df, pd.DataFrame):
        df = orders_df
        status_col = (
            "Courier Status"
            if "Courier Status" in df.columns
            else (
                "Pathao Status"
                if "Pathao Status" in df.columns
                else ("courier_status" if "courier_status" in df.columns else None)
            )
        )
        consignment_col = (
            "Pathao Consignment ID"
            if "Pathao Consignment ID" in df.columns
            else (
                "Consignment ID"
                if "Consignment ID" in df.columns
                else ("consignment_id" if "consignment_id" in df.columns else None)
            )
        )
        order_col = (
            "Order ID"
            if "Order ID" in df.columns
            else ("order_id" if "order_id" in df.columns else None)
        )
        cod_col = (
            "Pathao Collected Amount"
            if "Pathao Collected Amount" in df.columns
            else (
                "Collected Amount"
                if "Collected Amount" in df.columns
                else (
                    "collected_amount"
                    if "collected_amount" in df.columns
                    else (
                        "COD Amount"
                        if "COD Amount" in df.columns
                        else "Item Cost"
                        if "Item Cost" in df.columns
                        else None
                    )
                )
            )
        )

        # Unique orders if possible
        if order_col:
            unique_df = df.drop_duplicates(subset=[order_col])
        else:
            unique_df = df

        total_orders = len(unique_df)
        tracked_mask = (
            unique_df[consignment_col].notna()
            & (unique_df[consignment_col].astype(str).str.strip() != "")
            if consignment_col
            else pd.Series(False, index=unique_df.index)
        )
        tracked_count = int(tracked_mask.sum())

        statuses = (
            unique_df[status_col].astype(str).str.lower().str.strip()
            if status_col
            else pd.Series("", index=unique_df.index)
        )
        delivered_count = int(
            statuses.isin({"delivered", "successful", "successful_delivery"}).sum()
        )
        in_transit_count = int(
            statuses.isin(
                {
                    "in_transit",
                    "in transit",
                    "picked_up",
                    "at_sorting_hub",
                    "hub",
                    "on_the_way",
                }
            ).sum()
        )
        returned_count = int(
            statuses.isin(
                {
                    "returned",
                    "rto",
                    "failed",
                    "return",
                    "cancelled_at_courier",
                }
            ).sum()
        )

        cod_collected_bdt = 0.0
        if cod_col:
            delivered_mask = statuses.isin({"delivered", "successful"})
            cod_collected_bdt = float(
                pd.to_numeric(
                    unique_df.loc[delivered_mask, cod_col], errors="coerce"
                ).sum()
            )
    else:
        # dict records
        total_orders = len(orders_df)
        tracked_count = sum(
            1
            for o in orders_df
            if o.get("consignment_id") or o.get("Pathao Consignment ID")
        )
        delivered_count = sum(
            1
            for o in orders_df
            if str(o.get("courier_status", o.get("Pathao Status", ""))).lower().strip()
            in {"delivered", "successful"}
        )
        in_transit_count = sum(
            1
            for o in orders_df
            if str(o.get("courier_status", o.get("Pathao Status", ""))).lower().strip()
            in {"in_transit", "in transit", "picked_up", "at_sorting_hub", "on_the_way"}
        )
        returned_count = sum(
            1
            for o in orders_df
            if str(o.get("courier_status", o.get("Pathao Status", ""))).lower().strip()
            in {"returned", "rto", "failed", "return"}
        )
        cod_collected_bdt = sum(
            float(
                o.get("collected_amount", o.get("Pathao Collected Amount", 0.0)) or 0.0
            )
            for o in orders_df
            if str(o.get("courier_status", o.get("Pathao Status", ""))).lower().strip()
            in {"delivered", "successful"}
        )

    handover_rate = (
        round((tracked_count / total_orders) * 100, 1) if total_orders > 0 else 0.0
    )

    # 3. Render Telemetry Banner & Metrics
    st.markdown(f"#### 🚚 {title}")

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric(
            "Handed Over",
            f"{handover_rate}%",
            delta=f"{tracked_count}/{total_orders} orders",
            help="Orders assigned a courier consignment ID and handed over for delivery",
        )
    with c2:
        st.metric(
            "In Transit",
            f"{in_transit_count}",
            help="Parcels currently on route or in courier sorting hubs",
        )
    with c3:
        st.metric(
            "Delivered",
            f"{delivered_count}",
            delta=f"৳ {cod_collected_bdt:,.0f} COD",
            help="Parcels successfully handed to customers and confirmed by courier",
        )
    with c4:
        st.metric(
            "Returned / RTO",
            f"{returned_count}",
            delta="- Loss" if returned_count > 0 else "0",
            delta_color="inverse" if returned_count > 0 else "off",
            help="Parcels rejected or returned to merchant warehouse",
        )
    with c5:
        if audit_summary.discrepancy_count > 0:
            st.metric(
                "Discrepancies",
                f"{audit_summary.discrepancy_count}",
                delta=f"৳ {audit_summary.total_at_risk_bdt:,.0f} at risk",
                delta_color="inverse",
                help="Lifecycle mismatches between store records and courier delivery status",
            )
        else:
            st.metric(
                "Discrepancies",
                "0 Clean",
                delta="100% In Sync",
                help="Store records match courier tracking",
            )

    # 4. Render Discrepancy Alerts Expander
    if audit_summary.has_discrepancies:
        badge_type = (
            "🚨 CRITICAL ALERTS"
            if audit_summary.critical_count > 0
            else "⚠️ AUDIT NOTICES"
        )
        with st.expander(
            f"{badge_type}: {audit_summary.discrepancy_count} Courier & Revenue Mismatch(es) (৳ {audit_summary.total_at_risk_bdt:,.0f} at risk)",
            expanded=expanded_discrepancies,
        ):
            st.caption(
                "The courier discrepancy auditor cross-checks WooCommerce order states against "
                "Pathao Hermes tracking to identify phantom revenues, missed COD collections, and delayed pickups."
            )

            for alert in audit_summary.alerts:
                _render_discrepancy_alert_item(alert)

    return audit_summary


def _render_discrepancy_alert_item(alert: DiscrepancyAlert) -> None:
    """Render a single discrepancy alert card with styling and recommendation."""
    border_color = "#ef4444" if alert.severity == "CRITICAL" else "#f59e0b"
    bg_color = (
        "rgba(239, 68, 68, 0.08)"
        if alert.severity == "CRITICAL"
        else "rgba(245, 158, 11, 0.08)"
    )

    cols = st.columns([0.7, 0.3])
    with cols[0]:
        st.markdown(
            f"""
            <div style="border-left: 4px solid {border_color}; background: {bg_color}; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <strong style="color: {border_color}; font-size: 14px;">[{alert.severity}] #{alert.order_id} — {alert.title}</strong>
                    <span style="font-weight: 700; color: #1e293b;">৳ {alert.financial_impact:,.0f}</span>
                </div>
                <div style="font-size: 13px; color: #475569; margin-top: 4px;">
                    {alert.description}
                </div>
                <div style="font-size: 12px; color: #0f766e; margin-top: 6px; font-weight: 600;">
                    💡 Action: {alert.recommendation}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.caption(f"Customer: **{alert.customer_name or 'N/A'}**")
        st.caption(f"WC: `{alert.wc_status}` | Courier: `{alert.courier_status}`")
        if alert.consignment_id:
            tracking_url = f"https://merchant.pathao.com/tracking?consignment_id={alert.consignment_id}"
            st.markdown(
                f'<a href="{tracking_url}" target="_blank" style="text-decoration: none; font-size: 12px; color: #2563eb;">🔗 Pathao #{alert.consignment_id}</a>',
                unsafe_allow_html=True,
            )
