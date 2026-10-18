"""Date utilities and timezone coercion for order processing."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.config.constants import bd_today


def safe_coerce_datetime_naive(series: pd.Series) -> pd.Series:
    """Safely converts a pandas Series to timezone-naive datetime64[ns].

    If timestamps are timezone-aware or contain explicit UTC ISO indicators (Z or offset),
    converts them to Asia/Dhaka local time (+6).
    Naive timestamps are preserved as local naive datetimes without double shift.
    """
    if series is None or series.empty:
        return pd.to_datetime(series, errors="coerce")

    # If series is already datetime64 dtype
    if pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dt, "tz", None) is not None:
            return series.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
        return series

    # Standard parsing first
    parsed = pd.to_datetime(series, errors="coerce")
    if getattr(parsed.dt, "tz", None) is not None:
        try:
            return parsed.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
        except Exception:
            return parsed.dt.tz_localize(None)

    # If parsed result is naive string series, check if strings contain explicit UTC timezone designators ('Z', '+00:00')
    s_clean = series.dropna()
    if not s_clean.empty and isinstance(s_clean.iloc[0], str):
        first_val = str(s_clean.iloc[0])
        if "Z" in first_val or "+00" in first_val or "UTC" in first_val.upper():
            try:
                parsed_utc = pd.to_datetime(series, errors="coerce", utc=True)
                if getattr(parsed_utc.dt, "tz", None) is not None:
                    return parsed_utc.dt.tz_convert("Asia/Dhaka").dt.tz_localize(None)
            except Exception:
                pass

    return parsed


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
