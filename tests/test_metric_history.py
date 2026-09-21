"""Regression tests for metric snapshot persistence (Feature #5).

Guards against the double-counting bug where repeated dashboard renders
appended shift entries to the same day's file and daily_* totals were summed
across appends (one day showed ৳18.6M / 11,035 orders instead of ~৳130K).
"""

import json

import pandas as pd

import src.utils.metric_history as mh


def _snapshot_dir(monkeypatch, tmp_path):
    d = tmp_path / "metric_snapshots"
    monkeypatch.setattr(mh, "METRIC_SNAPSHOT_DIR", str(d))
    return d


def _read_file(snapshot_dir, key):
    return json.loads(
        (snapshot_dir / f"{key}.json").read_text(encoding="utf-8")
    )


def _today_key():
    return mh._today_key()


def test_double_save_reports_single_count_totals(monkeypatch, tmp_path):
    """Saving a snapshot twice in one day must report the latest values once,
    never the sum of both saves."""
    d = _snapshot_dir(monkeypatch, tmp_path)

    assert mh.save_shift_snapshot(revenue=100.0, orders=2, qty=3, aov=50.0)
    assert mh.save_shift_snapshot(revenue=120.0, orders=3, qty=4, aov=40.0)

    data = _read_file(d, _today_key())
    assert data["daily_revenue"] == 120.0  # not 220.0
    assert data["daily_orders"] == 3  # not 5
    assert data["daily_qty"] == 4  # not 7


def test_duplicate_save_does_not_grow_audit_trail(monkeypatch, tmp_path):
    """Identical consecutive saves refresh the timestamp instead of appending."""
    d = _snapshot_dir(monkeypatch, tmp_path)

    mh.save_shift_snapshot(revenue=59792.0, orders=36, qty=55, aov=1660.9)
    mh.save_shift_snapshot(revenue=59792.0, orders=36, qty=55, aov=1660.9)

    data = _read_file(d, _today_key())
    assert len(data["shifts"]) == 1
    assert data["daily_revenue"] == 59792.0
    assert data["daily_orders"] == 36


def test_distinct_saves_append_but_overwrite_totals(monkeypatch, tmp_path):
    """Changed metrics append an audit entry; totals still reflect the latest."""
    d = _snapshot_dir(monkeypatch, tmp_path)

    mh.save_shift_snapshot(revenue=600.0, orders=1, qty=6, aov=600.0)
    mh.save_shift_snapshot(revenue=41532.0, orders=25, qty=40, aov=1661.28)

    data = _read_file(d, _today_key())
    assert len(data["shifts"]) == 2
    assert data["daily_revenue"] == 41532.0
    assert data["daily_orders"] == 25


def test_load_snapshot_history_uses_overwritten_totals(monkeypatch, tmp_path):
    """The trend-chart loader must see single-counted totals after a re-save."""
    _snapshot_dir(monkeypatch, tmp_path)

    mh.save_shift_snapshot(revenue=100.0, orders=2, qty=3, aov=50.0)
    mh.save_shift_snapshot(revenue=120.0, orders=3, qty=4, aov=40.0)

    df = mh.load_snapshot_history(7)
    assert not df.empty
    assert len(df) == 1
    row = df.iloc[0]
    assert row["revenue"] == 120.0
    assert row["orders"] == 3
    assert row["qty"] == 4
    assert isinstance(df["date"].iloc[0], pd.Timestamp)


def test_rebuild_daily_totals_uses_last_today_entry():
    """Rebuild picks the last 'Today' entry, ignoring Prev / doubled entries."""
    data = {
        "date": "2026-09-20",
        "shifts": [
            {"ts": "t1", "label": "Today", "revenue": 41532.0, "orders": 25, "qty": 40},
            {"ts": "t2", "label": "Prev", "revenue": 155902.0, "orders": 92, "qty": 149},
            {"ts": "t3", "label": "Today", "revenue": 119584.0, "orders": 36, "qty": 110},
            {"ts": "t4", "label": "Today", "revenue": 59792.0, "orders": 36, "qty": 55},
        ],
        "daily_revenue": 376810.0,
        "daily_orders": 189,
        "daily_qty": 354,
    }

    assert mh.rebuild_daily_totals(data) is True
    assert data["daily_revenue"] == 59792.0
    assert data["daily_orders"] == 36
    assert data["daily_qty"] == 55


def test_rebuild_daily_totals_falls_back_to_last_entry():
    """Without any 'Today' entry, the last valid entry of any label is used."""
    data = {
        "shifts": [
            {"ts": "t1", "label": "Auto", "revenue": 10.0, "orders": 1, "qty": 1},
            {"ts": "t2", "label": "Prev", "revenue": 20.0, "orders": 2, "qty": 2},
        ],
        "daily_revenue": 30.0,
        "daily_orders": 3,
        "daily_qty": 3,
    }

    assert mh.rebuild_daily_totals(data) is True
    assert data["daily_revenue"] == 20.0
    assert data["daily_orders"] == 2


def test_rebuild_daily_totals_without_valid_shifts_is_noop():
    """Malformed or missing shift entries leave the file untouched."""
    data = {"shifts": [{"label": "Today"}], "daily_revenue": 1.0, "daily_orders": 1, "daily_qty": 1}

    assert mh.rebuild_daily_totals(data) is False
    assert data["daily_revenue"] == 1.0
    assert data["daily_orders"] == 1

    empty = {"shifts": []}
    assert mh.rebuild_daily_totals(empty) is False
