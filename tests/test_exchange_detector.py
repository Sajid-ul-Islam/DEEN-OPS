"""Unit tests for exchange and replacement order detection."""

from src.processing.orders.exchange_detector import (
    analyze_exchanges,
    detect_order_exchange,
)


def test_detect_exchange_prefix():
    # Order ID starting with D-17839 or DD-17839
    det1 = detect_order_exchange({"Order ID": "D-17839"})
    assert det1.is_exchange is True
    assert det1.exchange_type == "replacement"
    assert det1.referenced_order_id == "17839"

    det2 = detect_order_exchange({"Order ID": "DD-18085"})
    assert det2.is_exchange is True
    assert det2.referenced_order_id == "18085"


def test_detect_exchange_sip_meta():
    det = detect_order_exchange({"_sip_exchange_of": "17500"})
    assert det.is_exchange is True
    assert det.referenced_order_id == "17500"


def test_detect_exchange_note():
    det = detect_order_exchange({"Customer Note": "Size exchange for order #17200"})
    assert det.is_exchange is True
    assert det.referenced_order_id == "17200"


def test_analyze_exchanges_summary():
    orders = [
        {"Order ID": "1001", "Quantity": 1},
        {"Order ID": "D-1002", "Quantity": 2},
        {"Order ID": "1003", "_sip_replacement_orders": "1001", "Quantity": 1},
    ]
    summary = analyze_exchanges(orders)
    assert summary.count == 2
    assert summary.items_count == 3
    assert "D-1002" in summary.exchange_order_ids
    assert "1003" in summary.exchange_order_ids


def test_detect_exchange_sche_and_sip_keys():
    import pandas as pd
    from src.processing.orders.status_filters import _detect_exchange_mask

    # Order with sche meta key
    det_sche = detect_order_exchange({"sche": "exchange_credit_123"})
    assert det_sche.is_exchange is True

    # Order with _sip_exchange_code
    det_sip = detect_order_exchange({"_sip_exchange_code": "RET-9246AA"})
    assert det_sip.is_exchange is True

    # Order with _sip_exchange_order
    det_ord = detect_order_exchange({"_sip_exchange_order": "1"})
    assert det_ord.is_exchange is True

    # Order with created_via = sip_exchange
    det_via = detect_order_exchange({"Created via": "sip_exchange"})
    assert det_via.is_exchange is True

    # DataFrame mask detection
    df = pd.DataFrame(
        [
            {"Order ID": "101", "Order Status": "completed"},  # Regular checkout
            {"Order ID": "102", "Created via": "sip_exchange"},  # Exchange
            {"Order ID": "103", "sche": "1"},  # Exchange by sche key
            {"Order ID": "104", "_sip_exchange_code": "RET-123"},  # Exchange
            {"Order ID": "105", "Fee Notes": "Exchange credit: -TK 500"},  # Exchange
        ]
    )
    mask = _detect_exchange_mask(df)
    assert mask.tolist() == [False, True, True, True, True]
