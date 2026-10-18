# DEEN OPS Terminal

> **AI-assisted enterprise operations workspace for WooCommerce, multi-courier logistics (Pathao & Steadfast), and shift analytics workflows.**

---

## 🚀 Key Highlights

- **Live Operational Dashboard:**
  - Real-time shift tracking across **Today**, **Prev**, and **Backlog** operational windows.
  - Interactive KPI cards for **Gross Items**, **Actual Net Revenue** (with consolidated cashback breakdown), **Orders**, **Basket Size (AOV)**, and **Customer Mix**.
  - Integrated 36-hour hourly trend sparklines and 7-day new-customer acquisition curves with cubic Bézier smoothing and adaptive theme styling.
  - Shift Targets with goal progress bars, 30-Day snapshot history charts, and 1-click **Shift Handover Report** generation.
- **Strict Order Lifecycle & Shipped Tracking:**
  - Strict status whitelist enforcement ensuring only confirmed/completed orders count toward dispatch and revenue metrics.
  - **Authoritative Date Completed Precedence**: WooCommerce immutable `date_completed` timestamp is prioritized over `date_modified`.
  - Automatic protection against status reversions: orders changed back to `on-hold`, `waiting`, `pending`, or `processing` are immediately purged from shipped metrics.
  - Persistent disk-cached shipped history with automatic cache purging for reverted orders.
- **Multi-Courier Logistics & Dispatch Suite:**
  - Native integration with **Pathao Courier REST API** and **Steadfast API**.
  - Live consignment tracking, bulk label generation, and automated delivery health audits.
  - Automated duplicate dispatch prevention via local dispatch ledger.
- **Product Listing & SKU Breakdown:**
  - Granular item extraction, variant distribution, and inventory forecasting.
  - Dynamic export to multi-sheet formatted Excel reports.
- **Delivery Parser Engine:**
  - Universal multi-courier text & Excel parser for Bangladeshi customer addresses and order items.
  - Phone number normalization (11-digit BD standard: `01XXXXXXXXX`) and delivery zone classification.
- **Return Analytics Engine:**
  - Concurrently reconciles returned parcels against live WooCommerce order statuses and courier delivery logs to flag prepaid refund risks and status mismatches.
- **Lifetime Customer Identity Registry:**
  - Multi-tier identity matching (Phone ➔ Email ➔ Name/City) to calculate accurate new vs. returning customer retention rates.
- **Data Pilot AI Assistant:**
  - Natural-language business intelligence queries powered by multi-provider LLM routing (OpenRouter, Google Gemini, Groq, Ollama, Hugging Face).
- **Enterprise Resilience:**
  - Shared exponential backoff for external APIs, configuration validation ([src/config/secrets_schema.json](src/config/secrets_schema.json)), and container healthcheck support.

---

## 🛠️ Tech Stack

- **Frontend / UI:** Streamlit, Vanilla CSS, Plotly Express & Graph Objects, Pure SVG Sparklines
- **Data Engine:** Python 3.10+, pandas, Polars, numpy, DuckDB
- **Integrations:** WooCommerce REST API, Pathao Courier REST API, Steadfast Courier API
- **AI & LLM:** OpenRouter, Google Gemini, Groq, Ollama, Hugging Face
- **Quality & Testing:** pytest (375+ tests), Ruff, compileall, pre-commit

---

## ⚡ Quick Start

### 1. Clone & Set Up Environment

```bash
git clone https://github.com/Sajid-ul-Islam/DEEN-OPS.git
cd DEEN-OPS
python -m venv .venv
.venv\Scripts\activate       # On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pre-commit install
```

### 2. Run the Application

```bash
streamlit run app.py
```

*Note: Authentication fails closed by default. For local offline development, set `DEEN_OPS_ALLOW_UNAUTHENTICATED=true` before running.*

---

## ⚙️ Configuration

Configuration is managed via `.streamlit/secrets.toml` with environment variable fallbacks. The schema is validated at startup via [src/config/secrets_schema.json](src/config/secrets_schema.json).

Example `.streamlit/secrets.toml`:

