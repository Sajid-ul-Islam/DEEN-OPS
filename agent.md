# DEEN-OPS / DEEN-BI Blueprint & AI Agent Guide

**To any AI Agent reading this file:** This is your central blueprint for the DEEN-OPS (also known as DEEN-BI or DEEN OPS Terminal) project. Read this completely before making architectural changes, modifying session states, or adding new features. 

---

## 1. App Motive & Identity
**DEEN OPS Terminal** is a high-performance, AI-powered operational command center for E-commerce. 
**Goal:** Optimize operations through real-time data storytelling, automated inventory management, courier integrations (Pathao), and LLM-assisted business intelligence.
**Target Experience:** The UI must feel like a premium "Command Center" (glassmorphism, radial gradients, dark mode, dynamic widgets). It should be visually striking, highly reliable, and provide actionable insights, not just raw data.

## 2. Architecture & File Structure
The project follows a strict layered architecture. **Never introduce circular imports.** Each layer only imports from the layers below it.

- `app.py`: The main entry point (auth, routing, main layout).
- `src/pages/`: Individual workspace tabs (e.g., Live Dashboard, Stock Analytics, Data Pilot).
- `src/components/`: Reusable, data-agnostic UI widgets (Header, Sidebar, Charts).
- `src/services/`: External API clients (WooCommerce, Pathao, LLM manager, Google Sheets).
- `src/processing/`: Core data transformation pipelines (Categorization, Forecasting, Data Parsing).
- `src/inventory/`: Inventory matching engine and logic.
- `src/utils/`: Stateless helpers (text processing, logging).
- `src/config/`: App settings, constants, and UI configurations.
- `_deprecated/`: **DO NOT USE.** This contains legacy code. Always read and write to `src/`.

## 3. Technology Stack
- **Frontend Framework:** Streamlit (with extensive custom CSS injected via `st.markdown`).
- **Data Engine:** Pandas & Polars (vectorized operations & lazy evaluation) & Plotly (charting).
- **AI Integrations:** Multi-provider LLM wrappers (OpenRouter, Gemini, Groq, Ollama) via `services/llm/`.
- **APIs:** WooCommerce REST, Pathao Courier API.

## 4. State Management (`st.session_state`)
The app heavily relies on Streamlit's session state to maintain data across reruns. 
**Agent Rule:** Never rename or delete an existing `st.session_state` key unless you update all references globally. 

*Common Key Prefixes:*
- `live_*`: WooCommerce live dashboard data.
- `stock_*`: Stock analytics and snapshot data.
- `pilot_*`: Data Pilot conversational AI state.
- `pathao_*`: Courier order states.
- `wc_*`: WooCommerce syncing and navigation modes.

## 7. Known Technical Debt & Performance
The following items are identified for future cleanup to maintain project health:
- **No-Op Functions:** `render_sidebar_branding()` in `src/components/sidebar.py` is currently a no-op. It processes base64 data but does not render anything per user request.
- **Unused Configs:** `MORE_TOOLS` in `src/config/ui_config.py` is defined but not utilized in routing.
- **Redundant Scripts:** Some scripts in `scripts/` might overlap with new `src/` modules (always verify before use).

## 8. Recent Stability Improvements (Fixed Bugs)
- **Mobile UI Fix (Apr 21, 2026):** Restored the cover photo (app banner image) visibility in mobile views by removing `display: none` from the `@media` query in `header.py`.
- **Pandas Type Safety:** Fixed `AttributeError: Can only use .dt accessor with datetimelike values` by ensuring explicit `pd.to_datetime` conversion and handling empty DataFrames in `src/processing/` and `src/state/insights.py`.
- **Stock Analytics Recovery:** Fixed `raw_qty` undefined error by replacing it with `total_qty` in recovery mode.
- **Data Integrity:** Replaced fake Association Rules (which used `np.random.rand()`) with actual co-occurrence calculation logic in the dashboard.
- **Performance Optimization:** Migrated WhatsApp Bulk Processing to use Polars (`pl.LazyFrame`) for significantly faster execution and lower memory footprint.
- **Fuzzy Matching Integration:** Implemented `fuzzywuzzy` for resilient location detection (Thana/Area/Zone mapping).

## 9. Development Roadmap & Best Practices
- **New Workspace Page:** Follow the 4-step guide in `DEVELOPMENT.md` (Create page -> Update Nav -> Add Routing -> Register Reset).
- **Premium Design First:** Always use curated color palettes and smooth transitions. Avoid default Streamlit "grey/red/blue" buttons; use `st.markdown` for custom-styled elements where possible.
- **Defensive Rendering:** Use `src/utils/safe_ops.py` `safe_render()` for page-level components to prevent one failing module from crashing the entire app.

## 10. Execution & Testing
- **Local Dev:** `streamlit run app.py`
- **Unit Tests:** `pytest tests/ -v`
- **Coverage:** `pytest tests/ --cov=src`
- **Secrets:** Keep `.streamlit/secrets.toml` updated with WooCommerce and Pathao credentials.

---
*End of Blueprint. Use this knowledge to build, debug, and scale DEEN-OPS.*
