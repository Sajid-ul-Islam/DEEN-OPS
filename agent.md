# DEEN-OPS Blueprint & AI Agent Guide

**To any AI agent reading this file:** this is the working blueprint for the current DEEN-OPS codebase. Read this before changing architecture, session state, dashboard metrics, Pathao processing, or shared data logic.

---

## 1. App Identity
**DEEN OPS Terminal** is an AI-assisted e-commerce operations command center.

Primary goals:
- Explain live operational performance, not just display it.
- Turn WooCommerce, inventory, and Pathao workflows into reliable operator tools.
- Keep the UI visually premium while remaining resilient under bad data and unstable APIs.

The app is still referred to in some legacy docs as `DEEN-BI`, but the active workspace is `DEEN-OPS`.

## 2. Architecture
The project follows a layered structure. Avoid circular imports. Pages should orchestrate; services fetch; processing modules transform; components render.

- `app.py`
  Main Streamlit entrypoint: auth, sidebar routing, layout shell, session reset/save, log access.
- `src/pages/`
  Workspace-level UI modules.
  Important current pages include:
  - `live_dashboard.py`
  - `sales_ingestion.py`
  - `stock_analytics.py`
  - `inventory_distribution.py`
  - `pathao_orders.py`
  - `data_pilot.py`
  - `dashboard_output.py`
  - `dashboard_metrics.py`
- `src/components/`
  Reusable UI widgets and styling helpers.
- `src/services/`
  External integrations:
  - WooCommerce
  - Pathao
  - LLM providers
- `src/processing/`
  Shared transformation logic.
  Important current modules include:
  - `data_processing.py`
  - `column_detection.py`
  - `order_processor.py`
  - `forecasting.py`
- `src/inventory/`
  Inventory matching and distribution logic.
- `src/utils/`
  Stateless helpers.
- `src/config/`
  UI config, constants, settings, environment/secrets access.

## 3. Cloud Deployment Considerations (Streamlit Community Cloud)
- **Ephemeral Filesystem:** Local storage is temporary. Files like `resources/deen_ops.duckdb`, `pathao_map.json`, and CSV snapshots will be wiped when the app restarts or sleeps. The app is built to gracefully handle this by re-syncing from external APIs.
- **No Background Workers:** Streamlit Cloud does not support running background daemon processes like Celery or Redis. All syncs and API requests must run synchronously when triggered by user interaction.
- **Dependencies:** Any third-party package used (like `tenacity`, `duckdb`, `polars`) must be explicitly present in `requirements.txt`.
- **Plotly Image Export (`kaleido`):** Streamlit Cloud sometimes struggles with the `kaleido` package required to export Plotly charts as PNGs. The app has a safe fallback built into `snapshot.py` to export JSON if `kaleido` crashes or is missing.
- **Async LLM Streaming (`aiohttp`):** The Data Pilot uses `aiohttp` to perform asynchronous streaming from the LLM APIs to prevent blocking the Streamlit UI thread. Ensure `aiohttp` is in `requirements.txt`.

## 4. UI/UX Design Guidelines
- **Feedback & Loading:** Prefer `st.toast()` and `st.status()` over `st.spinner()` for a smoother, less disruptive user experience during background network tasks.
- **Empty States:** Never show a blank table. Use `st.info("📬 No inventory data found.")` with descriptive instructions.
- **Premium Metrics:** Use the custom HTML/CSS metric card layout (`<div class="metric-container">`) for KPIs instead of default `st.metric` for better styling.
- **Theme Responsiveness:** Ensure custom HTML elements do not hardcode background colors that break Streamlit's native dark mode.

## 5. Technology Stack
- Frontend: Streamlit with heavy custom CSS injection.
- Data: Pandas and Polars.
- Charts: Plotly.
- AI: multi-provider LLM routing (using `aiohttp` for async streaming).
- ML Forecasting: Scikit-Learn, XGBoost, and Statsmodels.
- APIs: WooCommerce REST API and Pathao Courier API.
## 6. Session State Rules
The app depends heavily on `st.session_state`. Do not rename or remove keys casually.

Common prefixes:
- `live_*`
  Live dashboard state.
- `manual_*`
  Sales ingestion state.
- `stock_*`
  Stock analytics state.
- `pilot_*`
  Data Pilot state.
- `pathao_*`
  Pathao processor state.
- `inv_*`
  Inventory distribution state.
- `wc_*`
  WooCommerce sync, slots, and navigation state.

Pathao-specific state currently used:
- `pathao_preview_df`
- `pathao_preview_source`
- `pathao_res_df`
- `pathao_vlink_df`
- `pathao_auto_process`
- `pathao_manual_items_df`
- `pathao_manual_desc`
- `inv_pathao_df` (Used when pushing allocations directly to Pathao from Inventory Distribution)
- `pilot_pathao_tracking_df` (Stores bulk-synced Pathao tracking data for the AI agent)

## 7. Operational Dashboard Rules
The operational dashboard has behavior that should not drift accidentally.

- `src/pages/dashboard_output.py`
  Owns the operational/integration flow for live dashboard rendering.
