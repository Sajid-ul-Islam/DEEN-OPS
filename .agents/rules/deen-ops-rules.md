# DEEN-OPS Workspace Agent Rules

These rules apply across all coding and refactoring sessions within the DEEN-OPS repository.

## 1. Unidirectional Dependency Rule
- `src/config` -> Leaf layer (no imports from other src packages).
- `src/utils` -> Generic utilities (no imports from `src/components`, `src/pages`, `src/services`).
- `src/services` -> Network I/O clients (WooCommerce, Pathao).
- `src/processing` -> Pure logic & business calculations (testable without Streamlit).
- `src/components` -> Reusable UI widgets & charts.
- `src/pages` -> Streamlit page controllers wiring everything together.

## 2. Temporal & Timezone Rule
- Bangladesh Time (UTC+6) is the single operational standard.
- Always use `bd_now()` and `bd_today()` from `src.config.constants`.
- Never use raw `datetime.now()` or `date.today()` in business calculations.

## 3. Shipped vs. Unfulfilled Order Invariant
- Only orders in `SHIPPED_STATUSES` (`completed`, `shipped`) count toward revenue/dispatch metrics.
- Reverted orders (e.g. changed from completed to `processing`, `on-hold`, `waiting`) must be immediately evicted from shipped totals and treated as active queue workload.

## 4. Verification Gate
Before declaring any task complete or committing:
1. `ruff check .`
2. `ruff format --check .`
3. `python -m compileall -q src app.py`
4. `python scripts/check_imports.py` (63/63 modules OK)
5. `pytest tests/ -q --disable-warnings` (432+ passed)
6. `python -c "import toml; toml.load('.streamlit/config.toml'); print('Streamlit config OK')"`
