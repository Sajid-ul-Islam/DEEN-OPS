"""7-Day Dispatch History Timeline & Operational Reporting Engine.

Ports rolling dispatch history aggregation from DEEN Sales Analysis (liveOpsProcessor.ts).
Constructs an authoritative 7-day operational timeline with order counts, exchange tags,
and revenue performance for quick one-click historical audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
import pandas as pd

from src.config.constants import bd_today
from src.processing.orders.date_utils import (
    get_previous_working_day,
    safe_coerce_datetime_naive,
)
from src.processing.orders.exchange_detector import detect_order_exchange


@dataclass
class DayTimelineSummary:
    date_iso: str  # YYYY-MM-DD
    date_label: str  # e.g. "Monday, Nov 9"
    day_name: str  # e.g. "Monday"
    day_short: str  # e.g. "Mon"
    is_today: bool = False
    is_prev_day: bool = False
    order_count: int = 0
    item_count: int = 0
    revenue: float = 0.0
    aov: float = 0.0
    exchange_count: int = 0
    orders: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Timeline7dReport:
    days: list[DayTimelineSummary] = field(default_factory=list)
    avg_7d_revenue: float = 0.0
    avg_7d_orders: float = 0.0
    avg_7d_items: float = 0.0
    avg_7d_aov: float = 0.0
    total_7d_revenue: float = 0.0
    total_7d_orders: int = 0


def build_7day_dispatch_timeline(
    full_orders_df: pd.DataFrame,
    reference_date: date | None = None,
) -> Timeline7dReport:
    """Aggregate the rolling 7-day dispatch history from orders data.

    Args:
        full_orders_df: DataFrame of orders across recent dates.
        reference_date: Reference calendar date (defaults to bd_today()).

    Returns:
        Timeline7dReport containing daily summaries and rolling 7-day averages.
    """
    ref_d = reference_date or bd_today()
    if hasattr(ref_d, "date") and callable(ref_d.date):
        ref_d = ref_d.date()

    prev_work_d = get_previous_working_day(ref_d)

    # Generate recent 7 days (walk backwards 6 days from ref_d)
    date_range = [ref_d - timedelta(days=i) for i in range(6, -1, -1)]

    df = (
        full_orders_df.copy()
        if full_orders_df is not None and not full_orders_df.empty
        else pd.DataFrame()
    )

    order_id_col = next(
        (c for c in ["Order ID", "order_id", "Order Number"] if c in df.columns), None
    )
    qty_col = next(
        (c for c in ["Quantity", "quantity", "Total Qty"] if c in df.columns), None
    )
    total_col = next(
        (
            c
            for c in ["Line Total", "Total Amount", "Total Price", "total"]
            if c in df.columns
        ),
        None,
    )
    cost_col = next(
        (c for c in ["Item Cost", "cost", "Item Price"] if c in df.columns), None
    )

    comp_col = next(
        (c for c in ["date_completed", "Date Completed"] if c in df.columns),
        None,
    )
    mod_col = next(
        (
            c
            for c in ["mod_dt_parsed", "Order Date Modified", "date_modified"]
            if c in df.columns
        ),
        None,
    )
    date_col = next(
        (c for c in ["dt_parsed", "Order Date", "date_created"] if c in df.columns),
        None,
    )
    status_col = next(
        (c for c in ["Order Status", "status", "Status"] if c in df.columns),
        None,
    )
    if status_col and not df.empty:
        from src.config.constants import SHIPPED_STATUSES

        shipped_vals = {s.lower() for s in SHIPPED_STATUSES}
        status_s = df[status_col].astype(str).str.lower().str.strip()
        df = df[status_s.isin(shipped_vals)].copy()

    if not df.empty:
        dt_comp = (
            safe_coerce_datetime_naive(df[comp_col])
            if comp_col
            else pd.Series(pd.NaT, index=df.index)
        )
        dt_mod = (
            safe_coerce_datetime_naive(df[mod_col])
            if mod_col
            else pd.Series(pd.NaT, index=df.index)
        )
        dt_create = (
            safe_coerce_datetime_naive(df[date_col])
            if date_col
            else pd.Series(pd.NaT, index=df.index)
        )
        # Authoritative precedence: date_completed -> date_modified -> date_created
        df["_effective_date"] = dt_comp.fillna(dt_mod).fillna(dt_create).dt.date
    else:
        df["_effective_date"] = pd.Series(dtype="object")

    daily_summaries: list[DayTimelineSummary] = []

    for d in date_range:
        d_iso = d.strftime("%Y-%m-%d")
        d_name = d.strftime("%A")
        d_short = d.strftime("%a")
        d_label = f"{d_name}, {d.strftime('%b %d')}"
        is_today = d == ref_d
        is_prev = d == prev_work_d

        day_subset = df[df["_effective_date"] == d] if not df.empty else pd.DataFrame()

        if day_subset.empty:
            daily_summaries.append(
                DayTimelineSummary(
                    date_iso=d_iso,
                    date_label=d_label,
                    day_name=d_name,
                    day_short=d_short,
                    is_today=is_today,
                    is_prev_day=is_prev,
                    order_count=0,
                    item_count=0,
                    revenue=0.0,
                    aov=0.0,
                    exchange_count=0,
                )
            )
            continue

        # Count unique orders
        unique_orders = (
            int(day_subset[order_id_col].nunique()) if order_id_col else len(day_subset)
        )

        # Count units sold
        items_cnt = (
            int(day_subset[qty_col].sum())
            if qty_col and pd.notna(day_subset[qty_col].sum())
            else len(day_subset)
        )

        # Sum revenue (excluding replacement orders if zero-cost or marked exchange)
        rev = 0.0
        if total_col:
            rev = float(
                pd.to_numeric(day_subset[total_col], errors="coerce").fillna(0).sum()
            )
        elif cost_col and qty_col:
            rev = float(
                (
                    pd.to_numeric(day_subset[cost_col], errors="coerce")
                    * pd.to_numeric(day_subset[qty_col], errors="coerce")
                )
                .fillna(0)
                .sum()
            )
        elif cost_col:
            rev = float(
                pd.to_numeric(day_subset[cost_col], errors="coerce").fillna(0).sum()
            )

        aov = (rev / unique_orders) if unique_orders > 0 else 0.0

        # Count exchanges
        ex_count = 0
        seen_ex_ids = set()
        for _, row in day_subset.iterrows():
            oid = str(row.get(order_id_col, "")).strip()
            if oid and oid not in seen_ex_ids:
                if detect_order_exchange(row).is_exchange:
                    seen_ex_ids.add(oid)
                    ex_count += 1

        daily_summaries.append(
            DayTimelineSummary(
                date_iso=d_iso,
                date_label=d_label,
                day_name=d_name,
                day_short=d_short,
                is_today=is_today,
                is_prev_day=is_prev,
                order_count=unique_orders,
                item_count=items_cnt,
                revenue=round(rev, 2),
                aov=round(aov, 2),
                exchange_count=ex_count,
            )
        )

    # Compute 7-day rolling statistics
    tot_rev = sum(s.revenue for s in daily_summaries)
    tot_ord = sum(s.order_count for s in daily_summaries)
    tot_items = sum(s.item_count for s in daily_summaries)
    active_days = max(1, len(daily_summaries))

    avg_rev = tot_rev / active_days
    avg_ord = tot_ord / active_days
    avg_items = tot_items / active_days
    avg_aov = (tot_rev / tot_ord) if tot_ord > 0 else 0.0

    return Timeline7dReport(
        days=daily_summaries,
        avg_7d_revenue=round(avg_rev, 2),
        avg_7d_orders=round(avg_ord, 1),
        avg_7d_items=round(avg_items, 1),
        avg_7d_aov=round(avg_aov, 2),
        total_7d_revenue=round(tot_rev, 2),
        total_7d_orders=tot_ord,
    )
