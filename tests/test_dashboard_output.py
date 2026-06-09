import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import pytest


def _identity_decorator(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


fake_streamlit = types.ModuleType("streamlit")
fake_streamlit.session_state = {}
fake_streamlit.secrets = {}
fake_streamlit.cache_data = _identity_decorator
fake_streamlit.cache_resource = _identity_decorator
fake_streamlit.session_state = {}
fake_streamlit.secrets = {}

class _DummyColumn:
    def __init__(self, *args, **kwargs):
        pass

class _DummyColumnConfig:
    TextColumn = _DummyColumn
    NumberColumn = _DummyColumn

fake_streamlit.column_config = _DummyColumnConfig

fake_components = types.ModuleType("streamlit.components")
fake_v1 = types.ModuleType("streamlit.components.v1")
fake_components.v1 = fake_v1
fake_streamlit.components = fake_components

sys.modules["streamlit"] = fake_streamlit
sys.modules["streamlit.components"] = fake_components
sys.modules["streamlit.components.v1"] = fake_v1

from src.pages import dashboard_output


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyStreamlit:
    def __init__(self, session_state):
        self.session_state = session_state

    def subheader(self, *args, **kwargs):
        return None

    def divider(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def download_button(self, *args, **kwargs):
        return None

    def expander(self, *args, **kwargs):
        return _DummyContext()

    def toggle(self, *args, **kwargs):
        return False

    def button(self, *args, **kwargs):
        return False

    def text_area(self, *args, **kwargs):
        return ""

    def warning(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def text_input(self, label, value="", *args, **kwargs):
        return value

    def dataframe(self, *args, **kwargs):
        return None

    def tabs(self, tabs_list, *args, **kwargs):
        return [_DummyContext() for _ in tabs_list]

    def link_button(self, *args, **kwargs):
        return None

    column_config = _DummyColumnConfig

    def empty(self, *args, **kwargs):
        return _DummyStreamlit(self.session_state)

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return tuple(_DummyContext() for _ in range(count))

    def __getattr__(self, name):
        def _fallback(*args, **kwargs):
            if name == "number_input":
                return 0
            if name in ("checkbox", "toggle"):
                return False
            return None
        return _fallback


@pytest.mark.parametrize(
    ("order_view_mode", "expected_statuses"),
    [
        ("All Orders", ["processing", "shipped"]),
        ("Processing Only", ["processing"]),
        ("Shipped Only", ["shipped"]),
    ],
)
def test_render_dashboard_output_operational_filters_do_not_raise(
    monkeypatch, order_view_mode, expected_statuses
):
    sales_df = pd.DataFrame(
        {
            "Order ID": [101, 102],
            "Order Status": ["processing", "shipped"],
            "Order Date": pd.to_datetime(["2026-05-01 09:00:00", "2026-05-02 10:00:00"]),
            "Order Total Amount": [1000.0, 1200.0],
            "Quantity": [1, 2],
            "Item Cost": [1000.0, 600.0],
            "Item Name": ["Product A", "Product B"],
            "Phone (Billing)": ["01710000000", "01710000001"],
            "SKU": ["SKU-A", "SKU-B"],
            "mod_dt_parsed": pd.to_datetime(["2026-05-01 12:00:00", "2026-05-02 13:00:00"]),
        }
    )

    session_state = {
        "wc_sync_mode": "Operational Cycle",
        "wc_nav_mode": "Today",
        "live_order_filter": order_view_mode,
        "wc_curr_df": sales_df.copy(),
        "wc_prev_df": sales_df.copy(),
        "wc_full_df": pd.DataFrame(),
        "wc_curr_slot": (pd.Timestamp("2026-05-01 00:00:00"), pd.Timestamp("2026-05-03 00:00:00")),
        "wc_prev_slot": (pd.Timestamp("2026-04-29 00:00:00"), pd.Timestamp("2026-05-01 00:00:00")),
    }

    captured = {}

    def fake_render_operational_metrics(m_df, c_df, *args, **kwargs):
        captured["m_df"] = m_df.copy()
        captured["c_df"] = None if c_df is None else c_df.copy()
        summary = pd.DataFrame(
            {
                "Category": ["Test"],
                "Total Qty": [float(m_df["Quantity"].sum())],
                "Total Amount": [float(m_df["Order Total Amount"].sum())],
            }
        )
        top = pd.DataFrame(
            {
                "Product Name": m_df["Item Name"].tolist(),
                "SKU": m_df["SKU"].tolist(),
                "Total Qty": m_df["Quantity"].tolist(),
                "Total Amount": m_df["Order Total Amount"].tolist(),
                "Category": ["Test"] * len(m_df),
                "Clean_Product": m_df["Item Name"].tolist(),
            }
        )
        basket = {"total_orders": int(m_df["Order ID"].nunique()), "avg_basket_value": 1100.0}
        return pd.DataFrame(), summary, top, basket, m_df

    monkeypatch.setattr(dashboard_output, "st", _DummyStreamlit(session_state))
    monkeypatch.setattr(dashboard_output, "render_operational_metrics", fake_render_operational_metrics)
    monkeypatch.setattr(dashboard_output, "render_category_charts", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard_output, "get_dispatch_metrics", lambda *args, **kwargs: {"pending": 0, "dispatched": 1, "dispatch_rate": 100})
    monkeypatch.setattr(dashboard_output, "generate_executive_briefing", lambda *args, **kwargs: "Operational briefing")
    monkeypatch.setattr("src.pages.dashboard_charts.render_spotlight", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.components.clipboard.render_copy_button", lambda *args, **kwargs: None)

    dashboard_output.render_dashboard_output(
        drill=None,
        summ=None,
        top=None,
        timeframe=None,
        basket={},
        source_name="test",
        granular_df=sales_df.copy(),
    )

    assert captured["m_df"]["Order Status"].tolist() == expected_statuses
