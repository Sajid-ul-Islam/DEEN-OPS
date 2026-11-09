"""Unit tests for the partial order subset-sum knapsack solver."""

from src.processing.orders.partial_knapsack import (
    OrderItemEntry,
    match_partial_items_advanced,
)


def test_knapsack_exact_subset_sum():
    # Order has 3 items: Item 0 = ৳1200, Item 1 = ৳800, Item 2 = ৳1500
    # Customer kept Item 0 and Item 1 = ৳2000
    items = [
        OrderItemEntry(idx=0, cost=1200.0, qty=1),
        OrderItemEntry(idx=1, cost=800.0, qty=1),
        OrderItemEntry(idx=2, cost=1500.0, qty=1),
    ]
    # No delivery fee adjustment, collected COD = 2000
    res = match_partial_items_advanced(
        items, collected_cod=2000.0, delivery_fees_to_try=[0.0]
    )

    assert res.confidence == "EXACT_MATCH"
    assert res.matched_value == 2000.0
    assert 0 in res.matched_indices
    assert 1 in res.matched_indices
    assert 2 not in res.matched_indices
    assert res.kept_total_value == 2000.0
    assert res.returned_total_value == 1500.0


def test_knapsack_with_dhaka_delivery_fee():
    # Customer kept Item 1 (৳800). Courier collected ৳850 (৳800 garment + ৳50 delivery fee)
    items = [
        {"idx": 0, "cost": 1200.0, "qty": 1},
        {"idx": 1, "cost": 800.0, "qty": 1},
        {"idx": 2, "cost": 1500.0, "qty": 1},
    ]
    res = match_partial_items_advanced(
        items, collected_cod=850.0, delivery_fees_to_try=[0.0, 50.0, 90.0]
    )

    assert res.confidence == "EXACT_MATCH"
    assert res.matched_value == 800.0
    assert 1 in res.matched_indices
    assert 0 not in res.matched_indices
    assert res.target_used == 800.0
    assert res.target_label == "COD - ৳50 delivery fee"


def test_knapsack_discrete_integer_units():
    # 2 units of Item 0 at ৳500 each, 1 unit of Item 1 at ৳1000.
    # Customer kept 1 unit of Item 0 (৳500)
    items = [
        {"idx": 0, "cost": 500.0, "qty": 2},
        {"idx": 1, "cost": 1000.0, "qty": 1},
    ]
    res = match_partial_items_advanced(
        items, collected_cod=500.0, delivery_fees_to_try=[0.0]
    )

    assert res.confidence == "EXACT_MATCH"
    assert res.matched_value == 500.0
    assign_0 = res.item_assignments[0]
    assert assign_0.kept_qty == 1
    assert assign_0.returned_qty == 1
    assert isinstance(assign_0.kept_qty, int)
    assert isinstance(assign_0.returned_qty, int)


def test_knapsack_closest_discrete_match():
    # Price mismatch due to manual coupon or tip (e.g. collected ৳995 for ৳1000 item)
    items = [
        {"idx": 0, "cost": 1000.0, "qty": 1},
        {"idx": 1, "cost": 2000.0, "qty": 1},
    ]
    res = match_partial_items_advanced(
        items, collected_cod=995.0, tolerance_bdt=10.0, delivery_fees_to_try=[0.0]
    )

    assert res.confidence == "TOLERANCE_MATCH"
    assert 0 in res.matched_indices
    assert abs(res.tolerance_difference) == 5.0
