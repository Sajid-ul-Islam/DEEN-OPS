"""Regression tests for shipped-today scoping (GOAL.md invariant 3).

Rules locked in here for `filter_shipped_by_slot`:

  - An order counts as shipped if its status is in the shipped set (and NOT in
    hold, waiting, processing, or cancelled/refunded).
  - Orders whose status is hold, waiting, pending, or processing NEVER count as shipped,
    even if they have a consignment ID.
  - "Shipped today" uses the effective date (modification date, falling back to
    creation date) matched against today's BD calendar date — slot-independent,
    so orders placed days ago but dispatched today still count.
  - Prev / comparison modes scope shipped orders to the operational slot window.
  - A user-selected custom date range scopes shipped orders by effective date.
"""

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, timezone

from conftest import build_order_df, now_bd

from src.processing.data_processing import filter_shipped_by_slot


# ── Today mode: calendar-date match, slot-independent ────────────────────────


def test_shipped_today_is_slot_independent_and_excludes_reverted_statuses(op_state):
    now = now_bd().replace(hour=12, minute=0, second=0, microsecond=0)
    orders = [
        # Status changed back to processing (has consignment) → must NOT count as shipped today.
        (601, "processing", now - timedelta(days=3), now - timedelta(hours=2), "DD601"),
        # Status shipped, modified today → counts.
        (602, "shipped", now - timedelta(hours=4), now - timedelta(hours=1), "DD602"),
        # Shipped yesterday → excluded in Today mode.
        (603, "shipped", now - timedelta(days=1), now - timedelta(days=1), ""),
        # Status changed back to on-hold (has consignment) → must NOT count as shipped.
        (604, "on-hold", now - timedelta(hours=2), now - timedelta(hours=1), "DD604"),
        # Status changed back to waiting/pending (has consignment) → must NOT count as shipped.
        (605, "waiting", now - timedelta(hours=2), now - timedelta(hours=1), "DD605"),
        (606, "pending", now - timedelta(hours=2), now - timedelta(hours=1), "DD606"),
        # Status completed today without consignment → counts as shipped.
        (607, "completed", now - timedelta(hours=3), now - timedelta(hours=1), ""),
        # Transitional/fulfillment states are workload, not recognized sales.
        (608, "confirmed", now - timedelta(hours=3), now - timedelta(hours=1), ""),
        (609, "dispatched", now - timedelta(hours=3), now - timedelta(hours=1), ""),
        (610, "delivered", now - timedelta(hours=3), now - timedelta(hours=1), ""),
    ]
    df = build_order_df(orders)

    shipped = filter_shipped_by_slot(df, "Today", is_comparison=False)

    assert set(shipped["Order ID"]) == {602, 607}


def test_actual_sales_status_set_is_strict():
    from src.config.constants import SHIPPED_STATUSES

    assert set(SHIPPED_STATUSES) == {
        "shipped",
        "completed",
        "wc-shipped",
        "wc-completed",
    }


def test_shipped_falls_back_to_creation_date_when_modified_missing(op_state):
    now = now_bd().replace(hour=12, minute=0, second=0, microsecond=0)
    orders = [
        # Modification date missing → falls back to creation date (today).
        (1001, "shipped", now - timedelta(hours=3), None, ""),
        # Modification date missing and created yesterday → NOT today.
        (1002, "shipped", now - timedelta(days=1), None, ""),
    ]
    df = build_order_df(orders)

    shipped = filter_shipped_by_slot(df, "Today", is_comparison=False)

    assert set(shipped["Order ID"]) == {1001}


# ── Prev / comparison modes: slot-window scoping ─────────────────────────────


def test_prev_mode_scopes_shipped_to_prev_slot(op_state):
    pc = op_state["prev_cutoff"]
    now = now_bd()
    orders = [
        # Within the previous operational slot (yesterday 18:00 → today 18:00).
        (701, "shipped", pc - timedelta(hours=20), pc - timedelta(hours=20), ""),
        (702, "shipped", pc - timedelta(hours=5), pc - timedelta(hours=5), ""),
        # Shipped today → outside the prev slot.
        (703, "shipped", now - timedelta(hours=2), now - timedelta(hours=2), ""),
        # Shipped well before the prev slot start → excluded.
        (704, "shipped", pc - timedelta(days=5), pc - timedelta(days=5), ""),
    ]
    df = build_order_df(orders)

    prev = filter_shipped_by_slot(df, "Prev", is_comparison=False)

    assert set(prev["Order ID"]) == {701, 702}


