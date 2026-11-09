"""Dashboard components package.

This module contains reusable UI components for the Live Dashboard,
refactored following Hick's Law principles for reduced cognitive load.
"""

from src.components.dashboard.dispatch_export_view import (
    render_dispatch_export,
)
from src.components.dashboard.executive_briefing_card import (
    render_executive_briefing_card,
)
from src.components.dashboard.live_components import (
    _render_dashboard_view_selector,
    _render_date_range_selector,
    _render_operation_mode_selector,
    _render_order_filter_selector,
    _render_refresh_controls,
    render_dashboard_banner,
)
from src.components.dashboard.orders_ledger_view import (
    render_orders_ledger_view,
)
from src.components.dashboard.timeline_7d_bar import (
    render_timeline_7d_bar,
)

__all__ = [
    "_render_dashboard_view_selector",
    "_render_date_range_selector",
    "_render_operation_mode_selector",
    "_render_order_filter_selector",
    "_render_refresh_controls",
    "render_dashboard_banner",
    "render_dispatch_export",
    "render_executive_briefing_card",
    "render_orders_ledger_view",
    "render_timeline_7d_bar",
]

# Re-export with public names (without underscore prefix) for easier imports
render_date_range_selector = _render_date_range_selector
render_dashboard_view_selector = _render_dashboard_view_selector
render_operation_mode_selector = _render_operation_mode_selector
render_order_filter_selector = _render_order_filter_selector
render_refresh_controls = _render_refresh_controls

__all__.extend(
    [
        "render_date_range_selector",
        "render_dashboard_view_selector",
        "render_operation_mode_selector",
        "render_order_filter_selector",
        "render_refresh_controls",
    ]
)
