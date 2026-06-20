"""Validate that all src/ modules can be imported without errors."""
import sys
import os
import importlib

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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
    "src.processing.whatsapp_processor",
    "src.processing.forecasting",
    "src.processing.delivery_parser",
    "src.services.pathao.client",
    "src.services.llm.manager",
    "src.services.woocommerce.client",
    "src.services.woocommerce.stock",
    "src.utils.url_fetch",
    "src.utils.safe_ops",
    "src.utils.metric_snapshots",
    "src.components.smart_filters",
    "src.utils.display",
    "src.components.clipboard",
    "src.components.styles",
    "src.components.header",
    "src.components.footer",
    "src.components.clock",
    "src.components.bike_animation",
    "src.components.widgets",
    "src.components.snapshot",
    "src.components.status",
    "src.pages.live_dashboard",
    "src.pages.sales_ingestion",
    "src.pages.stock_analytics",
    "src.pages.pathao_orders",
    "src.pages.inventory_distribution",
    "src.pages.whatsapp_messaging",
    "src.pages.delivery_parser",
    "src.pages.dashboard_metrics",
    "src.pages.dashboard_charts",
    "src.pages.dashboard_filters",
    "src.pages.dashboard_output",
    "src.pages.data_pilot",
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
