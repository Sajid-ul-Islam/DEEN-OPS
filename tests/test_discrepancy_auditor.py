"""Unit tests for the courier discrepancy and revenue leakage auditor."""

from datetime import datetime, timezone, timedelta

from src.processing.orders.discrepancy_auditor import (
    CourierDiscrepancyType,
    audit_order_discrepancies,
)


def test_phantom_delivery_detection():
    # Order marked completed in store, but courier returned it
    data = [
        {
            "Order ID": "1001",
            "Order Status": "completed",
            "Pathao Status": "Returned",
            "Line Total": 2400.0,
            "Customer": "Karim",
            "Phone": "01711111111",
            "Pathao Consignment ID": "C-1001",
        }
    ]
    summary = audit_order_discrepancies(data)
    assert summary.discrepancy_count == 1
    assert summary.critical_count == 1
    assert "1001" in summary.discrepant_order_ids
    assert summary.alerts[0].mismatch_type == CourierDiscrepancyType.PHANTOM_DELIVERY
    assert summary.alerts[0].financial_impact == 2400.0


def test_delivered_but_processing_detection():
    # Order still processing in WC, but courier delivered and collected money
    data = [
        {
            "Order ID": "1002",
            "Order Status": "processing",
            "Pathao Status": "Delivered",
            "Line Total": 1850.0,
            "Pathao Collected Amount": 1850.0,
            "Customer": "Rahim",
            "Phone": "01822222222",
            "Pathao Consignment ID": "C-1002",
        }
    ]
    summary = audit_order_discrepancies(data)
    assert summary.discrepancy_count == 1
    assert (
        summary.alerts[0].mismatch_type
        == CourierDiscrepancyType.DELIVERED_BUT_PROCESSING
    )
    assert summary.alerts[0].financial_impact == 1850.0


def test_uncollected_cod_alert():
    # COD order delivered, but courier collected 0 or recorded uncollected
    data = [
        {
            "Order ID": "1003",
            "Order Status": "completed",
            "Pathao Status": "Delivered",
            "Line Total": 3200.0,
            "Payment Method": "cod",
            "Pathao Collected Amount": 0.0,
            "Customer": "Sultana",
            "Phone": "01933333333",
            "Pathao Consignment ID": "C-1003",
        }
    ]
    summary = audit_order_discrepancies(data)
    assert summary.discrepancy_count == 1
    assert summary.alerts[0].mismatch_type == CourierDiscrepancyType.UNCOLLECTED_COD
    assert summary.alerts[0].financial_impact == 3200.0


def test_delayed_pickup_alert():
    # Order processing for > 48 hours without courier consignment
    old_time = (datetime.now(timezone.utc) - timedelta(hours=60)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    data = [
        {
            "Order ID": "1004",
            "Order Status": "processing",
            "Order Date": old_time,
            "Line Total": 1500.0,
            "Pathao Consignment ID": None,
            "Customer": "Tanvir",
            "Phone": "01544444444",
        }
    ]
    summary = audit_order_discrepancies(data)
    assert summary.discrepancy_count == 1
    assert summary.alerts[0].mismatch_type == CourierDiscrepancyType.DELAYED_PICKUP