def test_comparison_mode_scopes_to_previous_calendar_day(op_state, monkeypatch):
    comparison_day = datetime(2026, 9, 8).date()
    monkeypatch.setattr(
        "src.processing.data_processing.bd_today",
        lambda: comparison_day + timedelta(days=1),
    )
    orders = [
        (801, "shipped", "2026-09-08 10:00:00", "2026-09-08 10:00:00", ""),
        (802, "completed", "2026-09-08 22:00:00", "2026-09-08 22:00:00", ""),
        (803, "shipped", "2026-09-09 01:00:00", "2026-09-09 01:00:00", ""),
    ]
    df = build_order_df(orders)

    comp = filter_shipped_by_slot(df, "Today", is_comparison=True)

    assert set(comp["Order ID"]) == {801, 802}


# ── Custom range: effective-date scoping ─────────────────────────────────────


def test_custom_range_scopes_shipped_by_effective_date(op_state):
    now = now_bd()
    range_day = (now - timedelta(days=1)).date()
    st.session_state["live_custom_range"] = (range_day, range_day)

    orders = [
        # Effective (modified) date inside the range → kept.
        (901, "shipped", now - timedelta(days=1), now - timedelta(days=1), ""),
        # Effective date outside the range → excluded.
        (902, "shipped", now - timedelta(days=3), now - timedelta(days=3), ""),
    ]
    df = build_order_df(orders)

    scoped = filter_shipped_by_slot(df, "Today", is_comparison=False)

    assert set(scoped["Order ID"]) == {901}


def test_dispatch_metrics_reverted_to_hold_waiting_process(op_state):
    from src.processing.data_processing import get_dispatch_metrics

    now = now_bd()
    orders = [
        # Truly shipped orders
        (101, "completed", now - timedelta(hours=2), now - timedelta(hours=1), "DD101"),
        (102, "shipped", now - timedelta(hours=3), now - timedelta(hours=1), ""),
        # Reverted orders (have consignment but status changed back to hold / waiting / processing)
        (
            103,
            "processing",
            now - timedelta(hours=4),
            now - timedelta(hours=1),
            "DD103",
        ),
        (104, "on-hold", now - timedelta(hours=4), now - timedelta(hours=1), "DD104"),
        (105, "waiting", now - timedelta(hours=4), now - timedelta(hours=1), "DD105"),
        (106, "pending", now - timedelta(hours=4), now - timedelta(hours=1), "DD106"),
    ]
    df = build_order_df(orders)

    metrics = get_dispatch_metrics(df, total_orders=len(df))

    # Only 101 and 102 are dispatched
    assert metrics["dispatched"] == 2
    # 103, 104, 105, 106 are in pending queue
    assert metrics["pending"] == 4
    # Only 101 has Pathao consignment among the dispatched orders
    assert metrics["pathao_count"] == 1


# ── Evening visibility within the same calendar day ─────────────────────────


def test_shipped_orders_remain_visible_after_cutoff_same_day(op_state, monkeypatch):
    """Orders shipped after cutoff remain in the same BD calendar-day partition."""
    from src.services.woocommerce.client import (
        _compute_cutoff_times,
        _partition_operational_data,
    )

    tz_bd = timezone(timedelta(hours=6))

    # Scenario A: Wall-clock is 19:30 on Saturday (after 18:00 cutoff)
    sat_evening = datetime(2026, 9, 5, 19, 30, tzinfo=tz_bd)
    monkeypatch.setattr(
        "src.services.woocommerce.client.datetime",
        type(
            "MockDT",
            (datetime,),
            {"now": lambda tz=None: sat_evening, "combine": datetime.combine},
        ),
    )

    cutoff_today, prev_cutoff, day_before_prev, shipped_limit = _compute_cutoff_times(
        tz_bd
    )
    assert cutoff_today.date() == sat_evening.date()
    assert prev_cutoff < cutoff_today

    orders = [
        # Order shipped at 14:00 Saturday (before 18:00)
        (
            201,
            "shipped",
            sat_evening.replace(tzinfo=None) - timedelta(hours=5),
            sat_evening.replace(tzinfo=None) - timedelta(hours=5),
            "DD201",
        ),
        # Order shipped at 18:15 Saturday (late dispatch)
        (
            202,
            "shipped",
            sat_evening.replace(tzinfo=None) - timedelta(hours=1),
            sat_evening.replace(tzinfo=None) - timedelta(hours=1),
            "DD202",
        ),
        # Order shipped Thursday (prev shift)
        (
            203,
            "shipped",
            prev_cutoff - timedelta(hours=2),
            prev_cutoff - timedelta(hours=2),
            "DD203",
        ),
    ]
    df = build_order_df(orders)

    df_live, df_prev, _, _, _ = _partition_operational_data(df)

    # Both 201 and 202 must be in Today's partition at 19:30
    assert {201, 202} <= set(df_live["Order ID"])
    # 203 belongs to the previous shift
    assert 203 in set(df_prev["Order ID"])
    assert 203 not in set(df_live["Order ID"])


