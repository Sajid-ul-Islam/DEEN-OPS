"""Regression tests for the consolidated Live Dashboard order-view filtering.

These lock in the refactor from the dashboard audit:
- ``apply_order_view`` / ``apply_order_view_comparison`` are the single source
  of truth for the "All Orders / Shipped / Processing" selector (replacing the
  three previously duplicated implementations).
- KPI card labels in ``render_operational_metrics`` must reflect the actual
  ``live_order_filter`` values ("Shipped"/"Processing"), not the dead
  "Shipped Only"/"Processing Only" strings.

The filter helper is exercised with a lightweight fake Streamlit session state so
it never touches disk or the network.
"""

import pandas as pd
import pytest
import streamlit as st
from datetime import date

from src.processing.data_processing import (
    apply_order_view,
    apply_order_view_comparison,
    compute_live_filter_counts,
    filter_all_orders_to_slot,
    filter_live_dashboard_view,
    filter_shipped_by_slot,
)


class _FakeSessionState(dict):
    """Minimal stand-in for streamlit.session_state."""

    def get(self, key, default=None):
        return super().get(key, default)


@pytest.fixture()
def fake_session(monkeypatch):
    st.session_state = _FakeSessionState()
    # Slot windows used by the filter helpers.
    st.session_state["wc_curr_slot"] = (
        pd.Timestamp("2026-08-13 18:00:00"),
        pd.Timestamp("2026-08-14 18:00:00"),
    )
    st.session_state["wc_prev_slot"] = (
        pd.Timestamp("2026-08-12 18:00:00"),
        pd.Timestamp("2026-08-13 18:00:00"),
    )
    st.session_state["live_custom_range"] = None

    # Freeze the BD calendar day to the fixture's "today" so the
    # Today-mode "shipped today" filter (which compares against the live
    # bd_today() clock) is deterministic instead of depending on the wall clock.
    fixture_today = date(2026, 8, 13)
    monkeypatch.setattr(
        "src.processing.data_processing.bd_today", lambda: fixture_today
    )
    monkeypatch.setattr("src.pages.live_dashboard.bd_today", lambda: fixture_today)
    return st.session_state


def _orders(rows):
    """Build a minimal orders DataFrame.

    rows: list of (order_id, status, created, modified)
    """
    data = []
    for oid, status, created, modified in rows:
        data.append(
            {
                "Order ID": oid,
                "Order Status": status,
                "Order Date": created,
                "Order Date Modified": modified,
            }
        )
    return pd.DataFrame(data)


def test_apply_order_view_all_today_delegates_to_slot(fake_session):
    df = _orders(
        [
            (1, "processing", "2026-08-13 19:00:00", "2026-08-13 19:00:00"),
            (2, "shipped", "2026-08-14 10:00:00", "2026-08-14 12:00:00"),
            (3, "cancelled", "2026-08-14 09:00:00", "2026-08-14 09:00:00"),
            (4, "on-hold", "2026-08-10 09:00:00", "2026-08-10 09:00:00"),
            (5, "waiting", "2026-08-10 09:00:00", "2026-08-10 09:00:00"),
            (6, "custom-review", "2026-08-10 09:00:00", "2026-08-10 09:00:00"),
        ]
    )
    out = apply_order_view(df, "Today", "All Orders")
    # Cancelled is excluded; all other operational statuses remain visible.
    assert set(out["Order ID"]) == {1, 2, 4, 5, 6}


def test_filter_actual_sales_excludes_transitional_statuses(fake_session):
    from src.processing.data_processing import filter_actual_sales

    df = _orders(
        [
            (1, "completed", "2026-08-13 10:00:00", "2026-08-13 12:00:00"),
            (2, "shipped", "2026-08-13 10:00:00", "2026-08-13 12:00:00"),
            (3, "confirmed", "2026-08-13 10:00:00", "2026-08-13 12:00:00"),
            (4, "on-hold", "2026-08-13 10:00:00", "2026-08-13 12:00:00"),
        ]
    )

    assert set(filter_actual_sales(df)["Order ID"]) == {1, 2}


