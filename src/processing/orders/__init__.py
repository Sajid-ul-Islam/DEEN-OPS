"""Order processing subpackage for DEEN-OPS.

Provides modularized, single-responsibility units for date coercion, order filtering,
status detection, Polars aggregations, executive briefing, and product listing exports.
"""

from __future__ import annotations

from src.processing.orders.briefing_builder import (
    detect_active_campaign,
    generate_executive_briefing,
)
from src.processing.orders.customer_risk import (
    CustomerRiskRating,
    build_phone_history_stats,
    clean_phone_11_digits,
    score_customer_delivery_risk,
)
from src.processing.orders.data_aggregators import (
    aggregate_data,
    get_dispatch_metrics,
    prepare_granular_data,
)
from src.processing.orders.date_utils import (
    get_previous_working_day,
    safe_coerce_datetime_naive,
)
from src.processing.orders.discrepancy_auditor import (
    DiscrepancyAlert,
    DiscrepancyAuditSummary,
    audit_order_discrepancies,
)
from src.processing.orders.exchange_detector import (
    ExchangeDetails,
    ExchangeSummary,
    analyze_exchanges,
    detect_order_exchange,
)
from src.processing.orders.partial_knapsack import (
    OrderItemEntry,
    PartialKnapsackMatch,
    SubsetMatchResult,
    UnitItemAssignment,
    match_partial_items_advanced,
)
from src.processing.orders.product_aggregator import (
    aggregate_product_listing,
)
from src.processing.orders.status_filters import (
    _detect_exchange_mask,
    apply_order_view,
    apply_order_view_comparison,
    compute_live_filter_counts,
    count_by_status,
    filter_actual_sales,
    filter_all_orders_to_slot,
    filter_live_dashboard_view,
    filter_shipped_by_slot,
    pick_order_id_column,
    robust_order_count,
)
from src.processing.orders.timeline_7d import (
    DayTimelineSummary,
    Timeline7dReport,
    build_7day_dispatch_timeline,
)

__all__ = [
    "CustomerRiskRating",
    "DayTimelineSummary",
    "DiscrepancyAlert",
    "DiscrepancyAuditSummary",
    "ExchangeDetails",
    "ExchangeSummary",
    "OrderItemEntry",
    "PartialKnapsackMatch",
    "SubsetMatchResult",
    "Timeline7dReport",
    "UnitItemAssignment",
    "_detect_exchange_mask",
    "aggregate_data",
    "aggregate_product_listing",
    "analyze_exchanges",
    "apply_order_view",
    "apply_order_view_comparison",
    "audit_order_discrepancies",
    "build_7day_dispatch_timeline",
    "build_phone_history_stats",
    "clean_phone_11_digits",
    "compute_live_filter_counts",
    "count_by_status",
    "detect_active_campaign",
    "detect_order_exchange",
    "filter_actual_sales",
    "filter_all_orders_to_slot",
    "filter_live_dashboard_view",
    "filter_shipped_by_slot",
    "generate_executive_briefing",
    "get_dispatch_metrics",
    "get_previous_working_day",
    "match_partial_items_advanced",
    "pick_order_id_column",
    "prepare_granular_data",
    "robust_order_count",
    "safe_coerce_datetime_naive",
    "score_customer_delivery_risk",
]