- `src/pages/dashboard_metrics.py`
  Owns the operational KPI strip.

Current KPI behavior:
- `Gross Items` must keep its previous-slot delta when comparison data exists.
- The operational KPI strip currently shows 4 cards: `Gross Items`, `Revenue`, `Orders`, and `Avg Basket` / `Oldest Order`.
- `NEXT DAY FORECAST` is not currently shown as a KPI card.

If you touch metric-card ordering or badge placement, verify that deltas still appear on the intended cards.

## 8. Pathao Processor Rules
`src/pages/pathao_orders.py` and `src/processing/order_processor.py` now contain a few important conventions.

### Source modes
The Pathao processor has two user-facing modes:
- `WooCommerce Processing`
  Pull only WooCommerce rows currently in `processing` status.
- `Upload / URL`
  Accept uploaded spreadsheets or URL-fetched files.

Do not silently mix the two modes in session state. `pathao_preview_source` is used to keep them separate.

### Item description logic
`src/processing/order_processor.py` is the source of truth for Pathao `ItemDesc` formatting.

Shared helpers:
- `build_item_description()`
- `normalize_manual_item_input()`
- `parse_manual_item_lines()`

These are reused by:
- grouped order processing
- the manual `Item Description Helper` tab

Do not duplicate item-description formatting logic elsewhere unless there is a strong reason.

### Address normalization logic
`RecipientAddress(*)` is intentionally synthesized from multiple parts:
- normalized street/address text
- matched area when available
- zone/thana
- resolved district/city

District resolution can come from:
- WooCommerce BD state codes like `BD-13`
- direct district names
- Pathao map inference from zone/city matches

The goal is a more complete `RecipientAddress(*)`, not just a raw street field dump.

### Bulk Status Tracking
The Pathao module includes an `Order Tracking` tab that allows bulk tracking via Consignment IDs.
- If auto-update is enabled, it uses the `Order ID` column to actively send `completed` statuses back to WooCommerce via API for delivered parcels.
- Ensure tracking files contain an `Order ID` or `Merchant Order ID` column for this auto-sync to function properly.

The **Data Pilot** also has a bulk sync feature that does not require a file upload; it uses the live WooCommerce data in session to find pending orders with consignment IDs and fetches their statuses.

## 9. Item Description Helper
The bulk order processor includes a second tab: `Item Description Helper`.

Purpose:
- let users paste raw item lines
- normalize and sort them
- aggregate duplicate entries
- produce a ready-to-copy `ItemDesc` string using the same formatting as the real Pathao processor

Supported manual patterns currently include forms like:
- `2x Oxford Shirt`
- `Oxford Shirt x2`
- `Oxford Shirt (2 pcs)`
- `Oxford Shirt | SKU123`

If you extend parsing, keep it backward compatible and route all output through the shared normalization helpers.

## 9.1. Data Pilot Rules
The Data Pilot (`data_pilot.py`) is a conversational AI workspace.

- **Global Data Pilot**: A mini-pilot interface is available globally in the sidebar, allowing quick operational queries without switching tabs.
- **Knowledge Base**: The AI agent grounds its answers in the data available in its "Data Context". This data is loaded from other tabs (Live Dashboard, Inventory, Pathao Processor) or uploaded directly.
- **Modern Tab Layout**: The main Data Pilot page is divided into "💬 Pilot Interface" (chat), "🧠 Knowledge Base" (data context previews), and "📑 Generated Reports" (saved AI executive summaries).
- **Report Generation**: Users can request executive summaries or reports. The agent will format these as markdown, and the UI will automatically save them to the "Generated Reports" tab for downloading.

- **Data Synchronization**:
    - **Manual Sync**: Users can click "Sync from WooCommerce" or "Sync Pathao Statuses" to load fresh data into the knowledge base.
    - **Smart Auto-Sync**: An optional toggle that automatically syncs data if it's older than 15 minutes before answering a query.
    - **Chat Command**: The agent recognizes commands like "sync now" to trigger a data refresh dynamically.

- **Dynamic Intent Routing**:
    - The agent uses an internal "NeuralBrain" to detect user intent.
    - **ML Forecasts**: Responds to questions about future sales.
    - **ML Anomalies**: Detects unusual spikes or dips in sales data.
    - **Pathao Live Tracking**: Automatically detects Pathao Consignment IDs (e.g., `DD12345`) in the chat, fetches the live status from the Pathao API, and includes it in the answer.
    - **Report Generation**: Detects when the user asks for a summary or report and flags it to save in the session state.


## 10. Known Technical Debt
- Some older docs still describe the project as `DEEN-BI` or `dashboard_v1`.
- `MORE_TOOLS` in `src/config/ui_config.py` is still not part of active routing.
- Some page modules still mix heavy business logic directly into UI renderers.
- There are still runtime-generated artifacts and snapshots in the repo, so expect a dirty worktree.

