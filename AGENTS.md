# AGENTS.md — Agent Operating Guidelines for DEEN-OPS Terminal

> **Target Audience**: AI Coding Assistants (Antigravity, Claude Code, Cursor, Copilot Workspace, Devin) and Human Contributors.  
> **Repository**: [DEEN-OPS Terminal](file:///h:/Repo/Order%20Process%20Automation) (AI-assisted enterprise operations workspace for WooCommerce, Pathao courier logistics, SIP POS stock reconciliation, and shift analytics).

---

## 1. Core Architecture & Strict Layer Separation

DEEN-OPS follows a strict **unidirectional dependency architecture**. Bypassing layers or introducing circular imports is strictly prohibited.

```
┌────────────────────────────────────────────────────────┐
│               app.py / src/app_bootstrap.py             │  Application Entrypoint & Router
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                       src/pages/                       │  Streamlit Page Controllers & Views
└─────────────┬────────────────────────────┬─────────────┘
              │                            │
┌─────────────▼──────────────┐ ┌───────────▼─────────────┐
│      src/components/       │ │     src/processing/     │  UI Widgets & Charts vs. Pure Logic
└─────────────┬──────────────┘ └───────────┬─────────────┘
              │                            │
┌─────────────▼──────────────┐ ┌───────────▼─────────────┐
│       src/services/        │ │       src/utils/        │  External APIs vs. Local Helpers
└─────────────┬──────────────┘ └───────────┬─────────────┘
              │                            │
┌─────────────▼────────────────────────────▼─────────────┐
│                       src/config/                      │  Constants, Schemas, Settings (Leaf)
└────────────────────────────────────────────────────────┘
```

### Layer Rules & Responsibilities

| Layer | Directory | Permitted Imports | Prohibited Imports | Responsibilities |
| :--- | :--- | :--- | :--- | :--- |
| **Config** | `src/config/` | Standard library, external packages | `src.pages`, `src.components`, `src.processing`, `src.services`, `src.utils` | Constants (`constants.py`), UI config (`ui_config.py`), secrets schema (`settings.py`). Leaf layer. |
| **Utils** | `src/utils/` | `src.config`, external packages | `src.pages`, `src.components`, `src.services` | Logging, text parsing, metric history snapshots, HTTP retry helpers, customer registry. No UI code. |
| **Services** | `src/services/` | `src.config`, `src.utils` | `src.pages`, `src.components`, `src.processing` | External network clients: WooCommerce REST API, Pathao Courier REST API, LLM connectors. Network I/O only. |
| **Processing**| `src/processing/`| `src.config`, `src.utils` | `src.pages`, `src.components` | Pure data processing, order transformation, filtering rules, forecasting, SIP stock conversions. Must be deterministic and testable without Streamlit. |
| **Components**| `src/components/`| `src.config`, `src.utils`, `src.processing` | `src.pages` | Reusable Streamlit UI widgets, Plotly chart builders, SVG sparklines, KPI cards, tables. |
| **Pages** | `src/pages/` | All layers below | None (Top-level views) | Streamlit page controllers that bind session state, invoke services/processing, and call components. |

---

## 2. Domain Rules & Critical Invariants

### A. Timezone & Operational Date Standard
- **Always use Bangladesh Time (BDT, UTC+6)**:
  ```python
  from src.config.constants import bd_now, bd_today
  now = bd_now()      # datetime in Asia/Dhaka
  today = bd_today()  # date in Asia/Dhaka
  ```
- **Never use `datetime.now()` or `date.today()`** directly for business logic, as server clocks in Streamlit Cloud / GitHub Actions run in UTC (6 hours behind Bangladesh).

### B. Order Lifecycle & Shipped Tracking Rules
- **Strict Status Whitelist**: Only orders with statuses in `SHIPPED_STATUSES` (`completed`, `shipped`) count as sales/revenue.
- **Protection Against Status Reversions**:
  - If an order was previously marked shipped/completed but its status in WooCommerce is changed back to `on-hold`, `waiting`, `pending`, or `processing`, it **must immediately be purged from shipped metrics** and placed back into the active queue.
  - The presence of a Pathao tracking consignment ID does NOT override the live WooCommerce order status.
- **Date Modified vs. Date Created**:
  - Shipped orders are scoped by **Order Date Modified** (`mod_dt_parsed`), falling back to **Order Date** (`dt_parsed`).
  - Active/processing orders are scoped by **Order Date** (`dt_parsed`).

### C. Metric History & 30-Day Snapshots
- Located in `src/utils/metric_history.py`.
- **Last-Write-Wins Rule**: Repeated calls to `save_shift_snapshot` on the same calendar day overwrite `daily_revenue`, `daily_orders`, and `daily_qty` with the latest totals. They must **never be summed across appends** to prevent multi-million double-counting anomalies.
- Snapshots are stored under `resources/metric_snapshots/YYYY-MM-DD.json`.

### D. Session State Architecture
- Unified full dataset is stored in `st.session_state["wc_full_df"]`.
- Operational partitions:
  - `st.session_state["wc_curr_df"]`: Today's operational shift.
  - `st.session_state["wc_prev_df"]`: Previous working day's shift.
  - `st.session_state["wc_backlog_df"]`: Unresolved queue orders across all dates.
- Fallback Rule: Always inspect `wc_full_df` if partitioned dataframes are empty.

---

## 3. Mandatory Quality Gates & Verification Workflow

Before completing any task or committing changes, you **must run and pass all 6 checks**:

```powershell
# 1. Linting (Ruff)
.venv\Scripts\ruff.exe check .

# 2. Code Formatting (Ruff)
.venv\Scripts\ruff.exe format --check .

# 3. Python Compilation (Syntax verification)
.venv\Scripts\python.exe -m compileall -q src app.py

# 4. Strict 63-Module Import Verification
$env:PYTHONPATH="."
.venv\Scripts\python.exe scripts/check_imports.py

# 5. Full Unit Test Suite (432+ tests)
$env:PYTHONPATH="."
.venv\Scripts\pytest.exe tests/ -q --disable-warnings

# 6. Streamlit Config Validation
.venv\Scripts\python.exe -c "import toml; toml.load('.streamlit/config.toml'); print('Streamlit config OK')"
```

*(On Linux / macOS bash, replace `.venv\Scripts\` with `.venv/bin/` and use `export PYTHONPATH="."`)*.

---

## 4. Coding Conventions & Best Practices

1. **Ruff as Single Source of Truth for Linting & Formatting**:
   - Line length: 88 characters.
   - Do not disable rules globally without explicit justification.
   - If an import is conditionally needed after `sys.path` modification, use `# noqa: E402`.
2. **Defensive DataFrames**:
   - Always check for empty DataFrames before accessing columns (`if df is not None and not df.empty`).
   - Use `safe_coerce_datetime_naive(series)` for parsing timestamps to avoid timezone mismatch warnings.
3. **No Hardcoded Secrets or Credentials**:
   - Never commit API keys, store passwords, or credentials.
   - All secrets belong in `.streamlit/secrets.toml` or environment variables documented in `.env.example`.
4. **Preserve Documentation Integrity**:
   - Preserve existing docstrings, test invariants, and comments unrelated to your changes.
5. **Git Commit Messages**:
   - Follow Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
