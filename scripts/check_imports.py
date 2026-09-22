"""Validate that all src/ modules can be imported without errors."""

import importlib
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

MODULES = [
    "src.config.settings",
    "src.config.ui_config",
    "src.config.constants",
    "src.utils.text",
    "src.utils.product",
    "src.utils.file_io",
    "src.utils.logging",
    "src.utils.snapshots",
    "src.state.persistence",
    "src.processing.column_detection",
    "src.processing.data_processing",
    "src.processing.order_processor",
    "src.processing.forecasting",
    "src.processing.delivery_parser",
    "src.services.pathao.client",
    "src.services.pathao.orders",
    "src.services.pathao.dispatch_ledger",
    "src.services.woocommerce.client",
    "src.services.woocommerce.stock",
    "src.utils.safe_ops",
    "src.utils.display",
    "src.components.ui.clipboard",
    "src.components.custom",
    "src.components.custom.chip_filter",
    "src.components.custom.spark_metric",
    "src.components.ui.styles",
    "src.components.layout.header",
    "src.components.layout.footer",
    "src.components.ui.clock",
    "src.components.ui.bike_animation",
    "src.components.ui.widgets",
    "src.components.ui.status",
    "src.components.ui.calendar_slots",
    "src.components.ui.dataframe_search",
    "src.components.ui.empty_state",
    "src.components.ui.ui_components",
    "src.components.ui.mobile_navbar",
    "src.components.dashboard.svg",
    "src.components.react_kpi",
    "src.pages.live_dashboard",
    "src.pages.sales_ingestion",
    "src.pages.stock_analytics",
    "src.pages.pathao_orders",
    "src.pages.inventory_distribution",
    "src.pages.delivery_parser",
    "src.pages.return_analytics",
    "src.pages.woocommerce_orders",
    "src.components.dashboard.dashboard_metrics",
    "src.components.dashboard.dashboard_charts",
    "src.components.dashboard.dashboard_filters",
    "src.components.dashboard.dashboard_output",
    "src.processing.market_basket",
    "src.components.dashboard.market_basket_view",
    "src.pages.product_listing",
    "src.inventory.core",
    "src.processing.categorization",
    "src.processing.stock_categorization",
    "src.processing.hybrid_data_loader",
    "src.services.exports.excel_exporter",
    "src.services.woocommerce.orders",
    "src.utils.customer_registry",
    "src.utils.http",
    "src.utils.metric_history",
    "src.utils.ml_brain",
    "src.processing.sip_outlet_processor",
    "src.pages.sip_outlet_mapper",
]


def main():
    ok = 0
    fail = 0
    errors = []

    for mod in MODULES:
        try:
            importlib.import_module(mod)
            print(f"  OK  {mod}")
            ok += 1
        except Exception as e:
            print(f"  FAIL  {mod}: {e}")
            errors.append((mod, str(e)))
            fail += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {ok} OK, {fail} FAILED out of {len(MODULES)} modules")

    if errors:
        print("\nFailed modules:")
        for mod, err in errors:
            print(f"  - {mod}: {err}")
        sys.exit(1)
    else:
        print("All imports successful!")
        sys.exit(0)


if __name__ == "__main__":
    main()
