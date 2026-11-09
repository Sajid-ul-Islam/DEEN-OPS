"""Comprehensive Exchange & Replacement Parcel Detection Engine.

Ports and expands exchange detection from DEEN Sales Analysis (liveOpsProcessor.ts).
Distinguishes replacement dispatches (#18085 for #17839) and manual non-checkout customer
swaps from standard commercial e-commerce checkout sales.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
import pandas as pd


@dataclass
class ExchangeDetails:
    is_exchange: bool = False
    exchange_type: str = (
        "none"  # replacement, original_exchanged, general_exchange, none
    )
    referenced_order_id: str | None = None
    display_tag: str = ""


@dataclass
class ExchangeSummary:
    count: int = 0
    items_count: int = 0
    replacement_count: int = 0
    original_exchanged_count: int = 0
    orders: list[dict[str, Any]] = field(default_factory=list)
    exchange_order_ids: set[str] = field(default_factory=set)


EXCHANGE_PREFIX_PATTERN = re.compile(r"^(dd?|ex|exchange)[-_ ]+(\d+)", re.IGNORECASE)
EXCHANGE_NOTE_PATTERN = re.compile(
    r"exchange\s+(?:credit\s+)?(?:for\s+)?(?:order\s+)?#?(\d+)|\bdd?-(\d+)\b",
    re.IGNORECASE,
)


def detect_order_exchange(order_row: dict[str, Any] | pd.Series) -> ExchangeDetails:
    """Analyze an order row to determine if it is an exchange or replacement order."""
    if order_row is None:
        return ExchangeDetails()

    row = dict(order_row) if isinstance(order_row, (dict, pd.Series)) else {}

    # 1. Order ID or Consignment Prefix (D-17839, DD-17839, EX-17839)
    oid = str(
        row.get("Order ID", row.get("Order Number", row.get("order_id", "")))
    ).strip()
    cid = str(
        row.get(
            "Pathao Consignment ID",
            row.get("Consignment ID", row.get("consignment_id", "")),
        )
    ).strip()

    # Check prefix
    for val in (oid, cid):
        m = EXCHANGE_PREFIX_PATTERN.match(val)
        if m:
            ref_id = m.group(2)
            return ExchangeDetails(
                is_exchange=True,
                exchange_type="replacement",
                referenced_order_id=ref_id,
                display_tag=f"Exchange for #{ref_id}",
            )

    # 2. Check metadata fields
    sip_of = str(row.get("_sip_exchange_of", row.get("Exchange Of", ""))).strip()
    if sip_of and sip_of not in ("nan", "none", "null", "[]"):
        return ExchangeDetails(
            is_exchange=True,
            exchange_type="replacement",
            referenced_order_id=sip_of,
            display_tag=f"Exchange for #{sip_of}",
        )

    sip_repl = str(row.get("_sip_replacement_orders", "")).strip()
    if sip_repl and sip_repl not in ("nan", "none", "null", "[]"):
        clean_repl = (
            sip_repl.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
        )
        return ExchangeDetails(
            is_exchange=True,
            exchange_type="original_exchanged",
            referenced_order_id=clean_repl,
            display_tag=f"Exchanged (Replaced by #{clean_repl})",
        )

    # 3. Check Order Notes & Substatus
    notes = (
        " ".join(
            str(row.get(k, ""))
            for k in [
                "Order Notes",
                "Customer Note",
                "customer_note",
                "notes",
                "Fee Notes",
                "Substatus",
                "substatus",
                "Order Status",
            ]
            if k in row
        )
        .strip()
        .lower()
    )

    if notes:
        m_note = EXCHANGE_NOTE_PATTERN.search(notes)
        if m_note:
            ref_id = m_note.group(1) or m_note.group(2)
            return ExchangeDetails(
                is_exchange=True,
                exchange_type="replacement",
                referenced_order_id=ref_id,
                display_tag=f"Exchange for #{ref_id}",
            )

        if any(
            kw in notes
            for kw in ["exchange replacement", "size exchange", "product exchange"]
        ):
            return ExchangeDetails(
                is_exchange=True,
                exchange_type="general_exchange",
                referenced_order_id=None,
                display_tag="Exchange Replacement",
            )

    # 4. Check Non-Checkout / Manual Admin creation (excluding standard POS and Store API)
    created_via = (
        str(row.get("Created via", row.get("created_via", ""))).strip().lower()
    )
    if created_via in ("sip_exchange", "manual", "no-checkout", "non-checkout"):
        return ExchangeDetails(
            is_exchange=True,
            exchange_type="general_exchange",
            referenced_order_id=None,
            display_tag="Admin Exchange",
        )

    return ExchangeDetails(is_exchange=False)


def analyze_exchanges(
    orders_df: pd.DataFrame | list[dict[str, Any]],
) -> ExchangeSummary:
    """Analyze a DataFrame of orders and return consolidated exchange metrics."""
    if orders_df is None:
        return ExchangeSummary()
    if isinstance(orders_df, list):
        orders_df = pd.DataFrame(orders_df)
    if orders_df.empty:
        return ExchangeSummary()

    exchange_orders: list[dict[str, Any]] = []
    exchange_ids: set[str] = set()
    repl_cnt = 0
    orig_cnt = 0

    order_id_col = next(
        (c for c in ["Order ID", "order_id", "Order Number"] if c in orders_df.columns),
        None,
    )

    for _, row in orders_df.iterrows():
        details = detect_order_exchange(row)
        if details.is_exchange:
            oid = str(row.get(order_id_col, "")).strip() if order_id_col else ""
            if oid and oid not in exchange_ids:
                exchange_ids.add(oid)
                row_dict = row.to_dict()
                row_dict["exchange_tag"] = details.display_tag
                row_dict["exchange_type"] = details.exchange_type
                row_dict["exchange_ref_id"] = details.referenced_order_id
                exchange_orders.append(row_dict)

                if details.exchange_type == "replacement":
                    repl_cnt += 1
                elif details.exchange_type == "original_exchanged":
                    orig_cnt += 1

    qty_col = next(
        (c for c in ["Quantity", "quantity", "Total Qty"] if c in orders_df.columns),
        None,
    )
    total_items = (
        sum(int(float(o.get(qty_col, 1) or 1)) for o in exchange_orders)
        if qty_col
        else len(exchange_orders)
    )

    return ExchangeSummary(
        count=len(exchange_ids),
        items_count=total_items,
        replacement_count=repl_cnt,
        original_exchanged_count=orig_cnt,
        orders=exchange_orders,
        exchange_order_ids=exchange_ids,
    )
