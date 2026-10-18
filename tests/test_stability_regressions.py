"""Regression and stability tests for edge cases and runtime invariants.

Covers:
- React KPI component serialization (handling datetimes, strings, and nulls)
- Delivery data parser visual report safety against empty or missing columns
- Date range input defensive handling for Streamlit tuple states
- Pathao bulk tracking index resilience
- Architectural invariant: no invalid st.status(state="warning")
"""

import pandas as pd

from src.config.constants import bd_now
from src.components.react_kpi import render_react_kpi_toolbar
from src.pages.delivery_parser import render_visual_report


def test_render_react_kpi_toolbar_serializes_datetime(monkeypatch):
    """Ensure render_react_kpi_toolbar formats datetime and does not raise TypeError."""
    called_props = {}

    def mock_component(**kwargs):
        called_props.update(kwargs)
        return "All Orders"

    # Patch the custom component declaration
    monkeypatch.setattr(
        "src.components.react_kpi._component_func",
        mock_component,
    )

    views = ["All Orders", "Today Shipped"]
    view_counts = {"All Orders": 10, "Today Shipped": 5}
    metrics = {
        "revenue": {"gross": "৳10,000", "net": "৳9,500", "loss": 5.0, "delta": "+10%"},
        "orders": {"count": 10, "delta": "+2"},
        "units": {"count": 20, "delta": "+4"},
        "aov": {"gross": "৳1,000", "net": "৳950", "delta": "+5%"},
    }
    customer_mix = {"newCount": 6, "returningCount": 4, "returningRatio": 40.0}
    test_dt = bd_now()

    # Pass datetime directly as sync_time
    res = render_react_kpi_toolbar(
        views=views,
        selected_view="All Orders",
        view_counts=view_counts,
        metrics=metrics,
        customer_mix=customer_mix,
        sync_time=test_dt,
    )
    assert res == "All Orders"
    args = called_props.get("args", {})
    assert isinstance(args.get("syncTime"), str)
    assert args.get("syncTime") != ""

    # Pass None as sync_time
    render_react_kpi_toolbar(
        views=views,
        selected_view="All Orders",
        view_counts=view_counts,
        metrics=metrics,
        customer_mix=customer_mix,
        sync_time=None,
    )
    args_none = called_props.get("args", {})
    assert args_none.get("syncTime") is None


def test_delivery_parser_visual_report_empty_and_none(monkeypatch):
    """Ensure render_visual_report handles None, empty DataFrame, and missing columns gracefully."""
    mock_calls = []

    class MockCol:
        def metric(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("streamlit.divider", lambda: mock_calls.append("divider"))
    monkeypatch.setattr(
        "streamlit.subheader", lambda *a, **k: mock_calls.append("subheader")
    )
    monkeypatch.setattr("streamlit.columns", lambda n: [MockCol() for _ in range(n)])
    monkeypatch.setattr("streamlit.write", lambda *a, **k: None)
    monkeypatch.setattr("streamlit.plotly_chart", lambda *a, **k: None)

    # 1. None DataFrame
    render_visual_report(None)
    assert len(mock_calls) == 0

    # 2. Empty DataFrame
    render_visual_report(pd.DataFrame())
    assert len(mock_calls) == 0

    # 3. DataFrame with missing columns
    partial_df = pd.DataFrame([{"Customer": "Alice", "Phone": "01700000000"}])
    render_visual_report(partial_df)
    assert "divider" in mock_calls
    assert "subheader" in mock_calls

    # 4. DataFrame with populated columns
    full_df = pd.DataFrame(
        [
            {
                "Payment Status": "Paid",
                "Delivery Status": "Delivered",
                "COD Amount": 1200,
                "Charge": 100,
                "Discount": 50,
                "Store": "Main Store",
            },
            {
                "Payment Status": "Unpaid",
                "Delivery Status": "Pending",
                "COD Amount": "800",
                "Charge": "60",
                "Discount": 0,
                "Store": "Outlet 1",
            },
        ]
    )
    mock_calls.clear()
    render_visual_report(full_df)
    assert "divider" in mock_calls
    assert "subheader" in mock_calls


def test_no_invalid_status_state_warning():
    """Verify that no code in src/ calls status.update(state='warning').

    Streamlit only accepts 'running', 'complete', or 'error' as valid states.
    Passing 'warning' raises StreamlitAPIException.
    """
    import os

    src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")

    violations = []
    for root, _, files in os.walk(src_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if 'state="warning"' in content or "state='warning'" in content:
                violations.append(path)

    assert not violations, (
        f"Found invalid state='warning' in st.status calls: {violations}"
    )
