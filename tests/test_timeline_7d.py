"""Unit tests for the 7-day rolling dispatch timeline generator."""

from datetime import date, timedelta
import pandas as pd

from src.processing.orders.timeline_7d import build_7day_dispatch_timeline


def test_build_7day_dispatch_timeline():
    ref_d = date(2026, 11, 9)  # Monday
    # Create sample orders across past 4 days
    rows = []
    for i in range(4):
        d_str = (ref_d - timedelta(days=i)).strftime("%Y-%m-%d 14:00:00")
        rows.append(
            {
                "Order ID": 1000 + i,
                "Order Status": "completed",
                "Order Date Modified": d_str,
                "Quantity": 2,
                "Line Total": 2500.0,
            }
        )
    # Add an exchange order on today
    rows.append(
        {
            "Order ID": "D-9999",
            "Order Status": "completed",
            "Order Date Modified": ref_d.strftime("%Y-%m-%d 15:00:00"),
            "Quantity": 1,
            "Line Total": 0.0,
        }
    )

    df = pd.DataFrame(rows)
    report = build_7day_dispatch_timeline(df, reference_date=ref_d)

    assert len(report.days) == 7
    # First day should be today
    today_summary = next(d for d in report.days if d.is_today)
    assert today_summary.is_today is True
    assert today_summary.order_count == 2  # Order 1000 and D-9999
    assert today_summary.exchange_count == 1
    assert today_summary.revenue == 2500.0
    assert today_summary.date_iso == "2026-11-09"
    assert "Nov 09" in today_summary.date_label

    assert report.total_7d_revenue == 10000.0
    assert report.total_7d_orders == 5


def test_timeline_date_completed_precedence():
    ref_d = date(2026, 11, 9)
    # Order completed 3 days ago, but modified today (e.g. note added)
    comp_date = (ref_d - timedelta(days=3)).strftime("%Y-%m-%d 11:00:00")
    mod_date = ref_d.strftime("%Y-%m-%d 16:00:00")

    df = pd.DataFrame(
        [
            {
                "Order ID": "17839",
                "Order Status": "completed",
                "date_completed": comp_date,
                "Order Date Modified": mod_date,
                "Quantity": 1,
                "Line Total": 3500.0,
            }
        ]
    )
    report = build_7day_dispatch_timeline(df, reference_date=ref_d)

    # Must be counted on completion date (3 days ago, Nov 06), NOT today (Nov 09)
    today_summary = next(d for d in report.days if d.is_today)
    assert today_summary.order_count == 0
    assert today_summary.revenue == 0.0

    past_summary = next(d for d in report.days if d.date_iso == "2026-11-06")
    assert past_summary.order_count == 1
    assert past_summary.revenue == 3500.0


def test_timeline_status_filtering_excludes_open_orders():
    ref_d = date(2026, 11, 9)
    df = pd.DataFrame(
        [
            {
                "Order ID": "1001",
                "Order Status": "processing",  # Should be excluded
                "Order Date Modified": ref_d.strftime("%Y-%m-%d 12:00:00"),
                "Quantity": 1,
                "Line Total": 1500.0,
            },
            {
                "Order ID": "1002",
                "Order Status": "cancelled",  # Should be excluded
                "Order Date Modified": ref_d.strftime("%Y-%m-%d 13:00:00"),
                "Quantity": 1,
                "Line Total": 2000.0,
            },
            {
                "Order ID": "1003",
                "Order Status": "completed",  # Should be included
                "Order Date Modified": ref_d.strftime("%Y-%m-%d 14:00:00"),
                "Quantity": 1,
                "Line Total": 2500.0,
            },
        ]
    )
    report = build_7day_dispatch_timeline(df, reference_date=ref_d)
    today_summary = next(d for d in report.days if d.is_today)

    assert today_summary.order_count == 1
    assert today_summary.revenue == 2500.0


def test_filter_orders_to_date():
    from src.processing.orders.timeline_7d import filter_orders_to_date

    df = pd.DataFrame(
        [
            {
                "Order ID": "101",
                "Order Status": "completed",
                "Date Completed": "2026-11-08 14:00:00",
                "Quantity": 2,
                "Line Total": 2000.0,
            },
            {
                "Order ID": "102",
                "Order Status": "completed",
                "Date Completed": "2026-11-09 10:00:00",
                "Quantity": 1,
                "Line Total": 1500.0,
            },
            {
                "Order ID": "103",
                "Order Status": "cancelled",
                "Date Completed": "2026-11-08 14:00:00",
                "Quantity": 1,
                "Line Total": 1000.0,
            },
        ]
    )

    nov8 = filter_orders_to_date(df, "2026-11-08")
    assert len(nov8) == 1
    assert nov8.iloc[0]["Order ID"] == "101"

    nov9 = filter_orders_to_date(df, date(2026, 11, 9))
    assert len(nov9) == 1
    assert nov9.iloc[0]["Order ID"] == "102"
