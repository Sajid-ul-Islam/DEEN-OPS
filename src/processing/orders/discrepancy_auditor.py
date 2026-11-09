"""Automated Courier Discrepancy Auditing & Revenue Leakage Detector.

Ports and expands the discrepancy audit engine from DEEN Sales Analysis (discrepancyAuditor.ts).
Monitors discrepancies between WooCommerce order lifecycle and Pathao Hermes courier statuses:
1. PHANTOM_DELIVERY / RETURNED_BUT_SHIPPED: Store recorded completed/shipped, but courier returned consignment.
2. DELIVERED_BUT_PROCESSING: Order in processing/on-hold in WC, but courier already delivered & collected cash.
3. UNCOLLECTED_COD: COD order marked delivered by courier, but collected amount is 0 or missing.
4. COD_MISMATCH: Courier collected COD amount differs significantly from WooCommerce order total.
5. DELAYED_PICKUP: Order in processing for >48 hours with no courier consignment ID assigned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import pandas as pd

from src.config.constants import bd_now
from src.processing.orders.date_utils import safe_coerce_datetime_naive


class CourierDiscrepancyType:
    PHANTOM_DELIVERY = "PHANTOM_DELIVERY"
    DELIVERED_BUT_PROCESSING = "DELIVERED_BUT_PROCESSING"
    UNCOLLECTED_COD = "UNCOLLECTED_COD"
    COD_MISMATCH = "COD_MISMATCH"
    DELAYED_PICKUP = "DELAYED_PICKUP"


@dataclass
class DiscrepancyAlert:
    order_id: str
    mismatch_type: str  # PHANTOM_DELIVERY, DELIVERED_BUT_PROCESSING, UNCOLLECTED_COD, COD_MISMATCH, DELAYED_PICKUP
    severity: str  # CRITICAL, WARNING, INFO
    title: str
    description: str
    financial_impact: float
    customer_name: str
    phone: str
    order_amount: float
    wc_status: str
    courier_status: str
    consignment_id: str
    recommendation: str


@dataclass
class DiscrepancyAuditSummary:
    total_audited: int = 0
    discrepancy_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    total_at_risk_bdt: float = 0.0
    alerts: list[DiscrepancyAlert] = field(default_factory=list)
    discrepant_order_ids: set[str] = field(default_factory=set)

    @property
    def has_discrepancies(self) -> bool:
        return self.discrepancy_count > 0


def audit_order_discrepancies(
    orders_df: pd.DataFrame | list[dict[str, Any]],
    now_dt: datetime | None = None,
) -> DiscrepancyAuditSummary:
    """Audit orders for discrepancies between store status and courier status.

    Args:
        orders_df: DataFrame or list of dicts with Order ID, Status, Pathao Status, etc.
        now_dt: Reference datetime (defaults to current Bangladesh time).

    Returns:
        DiscrepancyAuditSummary with classified alerts and total financial impact.
    """
    if orders_df is None:
        return DiscrepancyAuditSummary()

    if isinstance(orders_df, list):
        df = pd.DataFrame(orders_df)
    else:
        df = orders_df.copy()

    if df.empty:
        return DiscrepancyAuditSummary()

    ref_now = now_dt or bd_now()
    if getattr(ref_now, "tzinfo", None) is not None:
        ref_now_naive = ref_now.replace(tzinfo=None)
    else:
        ref_now_naive = ref_now

    # Column name resolution
    order_id_col = next(
        (
            c
            for c in ["Order ID", "order_id", "ID", "id", "Order Number"]
            if c in df.columns
        ),
        None,
    )
    if not order_id_col:
        return DiscrepancyAuditSummary(total_audited=len(df))

    wc_status_col = next(
        (
            c
            for c in ["Order Status", "status", "Status", "order_status"]
            if c in df.columns
        ),
        None,
    )
    courier_status_col = next(
        (
            c
            for c in [
                "Courier Status",
                "Pathao Status",
                "Live Pathao Status",
                "delivery_status",
                "Delivery Status",
            ]
            if c in df.columns
        ),
        None,
    )
    consignment_col = next(
        (
            c
            for c in [
                "Pathao Consignment ID",
                "Consignment ID",
                "consignment_id",
                "tracking_number",
                "Tracking Number",
            ]
            if c in df.columns
        ),
        None,
    )
    collected_col = next(
        (
            c
            for c in [
                "Collected Amount",
                "Pathao Collected Amount",
                "courier_collected_amount",
                "collected_amount",
                "Cash Collected",
            ]
            if c in df.columns
        ),
        None,
    )
    amount_col = next(
        (
            c
            for c in [
                "Order Total Amount",
                "Total Price",
                "order_amount",
                "Total Amount",
                "Total",
                "Line Total",
                "Item Cost",
            ]
            if c in df.columns
        ),
        None,
    )
    payment_col = next(
        (
            c
            for c in [
                "Payment Method Title",
                "payment_method",
                "Payment Method",
                "Payment Method:",
            ]
            if c in df.columns
        ),
        None,
    )
    cust_col = next(
        (
            c
            for c in [
                "Full Name (Billing)",
                "Customer Name",
                "customer_name",
                "Billing Name",
            ]
            if c in df.columns
        ),
        None,
    )
    phone_col = next(
        (
            c
            for c in [
                "Phone (Billing)",
                "Customer Phone",
                "phone",
                "Phone Number",
                "Billing Phone",
            ]
            if c in df.columns
        ),
        None,
    )
    created_col = next(
        (
            c
            for c in ["dt_parsed", "Order Date", "date_created", "date"]
            if c in df.columns
        ),
        None,
    )

    alerts: list[DiscrepancyAlert] = []
    seen_orders: set[str] = set()

    for _, row in df.iterrows():
        oid = str(row.get(order_id_col, "")).strip()
        if not oid or oid in seen_orders or oid in ("nan", "none", "None"):
            continue
        seen_orders.add(oid)

        wc_st = str(row.get(wc_status_col, "") if wc_status_col else "").lower().strip()
        courier_st = (
            str(row.get(courier_status_col, "") if courier_status_col else "")
            .lower()
            .strip()
        )
        cid = str(row.get(consignment_col, "") if consignment_col else "").strip()
        if cid.lower() in ("nan", "none", "null", "-"):
            cid = ""

        try:
            amt = float(row.get(amount_col, 0.0) or 0.0)
        except (ValueError, TypeError):
            amt = 0.0

        try:
            coll_amt = (
                float(row.get(collected_col, 0.0) or 0.0) if collected_col else 0.0
            )
        except (ValueError, TypeError):
            coll_amt = 0.0

        pmt = str(row.get(payment_col, "") if payment_col else "").lower().strip()
        c_name = str(row.get(cust_col, "Customer") if cust_col else "Customer").strip()
        phone = str(row.get(phone_col, "") if phone_col else "").strip()

        # Parse created date via robust Bangladesh timezone conversion
        created_dt = None
        if created_col and pd.notna(row.get(created_col)):
            try:
                dt_coerced = safe_coerce_datetime_naive(
                    pd.Series([row.get(created_col)])
                )
                created_dt = (
                    dt_coerced.iloc[0]
                    if not dt_coerced.empty and pd.notna(dt_coerced.iloc[0])
                    else None
                )
            except Exception:
                created_dt = None

        is_wc_shipped = wc_st in {"completed", "shipped", "wc-completed", "wc-shipped"}
        is_wc_processing = wc_st in {
            "processing",
            "process",
            "wc-processing",
            "on-hold",
            "hold",
            "pending",
            "waiting",
        }

        is_courier_delivered = "delivered" in courier_st and "partial" not in courier_st
        is_courier_returned = any(
            kw in courier_st for kw in ["return", "failed", "rto", "cancelled"]
        )

        # 1. PHANTOM DELIVERY: Store completed/shipped, but courier returned consignment
        if is_wc_shipped and is_courier_returned:
            alerts.append(
                DiscrepancyAlert(
                    order_id=oid,
                    mismatch_type="PHANTOM_DELIVERY",
                    severity="CRITICAL",
                    title=f"Phantom Delivery Conflict: #{oid}",
                    description=f"WooCommerce records order as Completed/Shipped, but Pathao reports consignment ({cid}) was Returned to warehouse.",
                    financial_impact=amt,
                    customer_name=c_name,
                    phone=phone,
                    order_amount=amt,
                    wc_status=wc_st,
                    courier_status=courier_st,
                    consignment_id=cid,
                    recommendation="Audit physical stock return and update WooCommerce status to Cancelled / Refunded.",
                )
            )
            continue

        # 2. DELIVERED BUT PROCESSING: Order still in processing/on-hold in WC, but courier already delivered
        if is_wc_processing and is_courier_delivered:
            alerts.append(
                DiscrepancyAlert(
                    order_id=oid,
                    mismatch_type="DELIVERED_BUT_PROCESSING",
                    severity="CRITICAL",
                    title=f"Delivered in Processing: #{oid}",
                    description=f"Pathao delivered parcel ({cid}) and collected cash, but WooCommerce remains in '{wc_st}'.",
                    financial_impact=amt,
                    customer_name=c_name,
                    phone=phone,
                    order_amount=amt,
                    wc_status=wc_st,
                    courier_status=courier_st,
                    consignment_id=cid,
                    recommendation="Mark WooCommerce order Completed to recognize realized revenue and release customer loyalty credit.",
                )
            )
            continue

        # 3. UNCOLLECTED COD: Delivered COD order with 0 collected cash
        is_cod = "cod" in pmt or "cash on delivery" in pmt
        if (
            is_courier_delivered
            and is_cod
            and amt > 100
            and coll_amt == 0.0
            and collected_col
        ):
            alerts.append(
                DiscrepancyAlert(
                    order_id=oid,
                    mismatch_type="UNCOLLECTED_COD",
                    severity="CRITICAL",
                    title=f"Uncollected COD Shortfall: #{oid}",
                    description=f"Delivered COD parcel indicates ৳0 collected funds against an invoice of ৳{amt:,.0f}.",
                    financial_impact=amt,
                    customer_name=c_name,
                    phone=phone,
                    order_amount=amt,
                    wc_status=wc_st,
                    courier_status=courier_st,
                    consignment_id=cid,
                    recommendation="File a formal remittance dispute with Pathao merchant support immediately.",
                )
            )
            continue

        # 4. COD MISMATCH: Substantial mismatch between collected amount and order total
        if (
            is_courier_delivered
            and is_cod
            and coll_amt > 0
            and amt > 0
            and abs(coll_amt - amt) > 150
        ):
            alerts.append(
                DiscrepancyAlert(
                    order_id=oid,
                    mismatch_type="COD_MISMATCH",
                    severity="WARNING",
                    title=f"COD Amount Mismatch: #{oid}",
                    description=f"Courier collected ৳{coll_amt:,.0f}, which differs by ৳{abs(coll_amt - amt):,.0f} from invoice (৳{amt:,.0f}). Possible partial return or unauthorized discount.",
                    financial_impact=abs(coll_amt - amt),
                    customer_name=c_name,
                    phone=phone,
                    order_amount=amt,
                    wc_status=wc_st,
                    courier_status=courier_st,
                    consignment_id=cid,
                    recommendation="Review delivery note and run partial delivery knapsack solver to verify kept items.",
                )
            )
            continue

        # 5. DELAYED PICKUP: Processing for >48h with no consignment ID assigned
        if is_wc_processing and not cid and created_dt is not None:
            age_hours = (ref_now_naive - created_dt).total_seconds() / 3600.0
            if age_hours > 48.0:
                alerts.append(
                    DiscrepancyAlert(
                        order_id=oid,
                        mismatch_type="DELAYED_PICKUP",
                        severity="WARNING",
                        title=f"Delayed Fulfillment (>48h): #{oid}",
                        description=f"Order created {age_hours:.0f} hours ago remains in Processing without Pathao consignment ID or courier dispatch.",
                        financial_impact=amt,
                        customer_name=c_name,
                        phone=phone,
                        order_amount=amt,
                        wc_status=wc_st,
                        courier_status="untracked",
                        consignment_id="",
                        recommendation="Dispatch parcel immediately or verify stock availability across outlets.",
                    )
                )

    crit_cnt = sum(1 for a in alerts if a.severity == "CRITICAL")
    warn_cnt = sum(1 for a in alerts if a.severity == "WARNING")
    total_at_risk = sum(a.financial_impact for a in alerts)
    discrepant_ids = {a.order_id for a in alerts}

    return DiscrepancyAuditSummary(
        total_audited=len(seen_orders),
        discrepancy_count=len(alerts),
        critical_count=crit_cnt,
        warning_count=warn_cnt,
        total_at_risk_bdt=total_at_risk,
        alerts=alerts,
        discrepant_order_ids=discrepant_ids,
    )
