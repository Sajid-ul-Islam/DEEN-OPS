# Error Handling Guide

This document describes the graceful-failure patterns used throughout DEEN OPS Terminal. The core principle: **show warnings, don't crash, fall back gracefully**.

---

## Safe Operation Utilities (`src/utils/safe_ops.py`)

Three composable wrappers that catch exceptions and degrade gracefully instead of crashing the Streamlit page.

### `safe_filter(df, filter_fn, filter_name)`

Applies a filter function to a DataFrame. If the filter throws an exception or returns an empty result, the original unfiltered DataFrame is returned and a warning toast is shown.

**Signature:**
```python
def safe_filter(
    df: pd.DataFrame,
    filter_fn: Callable[[pd.DataFrame], pd.DataFrame],
    filter_name: str = "filter",
) -> pd.DataFrame
```

**Behavior on failure:**
- Exception in `filter_fn`: returns original `df`, shows `st.warning("Filter '<name>' failed: <error>. Showing unfiltered data.")`
- Empty or None result: returns original `df`, shows `st.warning("Filter '<name>' returned no results. Showing all data.")`

**When to use:** Wrap any user-driven filter (multiselect, date range, slider) so that malformed data or edge cases never blank out the page.

**Where used:**
- `src/components/smart_filters.py` -- wraps every auto-detected filter (date, categorical, numeric)
- `src/pages/stock_analytics.py` -- wraps Category/Fit, Item, Size, and stock-level filters

---

### `safe_column_access(df, col, default)`

Returns a DataFrame column if it exists, otherwise returns a Series filled with the default value.

**Signature:**
```python
def safe_column_access(
    df: pd.DataFrame, col: str, default: Any = "N/A"
) -> pd.Series
```

**Behavior when column is missing:**
- Returns `pd.Series([default] * len(df), index=df.index, name=col)`
- Shows `st.warning("Column '<col>' not found. Using default value.")`

**When to use:** When accessing columns that may or may not exist depending on the data source (e.g., "SKU" is present in WooCommerce data but not in all uploaded CSVs).

---

### `safe_render(render_fn, fallback_msg)`

Executes a zero-argument rendering callable inside a try/except. On failure, shows a warning message instead of crashing.

**Signature:**
```python
def safe_render(
    render_fn: Callable[[], T],
    fallback_msg: str = "Section unavailable.",
) -> T | None
```

**Behavior on exception:**
- Shows `st.warning("<fallback_msg> Error: <exception>")`
- Returns `None`

**When to use:** Wrap entire dashboard sections (chart blocks, intelligence panels) so that a failure in one section does not take down the whole page.

**Where used:**
- `src/pages/dashboard_output.py` -- wraps Market Basket Intelligence and ML Forecasting sections
- `src/pages/stock_analytics.py` -- wraps the stock KPI summary and the full stock body renderer
- `src/pages/live_dashboard.py` -- wraps the main live dashboard render call

---

## Data Pipeline Resilience Patterns

### `find_columns()` -- Partial Results on Failure

**Location:** `src/processing/column_detection.py`

`find_columns()` detects logical column roles (name, cost, qty, date, order_id, phone, sku) by matching against known aliases. The function is designed to return **partial results** rather than failing entirely:

- It iterates over each logical column independently
- If one column detection fails (e.g., no date column found), the others still succeed
- The returned dict may have fewer keys than expected; callers must check for the presence of each key before using it
- Errors during individual column detection are logged via `log_system_event()` but do not raise exceptions

This means a dataset missing a "date" column can still be processed for quantity/revenue analytics -- the date-dependent features simply skip.

### `prepare_granular_data()` -- Date Parsing Resilience

**Location:** `src/processing/data_processing.py`

Date parsing in `prepare_granular_data()` is wrapped in a multi-level try/except:

1. **Primary path:** `pd.to_datetime(df[date_col], errors="coerce")` -- invalid dates become NaT rather than raising
2. **Valid-date check:** If all dates parse as NaT, a `DATE_PARSE_WARN` is logged and processing continues without date filtering
3. **Outer catch:** If the entire date block throws (e.g., column dtype issue), a `DATE_PARSE_ERROR` is logged, and a fallback timeframe string is derived from the first non-null raw value
4. **Timezone normalization:** `tz_localize(None)` is applied to timezone-aware dates so Streamlit date widgets don't break

The function never crashes on bad date data. Downstream features that require dates (time-series charts, date range filters) gracefully degrade when dates are unavailable.

---

## General Guidance

1. **Show warnings, don't crash.** Use `st.warning()` for recoverable issues. Reserve `st.error()` for truly blocking failures (e.g., API authentication failure). Never let an unhandled exception reach the user.

2. **Fall back to the broader dataset.** When a filter or slice fails, show all data rather than nothing. An overly broad view is more useful than a blank page.

3. **Log everything.** Use `log_system_event()` from `src/utils/logging.py` for all error/warning events. This populates the System Logs viewer in the sidebar.

4. **Wrap sections, not individual widgets.** Use `safe_render()` at the section level (e.g., "Market Basket Intelligence") rather than wrapping every single Streamlit call. This keeps code readable while still isolating failures.

5. **Check column existence before access.** Use `"col" in df.columns` or `safe_column_access()` rather than bare `df["col"]` when the column may not exist. This is especially important in `dashboard_output.py` and `stock_analytics.py` where data sources vary.

6. **Partial results are acceptable.** Functions like `find_columns()` and `prepare_granular_data()` are designed to return whatever they can compute. Callers should handle missing keys/columns rather than expecting a complete result.

7. **Silent skip for non-critical UI.** The live banner (`src/components/live_banner.py`) catches all exceptions silently because its failure should never interfere with the main page. This is the exception to the "show warnings" rule -- use it only for truly optional, non-interactive elements.

---

## External API Rate Limiting

When working on external integrations, treat rate limiting as a first-class failure mode.

1. **Prefer cached or snapshot-backed reads.** WooCommerce stock and sales sync paths already cache results for short windows. Avoid replacing these with uncached polling loops.

2. **Bound concurrency intentionally.** The WooCommerce fetchers use `ThreadPoolExecutor` with explicit worker caps. If you raise those limits, document why and verify the upstream API can tolerate the change.

3. **Fail soft on bursty operations.** Bulk Pathao status checks and customer-history lookups should return partial results or user-facing warnings instead of retrying indefinitely.

4. **Use least-privilege credentials.** Production API keys should be scoped to the minimum access needed. For WooCommerce, prefer read-only keys for dashboards and analytics jobs when write access is unnecessary.

5. **Document retry expectations.** If an integration adds backoff, quotas, or daily caps, capture the operator-facing behavior in code comments or the service module docstring so rate-limit responses are not mistaken for generic outages.
