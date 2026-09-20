"""Metric snapshot persistence for daily shift history (Feature #5).

Saves a daily shift summary as a JSON file under resources/metric_snapshots/.
Provides a loader that returns a DataFrame of historical metrics for trend charts.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

from src.config.constants import METRIC_SNAPSHOT_DIR, bd_now


def _today_key() -> str:
    return bd_now().strftime("%Y-%m-%d")


def _snapshot_path(date_key: str) -> str:
    return os.path.join(METRIC_SNAPSHOT_DIR, f"{date_key}.json")


def save_shift_snapshot(
    revenue: float,
    orders: int,
    qty: int,
    aov: float,
    shift_label: str = "Auto",
    top_products: Optional[list[dict]] = None,
) -> bool:
    """Persist a single shift's key metrics to a daily JSON snapshot file.

    Repeated calls on the same day append shift entries as an audit trail, but
    the day-level totals (daily_revenue / daily_orders / daily_qty) always
    OVERWRITE with the latest call's values (last-write-wins) — they are never
    summed, so a day rendered many times is counted exactly once.
    Returns True on success.
    """
    try:
        os.makedirs(METRIC_SNAPSHOT_DIR, exist_ok=True)
        key = _today_key()
        path = _snapshot_path(key)

        # Load existing file for today if it exists
        existing: dict = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        shifts: list = existing.get("shifts", [])
        entry = {
            "ts": bd_now().isoformat(),
            "label": shift_label,
            "revenue": round(revenue, 2),
            "orders": int(orders),
            "qty": int(qty),
            "aov": round(aov, 2),
            "top_products": top_products or [],
        }
        # Skip duplicate appends when the metrics are unchanged since the last
        # save — just refresh the timestamp so the file records the latest
        # observation without bloating the audit trail.
        if shifts:
            last = shifts[-1]
            if last.get("label") == shift_label and all(
                last.get(k) == entry[k] for k in ("revenue", "orders", "qty", "aov")
            ):
                last["ts"] = entry["ts"]
            else:
                shifts.append(entry)
        else:
            shifts.append(entry)
        existing["date"] = key
        existing["shifts"] = shifts

        # Day-level aggregates: OVERWRITE (last-write-wins), never sum.
        existing["daily_revenue"] = round(revenue, 2)
        existing["daily_orders"] = int(orders)
        existing["daily_qty"] = int(qty)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _is_valid_shift(entry: dict) -> bool:
    """A shift entry is valid when it carries the expected numeric metrics."""
    try:
        float(entry["revenue"])
        int(entry["orders"])
        int(entry["qty"])
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _pick_last_valid_shift(shifts: list) -> Optional[dict]:
    """Pick the day's most representative shift entry.

    Prefers the LAST 'Today'-labelled entry (the fullest, most recent view of
    that calendar day's sales). Falls back to the last entry of any label —
    e.g. 'Prev' — only when no 'Today' entry exists.
    """
    valid = [s for s in shifts if isinstance(s, dict) and _is_valid_shift(s)]
    if not valid:
        return None
    today_entries = [s for s in valid if s.get("label") == "Today"]
    return today_entries[-1] if today_entries else valid[-1]


def rebuild_daily_totals(data: dict) -> bool:
    """Rebuild a snapshot dict's daily_* aggregates from its last valid shift.

    Earlier versions SUMMED every appended shift entry, massively double-
    counting days that were rendered multiple times. The last 'Today'-labelled
    entry is the best available approximation of that day's true totals.
    Returns True if totals were rebuilt, False when no valid shift exists.
    """
    shift = _pick_last_valid_shift(data.get("shifts", []))
    if shift is None:
        return False
    data["daily_revenue"] = round(float(shift["revenue"]), 2)
    data["daily_orders"] = int(shift["orders"])
    data["daily_qty"] = int(shift["qty"])
    return True


def load_snapshot_history(days: int = 30) -> pd.DataFrame:
    """Load the last `days` days of snapshot files and return a flat DataFrame.

    Columns: date, revenue, orders, qty, aov
    """
    records = []
    try:
        if not os.path.exists(METRIC_SNAPSHOT_DIR):
            return pd.DataFrame()

        files = sorted(
            [f for f in os.listdir(METRIC_SNAPSHOT_DIR) if f.endswith(".json")],
            reverse=True,
        )[:days]

        for fname in files:
            path = os.path.join(METRIC_SNAPSHOT_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                records.append(
                    {
                        "date": data.get("date", fname.replace(".json", "")),
                        "revenue": data.get("daily_revenue", 0),
                        "orders": data.get("daily_orders", 0),
                        "qty": data.get("daily_qty", 0),
                    }
                )
            except Exception:
                continue
    except Exception:
        pass

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    return df