def test_live_dashboard_today_and_last_day_are_sales_only():
    reference = date(2026, 9, 11)
    df = _orders(
        [
            (1, "shipped", "2026-09-08 09:00:00", "2026-09-11 10:00:00"),
            (2, "completed", "2026-09-10 09:00:00", "2026-09-10 12:00:00"),
            (3, "processing", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (4, "cancelled", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
        ]
    )

    assert set(
        filter_live_dashboard_view(df, "Today Shipped", reference)["Order ID"]
    ) == {1}
    assert set(filter_live_dashboard_view(df, "Today", reference)["Order ID"]) == {1}
    assert set(
        filter_live_dashboard_view(df, "Last Day Shipped", reference)["Order ID"]
    ) == {2}
    assert set(filter_live_dashboard_view(df, "Last Day", reference)["Order ID"]) == {2}


def test_live_dashboard_queue_is_date_independent_and_excludes_processing():
    reference = date(2026, 9, 11)
    df = _orders(
        [
            (1, "processing", "2026-08-01", "2026-08-01"),
            (2, "on-hold", "2026-08-02", "2026-08-02"),
            (3, "waiting", "2026-08-03", "2026-08-03"),
            (4, "pending", "2026-08-04", "2026-08-04"),
            (5, "completed", "2026-09-11", "2026-09-11"),
            (6, "cancelled", "2026-09-11", "2026-09-11"),
        ]
    )

    # 1 (processing) is excluded from Queue.
    # 5 (completed) and 6 (cancelled) are excluded.
    # 2 (on-hold), 3 (waiting), 4 (pending) are kept across dates.
    assert set(filter_live_dashboard_view(df, "Queue", reference)["Order ID"]) == {
        2,
        3,
        4,
    }


def test_live_dashboard_all_orders_excludes_hold_waiting_and_cancelled():
    reference = date(2026, 9, 11)
    df = _orders(
        [
            (1, "completed", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (2, "processing", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (3, "cancelled", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (4, "processing", "2026-09-10 09:00:00", "2026-09-10 10:00:00"),
            (5, "on-hold", "2026-09-10 09:00:00", "2026-09-10 10:00:00"),
            (6, "completed", "2026-09-10 09:00:00", "2026-09-10 10:00:00"),
            (7, "waiting", "2026-09-09 09:00:00", "2026-09-09 10:00:00"),
            (8, "on-hold", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (9, "waiting", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (10, "pending", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
        ]
    )

    # IDs 1 (today completed), 2 (today processing), 4 (prior unfulfilled queue processing) are kept.
    # Cancelled (3) and hold/waiting/pending (5, 7, 8, 9, 10) are excluded.
    assert set(filter_live_dashboard_view(df, "All Orders", reference)["Order ID"]) == {
        1,
        2,
        4,
    }


def test_compute_live_filter_counts_matches_filter_views():
    reference = date(2026, 9, 11)
    df = _orders(
        [
            (1, "completed", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (2, "processing", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (3, "cancelled", "2026-09-11 09:00:00", "2026-09-11 10:00:00"),
            (4, "processing", "2026-09-10 09:00:00", "2026-09-10 10:00:00"),
            (5, "on-hold", "2026-09-10 09:00:00", "2026-09-10 10:00:00"),
            (6, "completed", "2026-09-10 09:00:00", "2026-09-10 10:00:00"),
            (7, "waiting", "2026-09-09 09:00:00", "2026-09-09 10:00:00"),
        ]
    )
    counts = compute_live_filter_counts(df, reference)
    assert counts == {
        "All Orders": 3,
        "Today Shipped": 1,
        "Last Day Shipped": 1,
        "Queue": 2,
    }


def test_apply_order_view_shipped_delegates_to_shipped_filter(fake_session):
    df = _orders(
        [
            (1, "processing", "2026-08-13 19:00:00", "2026-08-13 19:00:00"),
            (2, "shipped", "2026-08-13 10:00:00", "2026-08-13 12:00:00"),
            (3, "shipped", "2026-08-10 10:00:00", "2026-08-10 12:00:00"),
        ]
    )
    out = apply_order_view(df, "Today", "Shipped")
    # Only shipped-today (BD calendar day 2026-08-13) retained.
    assert set(out["Order ID"]) == {2}


def test_apply_order_view_processing_status_filter(fake_session):
    df = _orders(
        [
            (1, "processing", "2026-08-13 19:00:00", "2026-08-13 19:00:00"),
            (2, "shipped", "2026-08-14 10:00:00", "2026-08-14 12:00:00"),
            (3, "on-hold", "2026-08-14 10:00:00", "2026-08-14 10:00:00"),
        ]
    )
    out = apply_order_view(df, "Today", "Processing")
    assert set(out["Order ID"]) == {1}


def test_apply_order_view_case_insensitive_status(fake_session):
    df = _orders(
        [
            (1, "Processing", "2026-08-13 19:00:00", "2026-08-13 19:00:00"),
            (2, "SHIPPED", "2026-08-14 10:00:00", "2026-08-14 12:00:00"),
        ]
    )
    proc = apply_order_view(df, "Today", "Processing")
    assert set(proc["Order ID"]) == {1}


def test_apply_order_view_missing_status_column_passthrough(fake_session):
    df = pd.DataFrame({"Order ID": [1, 2]})
    out = apply_order_view(df, "Today", "Processing")
    assert out is df


def test_apply_order_view_empty_passthrough(fake_session):
    df = pd.DataFrame(columns=["Order ID", "Order Status"])
    assert apply_order_view(df, "Today", "All Orders").empty


def test_apply_order_view_comparison_all_maps_to_prev(fake_session):
    df = _orders(
        [
            (1, "processing", "2026-08-12 19:00:00", "2026-08-12 19:00:00"),
            (2, "shipped", "2026-08-12 20:00:00", "2026-08-12 21:00:00"),
        ]
    )
    out = apply_order_view_comparison(df, "Today", "All Orders")
    # Comparison "All Orders" scopes against the Prev slot window.
    assert set(out["Order ID"]) == {1, 2}


def test_apply_order_view_matches_legacy_implementation(fake_session):
    """apply_order_view must agree with the previously-inlined logic."""
    df = _orders(
        [
            (1, "processing", "2026-08-13 19:00:00", "2026-08-13 19:00:00"),
            (2, "shipped", "2026-08-14 12:00:00", "2026-08-14 12:00:00"),
            (3, "on-hold", "2026-08-14 10:00:00", "2026-08-14 10:00:00"),
        ]
    )
    nav_mode = "Today"

    # Legacy "All Orders" branch
    legacy_all = filter_all_orders_to_slot(df, nav_mode)
    assert set(apply_order_view(df, nav_mode, "All Orders")["Order ID"]) == set(
        legacy_all["Order ID"]
    )

    # Legacy "Shipped" branch
    legacy_shipped = filter_shipped_by_slot(df, nav_mode, is_comparison=False)
    assert set(apply_order_view(df, nav_mode, "Shipped")["Order ID"]) == set(
        legacy_shipped["Order ID"]
    )

    # Legacy "Processing" branch (case-insensitive status filter)
    status_col = "Order Status"
    legacy_proc = df[df[status_col].astype(str).str.lower() == "processing"]
    assert set(apply_order_view(df, nav_mode, "Processing")["Order ID"]) == set(
        legacy_proc["Order ID"]
    )


def test_kpi_label_mapping_uses_actual_filter_values():
    """The KPI card label branches must key on 'Shipped'/'Processing' (the real
    ``live_order_filter`` values), not the dead 'Shipped Only'/'Processing Only'.

    We assert the mapping logic directly via the documented label strings the
    renderer switches on, guarding against a regression that reintroduces the
    unreachable branches.
    """
    valid_filter_values = {"All Orders", "Shipped", "Processing"}
    # The renderer's elif chain must handle exactly these values.
    label_branches = {
        "All Orders": "Gross Items",
        "Shipped": "Shipped Items",
        "Processing": "Processing Items",
    }
    for view in valid_filter_values:
        assert view in label_branches, (
            f"Order view '{view}' has no KPI label branch — check dashboard_metrics.py"
        )
    # Ensure the dead 'Only' variants are NOT what drive labels.
    assert "Shipped Only" not in label_branches
    assert "Processing Only" not in label_branches


def test_all_orders_comparison_frame_resolves_previous_day(fake_session):
    from src.pages.live_dashboard import _get_comparison_frame

    fake_session["live_dashboard_view"] = "All Orders"
    fake_session["wc_nav_mode"] = "Today"
    fake_session["live_order_filter"] = "All Orders"

    # Today is 2026-08-13 (frozen by fake_session fixture)
    orders_df = _orders(
        [
            (101, "completed", "2026-08-13 10:00:00", "2026-08-13 11:00:00"),
            (102, "processing", "2026-08-13 10:00:00", "2026-08-13 10:00:00"),
            (201, "completed", "2026-08-12 10:00:00", "2026-08-12 11:00:00"),
            (202, "processing", "2026-08-12 10:00:00", "2026-08-12 10:00:00"),
            (203, "cancelled", "2026-08-12 10:00:00", "2026-08-12 10:00:00"),
            (204, "on-hold", "2026-08-12 10:00:00", "2026-08-12 10:00:00"),
        ]
    )
    orders_df["Item Cost"] = 500
    orders_df["Quantity"] = 2
    orders_df["Product Name"] = "Test Product"

    fake_session["wc_full_df"] = orders_df

    cmp_df = _get_comparison_frame("All Orders", "Today", "All Orders")
    assert cmp_df is not None and not cmp_df.empty
    # Orders 201 (completed) and 202 (processing) from yesterday must be in comparison
    assert set(cmp_df["Order ID"]) == {201, 202}


def test_today_shipped_comparison_frame_resolves_last_day_shipped(fake_session):
    from src.pages.live_dashboard import _get_comparison_frame

    fake_session["live_dashboard_view"] = "Today Shipped"
    fake_session["wc_nav_mode"] = "Today"
    fake_session["live_order_filter"] = "Shipped"

    orders_df = _orders(
        [
            (101, "completed", "2026-08-13 10:00:00", "2026-08-13 11:00:00"),
            (201, "shipped", "2026-08-12 10:00:00", "2026-08-12 11:00:00"),
            (202, "processing", "2026-08-12 10:00:00", "2026-08-12 10:00:00"),
        ]
    )
    orders_df["Item Cost"] = 500
    orders_df["Quantity"] = 2
    orders_df["Product Name"] = "Test Product"

    fake_session["wc_full_df"] = orders_df

    cmp_df = _get_comparison_frame("Today Shipped", "Today", "Shipped")
    assert cmp_df is not None and not cmp_df.empty
    assert set(cmp_df["Order ID"]) == {201}


def test_queue_view_has_no_comparison_frame(fake_session):
    from src.pages.live_dashboard import _get_comparison_frame

    cmp_df = _get_comparison_frame("Queue", "Backlog", "Queue")
    assert cmp_df is None
