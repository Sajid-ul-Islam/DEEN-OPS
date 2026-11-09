"""Date utilities and timezone coercion for order processing."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.config.constants import bd_today


def _coerce_single_timestamp(val):
    if pd.isna(val) or val is None or val == "":
        return pd.NaT
    if isinstance(val, (datetime, pd.Timestamp)):
        if getattr(val, "tzinfo", None) is not None:
            return pd.to_datetime(val).tz_convert("Asia/Dhaka").tz_localize(None)
        return pd.to_datetime(val)
    s_val = str(val).strip()
    if not s_val:
        return pd.NaT
    try:
        dt = pd.to_datetime(s_val)
        if getattr(dt, "tzinfo", None) is not None:
            return dt.tz_convert("Asia/Dhaka").tz_localize(None)
        return dt
    except Exception:
        return pd.NaT


def safe_coerce_datetime_naive(series: pd.Series) -> pd.Series:
    """Safely converts a pandas Series to timezone-naive datetime64[ns].

    If timestamps are timezone-aware or contain explicit UTC ISO indicators (Z or offset),
    converts them to Asia/Dhaka local time (+6).
    Naive timestamps are preserved as local naive datetimes without double shift.
    Robust against mixed timezone and naive timestamp series.
    """
    if series is None or series.empty:
        return pd.to_datetime(series, errors="coerce")

    # If series is already datetime64 dtype
    if pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dt, "tz", None) is not None:
            return series.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
        return series

    # Element-wise coercion handles mixed string/aware/naive series seamlessly
    coerced = series.apply(_coerce_single_timestamp)
    return pd.to_datetime(coerced, errors="coerce")


def get_previous_working_day(reference_date=None):
    """Return the operational previous working day for comparisons.

    Skips Friday (the standard weekly off-day / holiday in Bangladesh).
    Specifically:
    - If reference_date is Saturday (weekday 5), returns Thursday (skipping Friday).
    - If the preliminary previous day is Friday (weekday 4), steps back to Thursday.
    """
    d = reference_date or bd_today()
    if hasattr(d, "date") and callable(d.date):
        d = d.date()
    elif isinstance(d, datetime):
        d = d.date()
    candidate = d - timedelta(days=1)
    if candidate.weekday() == 4:  # Friday is weekday 4 in Python
        candidate -= timedelta(days=1)
    return candidate
