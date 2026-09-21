"""Unit tests for the mobile bottom navigation bar component."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src.components.ui.mobile_navbar import (
    MOBILE_NAV_LABELS,
    format_mobile_nav_item,
    get_mobile_nav_items,
)
from src.config.ui_config import PRIMARY_NAV


def test_mobile_nav_labels_cover_all_primary_nav_items():
    """Ensure every primary navigation item has an optimized mobile label."""
    for item in PRIMARY_NAV:
        assert item in MOBILE_NAV_LABELS, f"Missing mobile label for {item}"
        label = format_mobile_nav_item(item)
        assert len(label) > 0
        # Mobile labels should be short and concise (under 20 characters)
        assert len(label) < 20
        # First character should be an emoji
        assert ord(label[0]) > 127 or label[0] in "📈🛒📦📊🤖"


def test_format_mobile_nav_item_passthrough():
    """Unrecognized nav items should pass through safely without crash."""
    assert format_mobile_nav_item("Unknown Tab") == "Unknown Tab"
    assert format_mobile_nav_item("") == ""


def test_get_mobile_nav_items_filtering():
    """Filters nav items list while preserving order."""
    items = ["📈 Live Dashboard", "Custom Extra", "🛒 Orders & Fulfillment"]
    result = get_mobile_nav_items(items)
    assert "📈 Live Dashboard" in result
    assert "🛒 Orders & Fulfillment" in result
    assert len(result) == 3


def test_mobile_navbar_state_synchronization_apptest(tmp_path):
    """Test two-way synchronization between sidebar nav and mobile bottom navbar."""
    script_content = """import streamlit as st
from src.config.ui_config import PRIMARY_NAV, LEGACY_NAV_MAPPING
from src.components.ui.mobile_navbar import render_mobile_navbar

default_nav = PRIMARY_NAV[0]
if "selected_nav" not in st.session_state:
    st.session_state["selected_nav"] = default_nav
if "sidebar_nav" not in st.session_state:
    st.session_state["sidebar_nav"] = st.session_state["selected_nav"]
if "mobile_bottom_nav" not in st.session_state:
    st.session_state["mobile_bottom_nav"] = st.session_state["selected_nav"]

def _sync_from_sidebar() -> None:
    chosen = st.session_state.get("sidebar_nav")
    if chosen:
        st.session_state["selected_nav"] = chosen
        st.session_state["mobile_bottom_nav"] = chosen

def _sync_from_mobile() -> None:
    chosen = st.session_state.get("mobile_bottom_nav")
    if chosen:
        st.session_state["selected_nav"] = chosen
        st.session_state["sidebar_nav"] = chosen

if st.session_state.get("_nav_override"):
    ovr = st.session_state.pop("_nav_override")
    mapped = LEGACY_NAV_MAPPING.get(ovr, ovr)
    if mapped in PRIMARY_NAV:
        st.session_state["selected_nav"] = mapped
        st.session_state["sidebar_nav"] = mapped
        st.session_state["mobile_bottom_nav"] = mapped

st.sidebar.pills(
    "Select Workspace",
    options=PRIMARY_NAV,
    key="sidebar_nav",
    on_change=_sync_from_sidebar,
)

render_mobile_navbar(
    PRIMARY_NAV,
    current_nav=st.session_state["selected_nav"],
    on_change=_sync_from_mobile,
)
"""
    test_file = tmp_path / "test_app_mobile_sync.py"
    test_file.write_text(script_content, encoding="utf-8")

    at = AppTest.from_file(str(test_file)).run()

    # Initial state should be Live Dashboard
    assert at.session_state["selected_nav"] == PRIMARY_NAV[0]
    assert at.session_state["sidebar_nav"] == PRIMARY_NAV[0]
    assert at.session_state["mobile_bottom_nav"] == PRIMARY_NAV[0]

    # Switch via mobile nav to "📦 Inventory & Stock"
    at.segmented_control(key="mobile_bottom_nav").set_value(PRIMARY_NAV[2]).run()
    assert at.session_state["selected_nav"] == PRIMARY_NAV[2]
    assert at.session_state["sidebar_nav"] == PRIMARY_NAV[2]
    assert at.session_state["mobile_bottom_nav"] == PRIMARY_NAV[2]

    # Switch via sidebar to "🤖 Automation Tools"
    at.pills(key="sidebar_nav").set_value(PRIMARY_NAV[4]).run()
    assert at.session_state["selected_nav"] == PRIMARY_NAV[4]
    assert at.session_state["sidebar_nav"] == PRIMARY_NAV[4]
    assert at.session_state["mobile_bottom_nav"] == PRIMARY_NAV[4]


def test_nav_override_mapping_apptest(tmp_path):
    """Test that legacy/feature nav overrides map cleanly to consolidated primary nav."""
    script_content = """import streamlit as st
from src.config.ui_config import PRIMARY_NAV, LEGACY_NAV_MAPPING
from src.components.ui.mobile_navbar import render_mobile_navbar