## 11. Recent Stability Improvements
- Fixed `list assignment index out of range` in Inventory Distribution by resetting dataframes and wrapping order-group logic in resilient `try...except` blocks.
- Added universal numeric/currency data sanitization (stripping non-numeric chars via regex) prior to `pd.to_numeric` to prevent silent `NaN` revenue/quantity drops.
- Added strict string-casting for categorical columns before Polars DataFrame conversion to prevent `MixedType` compute crashes.
- Prevented manual empty SKUs (filled with "0") from clustering entirely unrelated products together in inventory matching.
- Eliminated ghost UI previews by actively clearing `inv_*` session state variables on new uploads/URL fetches.
- Appended transaction IDs directly to Pathao `SpecialInstruction` and `ItemDesc` for 100% Prepaid (SSL/Bkash) orders.
- Integrated Pathao bulk-sheet generation directly into the Inventory Distribution page.
- **Mobile UI Fix (Apr 21, 2026):** Restored the cover photo (app banner image) visibility in mobile views by removing `display: none` from the `@media` query in `header.py`.
- **Pandas Type Safety:** Fixed `AttributeError: Can only use .dt accessor with datetimelike values` by ensuring explicit `pd.to_datetime` conversion and handling empty DataFrames in `src/processing/` and `src/state/insights.py`.
- **Stock Analytics Recovery:** Fixed `raw_qty` undefined error by replacing it with `total_qty` in recovery mode.
- **Data Integrity:** Replaced fake Association Rules (which used `np.random.rand()`) with actual co-occurrence calculation logic in the dashboard.
- **Performance Optimization:** Migrated WhatsApp Bulk Processing to use Polars (`pl.LazyFrame`) for significantly faster execution and lower memory footprint.
- **Data Pilot AI Agent**: Introduced a conversational AI agent (`data_pilot.py`) that can analyze and answer questions about all operational data.
- **Live Grounding & Intent Routing**: The Data Pilot can perform ML forecasts, detect anomalies, and dynamically track Pathao consignments from chat prompts.
- **Smart & Manual Sync**: Implemented multiple ways to keep the AI's knowledge base up-to-date, including manual buttons, a "stale data" auto-sync, and chat-based commands.
- **Pathao Bulk Status Sync & Export**: Added a feature to the Data Pilot to fetch live statuses for all pending Pathao orders, load them into the AI's context, and export them to Excel.
- **Global Data Pilot & Enhanced UI**: Upgraded the AI Data Pilot with a modern tabbed layout (Chat, Knowledge Base, Reports), multi-report generation, and a persistent global sidebar widget for instant access from any workspace.
- **Fuzzy Matching Integration:** Implemented `fuzzywuzzy` for resilient location detection (Thana/Area/Zone mapping).
- **UI/UX Overhaul (Terminal Theme):** Implemented glassmorphism metric cards, global fade-in animations, responsive mobile widget stacking, and Data Pilot terminal-themed chat bubbles via CSS injection.
- **Premium UI Polish:** Added glowing hover states for the "Launch DEEN BI" CTA, a prominent sidebar logo block, capsule-styled segmented controls with inset shadows, custom CSS-driven tooltips, and an active pill pulse animation.
- **Advanced Chart Grouping & Resilience:** Added intelligent "Others" aggregation for Pie/Donut charts (3% threshold) and dynamic layout scaling (`automargin=True`).
- **Robust Export Engine:** Created a unified Excel export system with auto-fitting column widths, multi-sheet consolidation, and safe NA dropping.
- **Graceful Error Handling:** Comprehensive adoption of `safe_render`, `safe_filter`, and `safe_column_access` via `src/utils/safe_ops.py` to prevent UI crashes.
- **Predictive Intelligence Upgrade:** Replaced mock mathematical forecasting with real Machine Learning models (XGBoost, Random Forest, ARIMA, Holt-Winters) utilizing Scikit-Learn and Statsmodels.
## 12. Development Guidance
- New workspace page:
  follow `DEVELOPMENT.md` for page creation, nav updates, routing, and reset registration.
- Defensive rendering:
  prefer `safe_render()` around page-level render boundaries.
- Shared logic:
  if a transformation is needed in more than one page, move it into `src/processing/` or `src/utils/`.
- Pathao changes:
  prefer editing shared helpers in `order_processor.py` before adding page-local formatting rules.
- Data sanitization:
  Always strip currency/text strings using `str.replace(r"[^\d.-]", "", regex=True)` before calling `pd.to_numeric` on quantities, prices, or amounts.

## 13. Execution & Testing
- Local app:
  `streamlit run app.py`
- Unit tests:
  `pytest tests/ -v`
- Coverage:
  `pytest tests/ --cov=src`

Practical note for shell validation:
- In some shell environments, importing real `streamlit` may hang.
- For pure processing checks, `py_compile` and focused stubbed tests are acceptable when full `pytest` is unreliable.

Secrets/config:
- keep `.streamlit/secrets.toml` updated for WooCommerce and Pathao
- use `src/config/settings.py` and `src/config/ui_config.py` patterns instead of hardcoding new secret reads in random modules

---
*End of blueprint. Keep this file aligned with actual behavior, not aspirational behavior.*