# ── Authoritative Date Completed & Weekend Fulfillment Invariants ───────────


def test_weekend_holiday_fulfillment_counts_as_shipped_today():
    """Orders placed before weekend/holiday (e.g. Thu night) and completed Saturday must count today."""
    from conftest import FakeSessionState
    from src.services.woocommerce.client import _apply_shipped_history

    st.session_state = FakeSessionState()
    st.session_state["_shipped_history_cache"] = {}

    now = now_bd().replace(hour=12, minute=0, second=0, microsecond=0)
    created_thursday = now - timedelta(days=2)  # ~48 hours ago
    completed_today = now - timedelta(hours=1)

    df_test = pd.DataFrame(
        [
            {
                "Order ID": "17941",
                "Order Number": "17941",
                "Order Date": str(created_thursday),
                "Order Date Modified": str(completed_today),
                "Date Completed": str(completed_today),
                "Order Status": "completed",
            }
        ]
    )

    df_resolved = _apply_shipped_history(df_test)
    assert df_resolved.loc[0, "mod_dt_parsed"].date() == now.date()

    shipped = filter_shipped_by_slot(df_resolved, "Today", is_comparison=False)
    assert "17941" in set(shipped["Order ID"])


def test_old_order_modified_today_preserves_past_completed_date():
    """Old completed orders edited today (notes/exchanges) must NOT recount as shipped today."""
    from conftest import FakeSessionState
    from src.services.woocommerce.client import _apply_shipped_history

    st.session_state = FakeSessionState()
    st.session_state["_shipped_history_cache"] = {}

    now = now_bd().replace(hour=12, minute=0, second=0, microsecond=0)
    created_old = now - timedelta(days=3)
    completed_past = now - timedelta(days=2)
    modified_today = now - timedelta(minutes=30)

    df_test = pd.DataFrame(
        [
            {
                "Order ID": "17839",
                "Order Number": "17839",
                "Order Date": str(created_old),
                "Order Date Modified": str(modified_today),
                "Date Completed": str(completed_past),
                "Order Status": "completed",
            }
        ]
    )

    df_resolved = _apply_shipped_history(df_test)
    assert df_resolved.loc[0, "mod_dt_parsed"].date() == completed_past.date()

    shipped = filter_shipped_by_slot(df_resolved, "Today", is_comparison=False)
    assert "17839" not in set(shipped["Order ID"])


def test_zero_amount_exchange_replacement_counts_as_shipped_today():
    """Replacement exchange orders created and completed today count as today's shipments."""
    from conftest import FakeSessionState
    from src.services.woocommerce.client import _apply_shipped_history

    st.session_state = FakeSessionState()
    st.session_state["_shipped_history_cache"] = {}

    now = now_bd().replace(hour=12, minute=0, second=0, microsecond=0)
    created_today = now - timedelta(hours=2)
    completed_today = now - timedelta(hours=1)

    df_test = pd.DataFrame(
        [
            {
                "Order ID": "18085",
                "Order Number": "18085",
                "Order Date": str(created_today),
                "Order Date Modified": str(completed_today),
                "Date Completed": str(completed_today),
                "Order Status": "completed",
                "Order Total Amount": 0.0,
            }
        ]
    )

    df_resolved = _apply_shipped_history(df_test)
    assert df_resolved.loc[0, "mod_dt_parsed"].date() == now.date()

    shipped = filter_shipped_by_slot(df_resolved, "Today", is_comparison=False)
    assert "18085" in set(shipped["Order ID"])
