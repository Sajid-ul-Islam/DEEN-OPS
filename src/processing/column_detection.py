import streamlit as st
import pandas as pd

from src.utils.logging import log_system_event


@st.cache_data(show_spinner=False)
def find_columns(df: pd.DataFrame) -> dict[str, str]:
    """Detects primary columns using exact and then partial matching.

    Returns partial results on failure instead of an empty dict, logging
    any errors encountered during detection.

    Args:
        df: Input DataFrame to detect columns in.

    Returns:
        Dict mapping logical names (name, cost, qty, date, order_id, phone)
        to actual column names found in the DataFrame.
    """
    mapping = {
        "name": [
            "item name",
            "product name",
            "product",
            "item",
            "title",
            "description",
            "name",
        ],
        "cost": [
            "item cost",
            "price",
            "unit price",
            "cost",
            "rate",
            "mrp",
            "selling price",
        ],
        "qty": ["quantity", "qty", "units", "sold", "count", "total quantity"],
        "date": ["date", "order date", "month", "time", "created at"],
        "order_id": [
            "order id",
            "order #",
            "invoice number",
            "invoice #",
            "order number",
            "transaction id",
            "id",
        ],
        "phone": [
            "phone",
            "contact",
            "mobile",
            "cell",
            "phone number",
            "customer phone",
        ],
    }

    found = {}
    try:
        actual_cols = [str(c).strip() for c in df.columns]
        lower_cols = [c.lower() for c in actual_cols]

        for key, aliases in mapping.items():
            for alias in aliases:
                if alias in lower_cols:
                    idx = lower_cols.index(alias)
                    found[key] = actual_cols[idx]
                    break

        for key, aliases in mapping.items():
            if key not in found:
                for col, l_col in zip(actual_cols, lower_cols):
                    if any(alias in l_col for alias in aliases):
                        found[key] = col
                        break
    except Exception as e:
        log_system_event("COLUMN_DETECT_ERROR", f"Partial detection returned {len(found)} columns: {e}")

    return found


@st.cache_data(show_spinner=False)
def scrub_raw_dataframe(df):
    """Filters out dashboard analytics, empty rows, and summary tables from raw exports."""
    if df is None or df.empty:
        return df

    # 1. Drop completely empty rows
    df = df.dropna(how="all")

    # 2. Heuristic: Sparsity Check
    # Keep rows that have at least 30% of the columns filled
    min_threshold = max(1, int(len(df.columns) * 0.3))
    df = df.dropna(thresh=min_threshold)

    # 3. Optimized Summary Filter (Avoid stacking)
    # Target common text columns instead of the entire dataframe
    summary_keywords = ["total", "grand total", "summary", "analytics", "chart", "metric"]
    pattern = "|".join(summary_keywords)

    # Check specifically for Order Number or ID being 'Total' or similar
    # If we find a column that looks like an ID, use it as a primary filter
    id_cols = [c for c in df.columns if any(k in c.lower() for k in ["id", "number", "invoice", "#"])]
    if id_cols:
        col = id_cols[0]
        df = df[~df[col].astype(str).str.lower().str.contains(pattern, na=False)]

    return df


def classify_columns(df: pd.DataFrame) -> dict[str, str]:
    """Classify all DataFrame columns by data type for smart filtering.

    This is a thin wrapper that delegates to
    ``src.components.smart_filters.detect_filterable_columns`` so the
    detection logic lives in one place while remaining accessible from the
    processing layer.

    Args:
        df: DataFrame to classify.

    Returns:
        Dict mapping column names to 'date', 'categorical', or 'numeric'.
    """
    from src.components.smart_filters import detect_filterable_columns
    return detect_filterable_columns(df)
