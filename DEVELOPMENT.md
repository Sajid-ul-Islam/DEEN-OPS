# Development Guide

## Setup

```bash
pip install -r requirements.txt
pip install -r requirements_dev.txt
pre-commit install
streamlit run app.py
```

## Configuration

- Put local secrets in `.streamlit/secrets.toml`
- Use environment variables when running in containers or CI
- Keep new secret keys aligned with [src/config/secrets_schema.json](src/config/secrets_schema.json)
- Load integration config through `src/config/settings.py`, not `src/config/ui_config.py`

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing
```

## Code Organization Rules

- Pages orchestrate UI and state, but do not own API client logic
- Services handle external integrations
- Processing modules stay focused on data transformation
- Shared configuration and secret lookup live in `src/config/`
- Use `src/utils/logging.py` for operational logging and failure capture

## Adding a New Workspace Page

1. Create `src/pages/your_page.py` with a single `render_*` entry point.
2. Register the nav label in [src/config/ui_config.py](src/config/ui_config.py).
3. Route it in [app.py](app.py).
4. Add tests for any non-trivial transformation or integration logic.

## Adding a New Integration

1. Create a module under `src/services/your_service/`.
2. Add the config contract to [src/config/secrets_schema.json](src/config/secrets_schema.json) if secrets are required.
3. Resolve credentials via `src/config/settings.py`.
4. Document rate limits, failure modes, and manual recovery steps.

## Local Workflow

- Run `pre-commit run --all-files` before opening a PR
- Keep changes scoped; do not edit `_deprecated/` unless you are explicitly cleaning it up
- Leave unrelated worktree changes untouched
- Prefer adding tests for config, processing, and service behavior changes

## Debugging

- System Logs: sidebar `Maintenance & Settings > System Logs`
- Error log file: `data/error_logs.json`
- Healthcheck script: [scripts/healthcheck.py](scripts/healthcheck.py)
- Config issues: sidebar `Maintenance & Settings > Configuration Health`