```toml
[woocommerce]
store_url = "https://your-store.com"
consumer_key = "ck_..."
consumer_secret = "cs_..."

[pathao]
base_url = "https://courier-api.pathao.com"
client_id = "..."
client_secret = "..."
username = "..."
password = "..."

[courier.steadfast]
api_key = "..."
secret_key = "..."

[llm]
openrouter_key = "..."
gemini_key = "..."
groq_key = "..."

[auth]
redirect_uri = "http://localhost:8501"
cookie_secret = "..."

[auth.google]
client_id = "..."
client_secret = "..."
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Supported Environment Variable Fallbacks:

- **WooCommerce:** `WC_URL`, `WC_KEY`, `WC_SECRET`
- **Pathao:** `PATHAO_BASE_URL`, `PATHAO_CLIENT_ID`, `PATHAO_CLIENT_SECRET`, `PATHAO_USERNAME`, `PATHAO_PASSWORD`
- **LLM APIs:** `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `HF_API_KEY`
- **Resilience:** `API_RETRY_MAX_ATTEMPTS`, `API_BACKOFF_FACTOR_SECONDS`, `API_BACKOFF_MAX_SECONDS`

---

## 📂 Project Structure

```text
DEEN-OPS/
├── app.py                      # Application entrypoint & sidebar router
├── requirements.txt            # Unified project dependencies (runtime + dev)
├── resources/                  # Customer registry, shipped history, metric snapshots
│   ├── customer_registry.json
│   ├── shipped_history.json
│   └── metric_snapshots/       # YYYY-MM-DD daily operational snapshots
├── scripts/
│   ├── check_imports.py        # Strict 65-module import verification
│   ├── check_requirements.py   # AST dependency usage validation
│   ├── export_todays_shipped.py
│   └── healthcheck.py          # Docker container health probe
├── src/
│   ├── app_bootstrap.py        # Session state bootstrap & page routing
│   ├── components/             # Reusable UI widgets, KPI cards, charts, svg sparklines
│   ├── config/                 # Constants, UI config, settings, secrets schema
│   ├── pages/                  # Page controllers (Live Dashboard, Sales Ingestion, Delivery Parser, Return Analytics, Product Listing)
│   ├── processing/             # Pure business logic: orders facade, forecasting, returns, categorization
│   │   └── orders/             # Modular order processing (date_utils, status_filters, aggregators, briefing, product)
│   ├── services/               # External clients: WooCommerce, Pathao, Courier (Steadfast), Excel Exporter
│   ├── state/                  # Session state persistence
│   └── utils/                  # Safe ops, logging, metric history, customer registry
├── tests/                      # Full unit test suite (375+ tests)
└── tools/
    └── excel_pathao_converter/ # Standalone Excel to Pathao bulk upload converter
```

---

## 🧪 Testing & Quality Gates

DEEN-OPS enforces **6 mandatory quality gates** before every commit or release:

```powershell
# 1. Linting (Ruff)
py -m ruff check .

# 2. Code Formatting (Ruff)
py -m ruff format --check .

# 3. Python Compilation (Syntax verification)
py -m compileall -q src app.py

# 4. Strict 65-Module Import Verification
$env:PYTHONPATH="."
py scripts/check_imports.py

# 5. Full Unit Test Suite (375+ tests)
$env:PYTHONPATH="."
py -m pytest tests/ -q --disable-warnings

# 6. Streamlit Config Validation
py -c "import toml; toml.load('.streamlit/config.toml'); print('Streamlit config OK')"
```

---

## 📚 Technical Reference & Guidelines

For in-depth architectural specifications and coding standards, refer to:

- 🏗️ **[System Architecture Guide (ARCHITECTURE.md)](ARCHITECTURE.md)**: Layered architecture, unidirectional dependencies, data pipelines, and state management.
- 🤖 **[Agent Operating Guidelines (AGENTS.md)](AGENTS.md)**: Critical domain invariants, timezone standards, order lifecycle rules, and quality gates for AI assistants and contributors.
- 🤝 **[Contributor Guide (CONTRIBUTING.md)](CONTRIBUTING.md)**: Development workflow, branching conventions, and quality checklist.
- 📦 **[Pathao Converter Tool (tools/excel_pathao_converter/README.md)](tools/excel_pathao_converter/README.md)**: Standalone desktop converter and Excel VBA add-in.
