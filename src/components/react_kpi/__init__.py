"""React KPI Toolbar Component for DEEN-OPS.

Provides an interactive React-powered toolbar combining:
1. Live view switcher pills with counters (All Orders, Today Shipped, Last Day Shipped, Queue)
2. 5 high-impact glassmorphic KPI cards (Revenue, Orders, Units, AOV, Customer Mix)
3. Instant bidirectional view filtering back to Streamlit
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import streamlit.components.v1 as components

_RELEASE = not os.getenv("STREAMLIT_REACT_DEV", "").strip()

_PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
_BUILD_DIR = os.path.join(_PARENT_DIR, "frontend/dist")

# Only declare component if build dir exists or in dev mode
if not _RELEASE:
    _component_func = components.declare_component(
        "react_kpi_toolbar",
        url="http://localhost:5173",
    )
elif os.path.exists(os.path.join(_BUILD_DIR, "index.html")):
    _component_func = components.declare_component(
        "react_kpi_toolbar",
        path=_BUILD_DIR,
    )
else:
    _component_func = None


def is_react_kpi_available() -> bool:
    """Check if the compiled React bundle or dev server is available."""
    if not _RELEASE:
        return True
    return os.path.exists(os.path.join(_BUILD_DIR, "index.html"))


def render_react_kpi_toolbar(
    views: List[str],
    selected_view: str,
    view_counts: Dict[str, int],
    metrics: Dict[str, Any],
    customer_mix: Dict[str, Any],
    sync_time: Optional[str] = None,
    key: str = "react_kpi_toolbar",
) -> str:
    """Render the React KPI toolbar and return the currently selected view.

    Args:
        views: List of available view names.
        selected_view: Currently active view name.
        view_counts: Dict of counts per view name.
        metrics: Dict containing revenue, orders, units, and aov data.
        customer_mix: Dict containing newCount, returningCount, and returningRatio.
        sync_time: Human-readable last sync timestamp.
        key: Streamlit component key.

    Returns:
        The selected view string (from user interaction or default).
    """
    if _component_func is None:
        # Graceful fallback: return selected_view unmodified
        return selected_view

    if hasattr(sync_time, "strftime"):
        formatted_sync_time = sync_time.strftime("%I:%M %p")
    elif sync_time is not None:
        formatted_sync_time = str(sync_time)
    else:
        formatted_sync_time = None

    args = {
        "views": views,
        "selectedView": selected_view,
        "viewCounts": view_counts,
        "metrics": metrics,
        "customerMix": customer_mix,
        "syncTime": formatted_sync_time,
    }

    result = _component_func(
        args=args,
        views=views,
        selectedView=selected_view,
        viewCounts=view_counts,
        metrics=metrics,
        customerMix=customer_mix,
        syncTime=formatted_sync_time,
        default=selected_view,
        key=key,
    )
    return str(result) if result else selected_view
