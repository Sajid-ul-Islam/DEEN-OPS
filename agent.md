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
- `_deprecated/`
  Archived legacy code. Do not build new logic here.

## 3. Technology Stack
- Frontend: Streamlit with heavy custom CSS injection.
- Data: Pandas and Polars.
- Charts: Plotly.
- AI: multi-provider LLM routing.
- APIs: WooCommerce REST API and Pathao Courier API.

## 4. Session State Rules
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

## 5. Operational Dashboard Rules
The operational dashboard has behavior that should not drift accidentally.

- `src/pages/dashboard_output.py`
  Owns the operational/integration flow for live dashboard rendering.
- `src/pages/dashboard_metrics.py`
  Owns the operational KPI strip.

Current KPI behavior:
- `Gross Items` must keep its previous-slot delta when comparison data exists.
- `Avg Lead` is shown on the `NEXT DAY FORECAST` card, not on `Gross Items`.
- `NEXT DAY FORECAST` remains in the fifth slot of the KPI strip.

If you touch metric-card ordering or badge placement, verify that deltas still appear on the intended cards.

## 6. Pathao Processor Rules
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

## 7. Item Description Helper
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

## 8. Known Technical Debt
- Some older docs still describe the project as `DEEN-BI` or `dashboard_v1`.
- `MORE_TOOLS` in `src/config/ui_config.py` is still not part of active routing.
- Some page modules still mix heavy business logic directly into UI renderers.
- There are still runtime-generated artifacts and snapshots in the repo, so expect a dirty worktree.

## 9. Recent Stability Improvements
- Fixed the operational dashboard crash caused by unbound `status_col_m` / `status_col_c` in `dashboard_output.py`.
- Restored `Gross Items` comparison delta visibility by moving `Avg Lead` off that card.
- Added explicit Pathao source selection between WooCommerce processing data and upload/URL input.
- Added the `Item Description Helper` tab to the Pathao page.
- Centralized Pathao item-description normalization so manual and grouped-order flows use the same formatter.
- Improved Pathao `RecipientAddress(*)` generation with normalized zone and district synthesis.

## 10. Development Guidance
- New workspace page:
  follow `DEVELOPMENT.md` for page creation, nav updates, routing, and reset registration.
- Defensive rendering:
  prefer `safe_render()` around page-level render boundaries.
- Shared logic:
  if a transformation is needed in more than one page, move it into `src/processing/` or `src/utils/`.
- Pathao changes:
  prefer editing shared helpers in `order_processor.py` before adding page-local formatting rules.

## 11. Execution & Testing
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
