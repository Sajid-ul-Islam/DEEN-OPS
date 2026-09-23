"""Mobile bottom navigation bar component for DEEN-OPS Terminal.

Provides a fixed, thumb-friendly bottom navigation bar on mobile viewports
(<= 768px) while staying completely hidden on desktop viewports (> 768px).
Synchronizes bidirectionally with the sidebar navigation and session state.
"""

from __future__ import annotations

from typing import Callable, Optional

import streamlit as st

# Mobile-optimized labels for the 4 consolidated Jakob's Law navigation tabs
MOBILE_NAV_LABELS: dict[str, str] = {
    "📈 Live Dashboard": "📈 Live",
    "🛒 Orders & Fulfillment": "🛒 Orders",
    "📦 Inventory & Stock": "📦 Stock",
    "📊 Analytics & Insights": "📊 Analytics",
}


def format_mobile_nav_item(item: str) -> str:
    """Format a primary nav item into a compact mobile label."""
    return MOBILE_NAV_LABELS.get(item, item)


def get_mobile_nav_items(nav_items: list[str]) -> list[str]:
    """Return the list of nav items filtered to recognized primary navigation."""
    return [item for item in nav_items if item in MOBILE_NAV_LABELS or item]


def render_mobile_navbar(
    nav_items: list[str],
    current_nav: str,
    on_change: Optional[Callable[[], None]] = None,
    key: str = "mobile_bottom_nav",
) -> str:
    """Render the mobile bottom navigation bar widget.

    Args:
        nav_items: List of primary navigation items.
        current_nav: The currently active navigation item.
        on_change: Optional callback when user taps a tab.
        key: Streamlit widget key.

    Returns:
        The selected navigation item string.
    """
    options = get_mobile_nav_items(nav_items)
    if not options:
        return current_nav

    default_val = current_nav if current_nav in options else options[0]

    # Ensure key is initialized cleanly in session state without dual-state warning
    if key not in st.session_state:
        st.session_state[key] = default_val

    # Use st.segmented_control if available (Streamlit >= 1.39)
    if hasattr(st, "segmented_control"):
        # Wrap in a styled container for DOM scoping
        with st.container(key="mobile_bottom_navbar_container"):
            selected = st.segmented_control(
                "Mobile Navigation",
                options=options,
                format_func=format_mobile_nav_item,
                selection_mode="single",
                required=True,
                width="stretch",
                label_visibility="collapsed",
                key=key,
                on_change=on_change,
            )
            return selected or default_val

    # Fallback for earlier versions if segmented_control not present
    with st.container(key="mobile_bottom_navbar_container"):
        selected = st.pills(
            "Mobile Navigation",
            options=options,
            format_func=format_mobile_nav_item,
            selection_mode="single",
            label_visibility="collapsed",
            key=key,
            on_change=on_change,
        )
        return selected or default_val
