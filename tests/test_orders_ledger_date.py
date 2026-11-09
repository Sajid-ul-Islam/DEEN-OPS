"""Unit tests for date rendering and timeline date scoping in the Orders Ledger."""

import pandas as pd
from src.processing.orders.date_utils import safe_coerce_datetime_naive


def test_order_ledger_date_normalization():
    raw_dates = [
        "2026-11-09T08:15:30Z",  # UTC ISO timestamp (14:15:30 BDT)
        "2026-11-09 14:15:30",  # Naive BDT
        "2026-11-08T20:00:00+00:00",  # UTC offset (02:00:00 BDT next day Nov 9)
    ]
    series = pd.Series(raw_dates)
    coerced = safe_coerce_datetime_naive(series)

    # All should be converted to Bangladesh local date (Nov 09, 2026)
    dates_str = coerced.dt.strftime("%Y-%m-%d").tolist()
    assert dates_str == ["2026-11-09", "2026-11-09", "2026-11-09"]

    # Formatted display string
    display_str = coerced.dt.strftime("%d %b %Y, %I:%M %p").tolist()
    assert "09 Nov 2026" in display_str[0]
    assert "02:15 PM" in display_str[0]
