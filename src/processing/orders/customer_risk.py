"""Customer Delivery Success Rate & Fraud/RTO Risk Engine.

Ports and expands customer rating intelligence from DEEN Sales Analysis (customerRatingTypes.ts).
Evaluates customer phone delivery statistics across store history and courier networks:
- EXCELLENT: ≥90% delivery success rate (VIP, fast-track dispatch)
- GOOD: 80% - 89% delivery success rate (Reliable buyer)
- MODERATE: 60% - 79% delivery success rate (Occasional return, confirm before dispatch)
- RISKY: <60% delivery success rate (High cancellation / RTO risk, advance fee recommended)
- NEW: First-time buyer profile
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd

from src.utils.text import normalize_phone_number


class CustomerRiskTier:
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    MODERATE = "MODERATE"
    RISKY = "RISKY"
    NEW = "NEW"


@dataclass
class CustomerRiskRating:
    phone: str
    normalized_phone: str
    tier: str  # EXCELLENT, GOOD, MODERATE, RISKY, NEW
    label: str  # e.g., "95% (Excellent)" or "New Customer"
    success_rate: int  # 0 to 100 percentage
    total_orders: int
    delivered_orders: int
    returned_orders: int
    risk_level: str  # LOW, MEDIUM, HIGH
    courier_notes: str
    badge_color: str  # HEX color token for UI display


def clean_phone_11_digits(raw_phone: Any) -> str:
    """Normalize phone to Bangladesh standard 11-digit string (e.g. 01712345678)."""
    p = normalize_phone_number(raw_phone)
    if not p:
        return ""
    digits = "".join(filter(str.isdigit, str(p)))
    if digits.startswith("880"):
        digits = "0" + digits[3:]
    elif digits.startswith("88"):
        digits = "0" + digits[2:]
    elif len(digits) == 10 and not digits.startswith("0"):
        digits = "0" + digits
    return digits if len(digits) == 11 else digits


def score_customer_delivery_risk(
    phone: str,
    delivered_count: int = 0,
    returned_count: int = 0,
    raw_pathao_rating: str | None = None,
) -> CustomerRiskRating:
    """Calculate the delivery success rate and risk classification for a customer."""
    norm_phone = clean_phone_11_digits(phone)
    total = delivered_count + returned_count

    if total == 0:
        return CustomerRiskRating(
            phone=phone,
            normalized_phone=norm_phone or phone,
            tier="NEW",
            label="New Customer",
            success_rate=100,
            total_orders=0,
            delivered_orders=0,
            returned_orders=0,
            risk_level="LOW",
            courier_notes="First-time buyer. Standard order verification recommended.",
            badge_color="#8b5cf6",  # Purple
        )

    rate = int(round((delivered_count / total) * 100)) if total > 0 else 100
    pathao_tag = str(raw_pathao_rating or "").lower().strip()

    if "excellent" in pathao_tag or rate >= 90:
        return CustomerRiskRating(
            phone=phone,
            normalized_phone=norm_phone,
            tier="EXCELLENT",
            label=f"{rate}% (Excellent)",
            success_rate=rate,
            total_orders=total,
            delivered_orders=delivered_count,
            returned_orders=returned_count,
            risk_level="LOW",
            courier_notes="Very high delivery success rate across courier network. Fast-track dispatch eligible.",
            badge_color="#10b981",  # Emerald Green
        )
    elif "good" in pathao_tag or (80 <= rate < 90):
        return CustomerRiskRating(
            phone=phone,
            normalized_phone=norm_phone,
            tier="GOOD",
            label=f"{rate}% (Good)",
            success_rate=rate,
            total_orders=total,
            delivered_orders=delivered_count,
            returned_orders=returned_count,
            risk_level="LOW",
            courier_notes="Consistent delivery history with minimal courier returns.",
            badge_color="#3b82f6",  # Blue
        )
    elif "moderate" in pathao_tag or (60 <= rate < 80):
        return CustomerRiskRating(
            phone=phone,
            normalized_phone=norm_phone,
            tier="MODERATE",
            label=f"{rate}% (Moderate)",
            success_rate=rate,
            total_orders=total,
            delivered_orders=delivered_count,
            returned_orders=returned_count,
            risk_level="MEDIUM",
            courier_notes="Occasional return history. Confirm recipient availability prior to dispatch.",
            badge_color="#f59e0b",  # Amber
        )
    else:  # rate < 60 or risky
        return CustomerRiskRating(
            phone=phone,
            normalized_phone=norm_phone,
            tier="RISKY",
            label=f"{rate}% (High Risk)",
            success_rate=rate,
            total_orders=total,
            delivered_orders=delivered_count,
            returned_orders=returned_count,
            risk_level="HIGH",
            courier_notes="High return/cancellation risk (>40% RTO). Advance courier fee collection advised.",
            badge_color="#ef4444",  # Red
        )


def build_phone_history_stats(orders_df: pd.DataFrame) -> dict[str, tuple[int, int]]:
    """Build a mapping of normalized phone -> (delivered_count, returned_count)."""
    stats_map: dict[str, tuple[int, int]] = {}
    if orders_df is None or orders_df.empty:
        return stats_map

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
            if c in orders_df.columns
        ),
        None,
    )
    status_col = next(
        (
            c
            for c in [
                "Order Status",
                "Status",
                "status",
                "Courier Status",
                "Pathao Status",
            ]
            if c in orders_df.columns
        ),
        None,
    )

    if not phone_col or not status_col:
        return stats_map

    for _, row in orders_df.iterrows():
        p = clean_phone_11_digits(row.get(phone_col))
        if not p or len(p) < 10:
            continue
        st_val = str(row.get(status_col, "")).lower()

        deliv, ret = stats_map.get(p, (0, 0))
        if any(kw in st_val for kw in ["return", "cancel", "failed", "rto", "refund"]):
            ret += 1
        elif any(kw in st_val for kw in ["delivered", "completed", "shipped", "paid"]):
            deliv += 1
        else:
            deliv += 1
        stats_map[p] = (deliv, ret)

    return stats_map