default_nav = PRIMARY_NAV[0]
if "selected_nav" not in st.session_state:
    st.session_state["selected_nav"] = default_nav
if "sidebar_nav" not in st.session_state:
    st.session_state["sidebar_nav"] = st.session_state["selected_nav"]
if "mobile_bottom_nav" not in st.session_state:
    st.session_state["mobile_bottom_nav"] = st.session_state["selected_nav"]

if st.session_state.get("_nav_override"):
    ovr = st.session_state.pop("_nav_override")
    mapped = LEGACY_NAV_MAPPING.get(ovr, ovr)
    if mapped in PRIMARY_NAV:
        st.session_state["selected_nav"] = mapped
        st.session_state["sidebar_nav"] = mapped
        st.session_state["mobile_bottom_nav"] = mapped

render_mobile_navbar(
    PRIMARY_NAV,
    current_nav=st.session_state["selected_nav"],
)
"""
    test_file = tmp_path / "test_app_override.py"
    test_file.write_text(script_content, encoding="utf-8")

    at = AppTest.from_file(str(test_file))
    at.session_state["_nav_override"] = "🚀 Data Pilot"
    at.run()

    # Should map "🚀 Data Pilot" -> "🤖 Automation Tools"
    assert at.session_state["selected_nav"] == "🤖 Automation Tools"
    assert at.session_state["sidebar_nav"] == "🤖 Automation Tools"
    assert at.session_state["mobile_bottom_nav"] == "🤖 Automation Tools"


def test_orders_sub_feature_initialization_in_route_page(tmp_path):
    """Ensure Orders & Fulfillment initializes orders_sub_feature without AttributeError."""
    script_content = """import streamlit as st
from src.app_bootstrap import _route_page

for key in ["orders_sub_feature", "inventory_sub_feature", "analytics_sub_feature", "automation_sub_feature"]:
    st.session_state.pop(key, None)

_route_page("🛒 Orders & Fulfillment")
"""
    test_file = tmp_path / "test_route_orders.py"
    test_file.write_text(script_content, encoding="utf-8")

    at = AppTest.from_file(str(test_file)).run()
    assert not at.exception, f"Failed with exception: {at.exception}"
    assert at.session_state["orders_sub_feature"] == "Order Tracking"


def test_legacy_subfeature_override():
    """Ensure legacy subfeature mappings correctly match expected sub-features."""
    from src.config.ui_config import LEGACY_NAV_MAPPING, LEGACY_SUBFEATURE_MAPPING

    assert "📦 Pathao Processor" in LEGACY_SUBFEATURE_MAPPING
    sub_key, sub_val = LEGACY_SUBFEATURE_MAPPING["📦 Pathao Processor"]
    assert sub_key == "orders_sub_feature"
    assert sub_val == "Pathao Processor"
    assert LEGACY_SUBFEATURE_MAPPING["🛒 Order Tracking"] == (
        "orders_sub_feature",
        "Order Tracking",
    )
    assert LEGACY_SUBFEATURE_MAPPING["📋 Product Listing"] == (
        "orders_sub_feature",
        "Product Listing",
    )
    assert LEGACY_NAV_MAPPING["📋 Product Listing"] == "🛒 Orders & Fulfillment"
    assert LEGACY_SUBFEATURE_MAPPING[":material/rocket_launch: Data Pilot"] == (
        "automation_sub_feature",
        "Data Pilot",
    )


def test_product_listing_routed_under_orders_fulfillment(tmp_path):
    """Ensure Product Listing routes cleanly under Orders & Fulfillment."""
    script_content = """import streamlit as st
from unittest.mock import patch
from src.app_bootstrap import _route_page

st.session_state["orders_sub_feature"] = "Product Listing"
with patch("src.pages.product_listing.render_product_listing_tab"):
    _route_page("🛒 Orders & Fulfillment")
"""
    test_file = tmp_path / "test_route_product_listing.py"
    test_file.write_text(script_content, encoding="utf-8")

    at = AppTest.from_file(str(test_file)).run(timeout=10)
    assert not at.exception, f"Failed with exception: {at.exception}"
    assert at.session_state["orders_sub_feature"] == "Product Listing"


def test_inventory_sub_feature_initialization_defaults_to_stock_analytics(tmp_path):
    """Ensure Inventory & Stock defaults to Current Stock Analytics."""
    script_content = """import streamlit as st
from unittest.mock import patch
from src.app_bootstrap import _route_page

st.session_state.pop("inventory_sub_feature", None)
with patch("src.pages.stock_analytics.render_stock_analytics_tab"):
    _route_page("📦 Inventory & Stock")
"""
    test_file = tmp_path / "test_route_inventory_defaults.py"
    test_file.write_text(script_content, encoding="utf-8")

    at = AppTest.from_file(str(test_file)).run(timeout=10)
    assert not at.exception, f"Failed with exception: {at.exception}"
    assert at.session_state["inventory_sub_feature"] == "Current Stock Analytics"
