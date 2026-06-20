# Dead Code Report

Catalogue of removed, unused, and no-op code identified during the v1-to-v2 migration. Items listed here have either been deleted, replaced, or are candidates for future cleanup.

---

## Removed Constants and Functions

### `DEFAULT_GSHEET_URL` (removed from `src/config/ui_config.py`)

Previously held a hardcoded Google Sheets CSV export URL used as the default data source for Sales Ingestion. Removed because all ingestion now flows through WooCommerce API sync or file upload via the Smart Ingestion system. The constant was the only reference to a specific Google Sheet; no other code depends on it.

### `load_default_gsheet()` (removed)

A helper function that fetched a DataFrame from `DEFAULT_GSHEET_URL` using `pd.read_csv()`. It was called from the Sales Ingestion page as the "quick start" data source. Replaced by the unified `fetch_dataframe_from_url()` utility in `src/utils/url_fetch.py`, which auto-detects CSV vs XLSX format and works with any public URL.

### `src/services/google/sheets.py` (entire file deleted)

Contained Google Sheets-specific loading logic (public CSV export URL construction, caching wrapper). The file has been deleted; only the empty `__init__.py` remains in `src/services/google/`. All URL-based data fetching is now handled by `src/utils/url_fetch.py`.

---

## Removed UI Blocks

### GSheet Button Blocks (removed from 4 pages)

Each of the following pages previously contained a "Load from Google Sheet" button and associated URL input field. These blocks have been removed:

| Page | File | What Was Removed |
|------|------|-----------------|
| Sales Data Ingestion | `src/pages/sales_ingestion.py` | GSheet URL input + load button in the data source section |
| Bulk Order Processer | `src/pages/pathao_orders.py` | GSheet import option in the order source selector |
| WhatsApp Messaging | `src/pages/whatsapp_messaging.py` | GSheet URL input for loading order data |
| Inventory Distribution | `src/pages/inventory_distribution.py` | GSheet URL input for loading inventory data |

Replacement: Pages now use file upload and/or WooCommerce API sync. For URL-based loading, the generic `fetch_dataframe_from_url()` is available.

---

## No-Op / Unused Code (Still Present)

### `render_sidebar_branding()` in `src/components/sidebar.py` (removed)

**Status:** Removed.

The function loads the DEEN Commerce logo and encodes it to base64 but then does nothing with it. The final line is `pass` with a comment noting the user requested no title in the sidebar. The logo loading code above the `pass` still executes (wasting I/O) but produces no visible output.

**Resolution:** The function has been completely removed.

### `MORE_TOOLS` list in `src/config/ui_config.py` (removed)

**Status:** Removed.

```python
MORE_TOOLS = [
    "System Logs",
    "Dev Lab",
]
```

This list is defined at module level but is not referenced by `app.py` or any navigation logic. The sidebar's "Maintenance & Settings" section uses its own hardcoded options rather than reading from this list.

**Recommendation:** Either wire it into the sidebar navigation or remove it to avoid confusion.

---

## Replaced Logic

### Old PNG Snapshot Logic in `src/components/snapshot.py`

**Status:** Fully replaced by JSON metric snapshot.

The original implementation used `html2canvas` (via a Streamlit JS component) to take a PNG screenshot of the rendered dashboard. This was brittle, slow, and produced large files.

**Replacement:** `src/components/snapshot.py` now contains `compute_snapshot_metrics()` which extracts core KPIs (qty, revenue, orders, avg basket) and category breakdowns into a structured dict, and `render_snapshot_button()` which offers a JSON download. The persistence layer lives in `src/utils/metric_snapshots.py` (`save_metric_snapshot()` / `load_metric_snapshot()`).

The JSON snapshot is smaller, machine-readable, and suitable for trend comparison across snapshots.

---

## Dead Code Audit — June 2026

Comprehensive dead code sweep across the `src/` tree. All items below have been **removed** unless stated otherwise.

### Deleted Files (zero imports across the codebase)

| File | Contents | Evidence |
|------|----------|----------|
| `src/components/sidebar.py` | Empty placeholder — comments only, no code | Never imported |
| `src/components/data_display.py` | `render_numbered_dataframe()` | Zero imports; only defined |
| `src/components/live_banner.py` | `render_live_banner()` | Zero imports; only defined |
| `src/state/insights.py` | `get_business_insights()` | Zero imports; only defined |
| `src/services/llm/rag_engine.py` | `RAGEngine` class (DuckDB vector search) | Zero imports; only defined |

### Removed Functions

| Function | File | Reason |
|----------|------|--------|
| `render_performance_analysis()` | `src/pages/dashboard_output.py` | ~182-line function never called. `render_dashboard_output()` uses the private `_render_*` helpers instead. |
| `get_category_from_name()` | `src/utils/product.py` | Only consumer of `@lru_cache` in this file; never imported or called. |
| `classify_columns()` | `src/processing/column_detection.py` | Thin wrapper around `detect_filterable_columns`; never imported or called. |

### Removed Dead Imports (orphaned by the above deletions)

| Import | File | Reason |
|--------|------|--------|
| `from src.processing.forecasting import PredictiveIntelligence` | `src/pages/dashboard_output.py` | Only used by the removed `render_performance_analysis()`. |
| `import functools` | `src/utils/product.py` | Only used by the removed `@lru_cache` decorator on `get_category_from_name()`. |

### Removed Commented-Out Code

| File | Line | Code |
|------|------|------|
| `src/pages/delivery_parser.py` | 122 | `# section_card("Delivery Text Parser", "")` |
| `src/pages/whatsapp_messaging.py` | 48 | `# section_card("WhatsApp Verification", "")` |

### Deduplicated Excel Export

| Item | Before | After |
|------|--------|-------|
| Delivery Excel export | `df_to_excel_bytes()` in `src/processing/delivery_parser.py` (local duplicate with extra styling) | `to_excel_bytes()` from `src/utils/file_io.py` with `sheet_name="Deliveries"` |
| `BytesIO` import | `src/processing/delivery_parser.py` | Removed (only consumer was the deleted `df_to_excel_bytes`) |

**Note:** The removed `df_to_excel_bytes` had delivery-specific Excel styling (freeze panes, column widths, number formatting) that the shared utility does not provide. This is a minor visual regression in the downloaded `.xlsx` files.
