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
