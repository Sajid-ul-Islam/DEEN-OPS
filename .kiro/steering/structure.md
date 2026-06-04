# Project Structure

```
DEEN-OPS/
├── app.py                          # Main entry point with auth, routing, layout
├── assets/                         # Static assets (images, CSS)
├── data/                           # Runtime data (logs, session state, feedback)
├── resources/                      # Reference data (snapshots, maps, CSVs)
├── scripts/                        # Utility scripts (healthcheck, requirements)
├── BackEnd/cache/                  # Local data snapshots (orders, operations DB)
├── src/
│   ├── components/                 # Reusable UI components (header, footer, widgets)
│   ├── config/                     # Configuration, secrets, constants, UI config
│   ├── inventory/                  # Inventory core logic (core.py, region files)
│   ├── pages/                      # Streamlit pages (dashboard, Pathao, WhatsApp, etc.)
│   ├── processing/                 # Data transformation (data_processing, categorization)
│   ├── services/                   # External API clients (WooCommerce, Pathao, LLM)
│   ├── state/                      # Session state persistence
│   ├── utils/                      # Shared utilities (logging, text, file_io, safe_ops)
│   └── __init__.py
├── tests/                          # Unit and integration tests
├── requirements/                   # Dependency files (base, ai, integrations, dev)
├── requirements.txt                # Runtime dependencies
├── requirements_dev.txt            # Runtime + dev dependencies
├── requirements.lock               # Pinned transitive dependencies
├── Makefile                        # Build targets (run, test, format, audit)
├── .kiro/                          # Kiro configuration
│   ├── hooks/                      # Agent hooks
│   ├── skills/                     # Kiro skills
│   └── steering/                   # This directory (steering rules)
├── .streamlit/                     # Streamlit config (config.toml, secrets.toml)
├── .devcontainer/                  # VS Code devcontainer configuration
├── .github/workflows/              # CI/CD workflows
└── Dockerfile                      # Container image definition
```

## Import Rules

- **Layered architecture**: Each layer imports only from layers below or same level
- **No circular imports**: Enforced by import structure
- **Lazy imports in app.py**: Bootstrap resilience on cloud

## Page Structure

Each page in `src/pages/` exposes a single `render_*` function as its entry point.

Pages register in `src/config/ui_config.py` and route in `app.py`.

## State Management

- All `st.session_state` keys are preserved from original codebase
- Keys grouped by prefix: `live_*`, `manual_*`, `pathao_*`, `wp_*`, `inv_*`, `parser_*`, `stock_*`, `pilot_*`
- Session state persisted to `data/session_state.json`