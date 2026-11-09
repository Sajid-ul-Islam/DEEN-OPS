"""Partial Order Subset-Sum & Knapsack Resolution Engine.

Ports the battle-tested knapsack algorithm from DEEN Sales Analysis (subsetSum.ts).
Solves multi-item partial returns by matching collected COD amounts against line items:
1. Collected COD often includes a delivery fee (৳50 inside Dhaka, ৳90 outside Dhaka).
   Subtracting the delivery fee yields the net price of items the customer kept.
2. The leftover price is the price of returned items.
3. Quantities are strictly whole integers (never floats).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderItemEntry:
    idx: int
    cost: float
    qty: int
    weight_grams: float = 700.0


@dataclass
class UnitItemAssignment:
    idx: int
    total_qty: int
    kept_qty: int  # Strictly integer
    returned_qty: int  # Strictly integer
    item_cost: float
    kept_value: float
    returned_value: float


@dataclass
class SubsetMatchResult:
    matched_indices: set[int] = field(default_factory=set)
    matched_value: float = 0.0
    target_used: float = 0.0
    confidence: str = (
        "EXACT_MATCH"  # EXACT_MATCH, TOLERANCE_MATCH, CLOSEST_DISCRETE_MATCH
    )
    tolerance_difference: float = 0.0
    item_assignments: dict[int, UnitItemAssignment] = field(default_factory=dict)
    kept_total_value: float = 0.0
    returned_total_value: float = 0.0
    target_label: str = ""


# Alias for compatibility with external callers
PartialKnapsackMatch = SubsetMatchResult


@dataclass
class _GarmentUnit:
    unit_id: int
    original_idx: int
    cost: float
    weight: float


def match_partial_items_advanced(
    items: list[OrderItemEntry | dict[str, Any]],
    collected_cod: float,
    order_total_amount: float = 0.0,
    custom_inside_fee: float = 50.0,
    custom_outside_fee: float = 90.0,
    custom_tolerance: float = 2.0,
    delivery_fees_to_try: list[float] | None = None,
    tolerance_bdt: float | None = None,
) -> SubsetMatchResult:
    """Solve which line items were kept vs returned in a partial delivery parcel.

    Args:
        items: List of OrderItemEntry or dicts with 'idx', 'cost', 'qty'.
        collected_cod: Cash on delivery amount collected by courier.
        order_total_amount: Full order total from WooCommerce invoice.
        custom_inside_fee: Delivery charge inside Dhaka (default: 50 BDT).
        custom_outside_fee: Delivery charge outside Dhaka (default: 90 BDT).
        custom_tolerance: Price match tolerance (default: 2.0 BDT).

    Returns:
        SubsetMatchResult containing integer assignments for kept vs returned quantities.
    """
    normalized_items: list[OrderItemEntry] = []
    for it in items:
        if isinstance(it, OrderItemEntry):
            normalized_items.append(it)
        elif isinstance(it, dict):
            normalized_items.append(
                OrderItemEntry(
                    idx=int(it.get("idx", 0)),
                    cost=float(it.get("cost", 0.0)),
                    qty=int(round(float(it.get("qty", 1)))),
                    weight_grams=float(it.get("weight_grams", 700.0)),
                )
            )

    # Flatten line items with quantities into discrete individual garments
    units: list[_GarmentUnit] = []
    counter = 0
    for it in normalized_items:
        clean_qty = max(0, int(round(it.qty)))
        for _ in range(clean_qty):
            units.append(
                _GarmentUnit(
                    unit_id=counter,
                    original_idx=it.idx,
                    cost=it.cost,
                    weight=it.weight_grams,
                )
            )
            counter += 1

    total_product_cost = sum(u.cost for u in units)
    calculated_delivery_fee = max(0.0, order_total_amount - total_product_cost)

    # Candidate targets for kept merchandise cost
    candidate_targets: list[tuple[float, str]] = []

    def _add_candidate(t: float, lbl: str):
        if 10.0 <= t <= (total_product_cost + 15.0):
            if not any(abs(existing[0] - t) < 0.5 for existing in candidate_targets):
                candidate_targets.append((round(t, 2), lbl))

    inside_fee = custom_inside_fee
    outside_fee = custom_outside_fee
    tol = tolerance_bdt if tolerance_bdt is not None else custom_tolerance

    if delivery_fees_to_try is not None:
        for fee in delivery_fees_to_try:
            lbl = f"COD - ৳{fee:.0f} delivery fee" if fee > 0 else "Direct COD Match"
            _add_candidate(collected_cod - fee, lbl)

    # 1. Delivery fee subtracted from collected COD (Inside, Outside, Sub-Dhaka, Standard)
    _add_candidate(
        collected_cod - outside_fee, f"Outside Dhaka ৳{outside_fee:.0f} Fee Subtracted"
    )
    _add_candidate(
        collected_cod - inside_fee, f"Inside Dhaka ৳{inside_fee:.0f} Fee Subtracted"
    )
    if inside_fee != 50.0:
        _add_candidate(collected_cod - 50.0, "Inside Dhaka ৳50 Fee Subtracted")
    if outside_fee != 90.0:
        _add_candidate(collected_cod - 90.0, "Outside Dhaka ৳90 Fee Subtracted")
    _add_candidate(collected_cod - 60.0, "Sub-Dhaka ৳60 Fee Subtracted")
    _add_candidate(collected_cod - 100.0, "Standard ৳100 Fee Subtracted")
    _add_candidate(collected_cod - 120.0, "Express ৳120 Fee Subtracted")
    if (
        calculated_delivery_fee > 0
        and abs(calculated_delivery_fee - inside_fee) > 1
        and abs(calculated_delivery_fee - outside_fee) > 1
    ):
        _add_candidate(
            collected_cod - calculated_delivery_fee,
            f"Calculated ৳{calculated_delivery_fee:.0f} Fee Subtracted",
        )

    # 2. Direct COD without delivery fee (prepaid delivery fee or zero delivery fee)
    _add_candidate(collected_cod, "Direct Merchandise Cost without Delivery Fee")

    # 3. Courier 1% COD Commission adjustments
    _add_candidate(
        (collected_cod - outside_fee) / 0.99,
        f"1% Courier Commission Adjusted (৳{outside_fee:.0f} Fee)",
    )
    _add_candidate(
        (collected_cod - inside_fee) / 0.99,
        f"1% Courier Commission Adjusted (৳{inside_fee:.0f} Fee)",
    )
    _add_candidate(collected_cod / 0.99, "1% Courier Commission Adjusted (Direct)")

    # 4. Reverse target: If collected COD corresponds to returned items' cost
    _add_candidate(
        total_product_cost - (collected_cod - outside_fee),
        f"Reverse Returned Calculation (৳{outside_fee:.0f} Fee)",
    )
    _add_candidate(
        total_product_cost - (collected_cod - inside_fee),
        f"Reverse Returned Calculation (৳{inside_fee:.0f} Fee)",
    )
    _add_candidate(
        total_product_cost - collected_cod, "Reverse Returned Calculation (Direct)"
    )

    best_match_indices: list[int] = []
    best_target_val = 0.0
    best_matched_val = 0.0
    best_diff = float("inf")
    best_label = ""
    best_confidence = "CLOSEST_DISCRETE_MATCH"

    # Evaluate subsets for each candidate target
    n_units = len(units)
    # Search all 2^N subsets (parcels in retail e-com have typically 2-8 garments)
    # For N <= 14, exhaustive power-set is virtually instantaneous (<0.1ms)
    subsets_power: list[list[int]] = [[]]
    for i in range(n_units):
        subsets_power += [curr + [i] for curr in subsets_power]

    # Precalculate sum for each subset
    subset_sums: list[tuple[float, list[int]]] = []
    for sub in subsets_power:
        if not sub:
            continue
        s_val = sum(units[i].cost for i in sub)
        subset_sums.append((s_val, sub))

    for target_val, target_lbl in candidate_targets:
        for s_val, sub in subset_sums:
            diff = abs(s_val - target_val)
            if diff < best_diff:
                best_diff = diff
                best_target_val = target_val
                best_matched_val = s_val
                best_match_indices = sub
                best_label = target_lbl
                if diff < 0.1:
                    best_confidence = "EXACT_MATCH"
                elif diff <= tol:
                    best_confidence = "TOLERANCE_MATCH"
                else:
                    best_confidence = "CLOSEST_DISCRETE_MATCH"
                if diff == 0.0:
                    break
        if best_diff == 0.0:
            break

    # Build per-line-item integer assignment
    kept_unit_set = set(best_match_indices)
    assignments: dict[int, UnitItemAssignment] = {}

    for it in normalized_items:
        it_units = [u for u in units if u.original_idx == it.idx]
        total_q = len(it_units)
        kept_q = sum(1 for u in it_units if u.unit_id in kept_unit_set)
        returned_q = total_q - kept_q

        assignments[it.idx] = UnitItemAssignment(
            idx=it.idx,
            total_qty=total_q,
            kept_qty=kept_q,
            returned_qty=returned_q,
            item_cost=it.cost,
            kept_value=round(kept_q * it.cost, 2),
            returned_value=round(returned_q * it.cost, 2),
        )

    matched_original_indices = {units[i].original_idx for i in best_match_indices}
    kept_total = sum(a.kept_value for a in assignments.values())
    returned_total = sum(a.returned_value for a in assignments.values())

    return SubsetMatchResult(
        matched_indices=matched_original_indices,
        matched_value=best_matched_val,
        target_used=best_target_val,
        confidence=best_confidence,
        tolerance_difference=round(best_diff, 2),
        item_assignments=assignments,
        kept_total_value=kept_total,
        returned_total_value=returned_total,
        target_label=best_label,
    )
