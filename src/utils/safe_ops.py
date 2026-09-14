"""Graceful failure utilities for Streamlit rendering and data filtering."""

from __future__ import annotations

from typing import Callable, TypeVar

import pandas as pd
import streamlit as st

from src.utils.logging import log_error

T = TypeVar("T")


def safe_render(
    render_fn: Callable[[], T],
    fallback_msg: str = "Section unavailable.",
) -> T | None:
    """Execute a rendering function with graceful failure.

    On exception, displays a warning instead of crashing the page.

    Args:
        render_fn: Zero-argument callable that renders a UI section.
        fallback_msg: Message shown if the render function fails.

    Returns:
        The return value of render_fn, or None on failure.
    """
    # Defensively support inverted argument order: safe_render("msg", callable)
    if not callable(render_fn) and callable(fallback_msg):
        render_fn, fallback_msg = fallback_msg, str(render_fn)

    try:
        return render_fn()
    except Exception as e:
        try:
            log_error(e, context="safe_render", details={"fallback_msg": fallback_msg})
        except Exception:
            pass
        st.warning(f"{fallback_msg} Error: {e}")
        return None


def safe_filter(
    df: pd.DataFrame,
    filter_fn: Callable[[pd.DataFrame], pd.DataFrame],
    filter_name: str = "filter",
) -> pd.DataFrame:
    """Apply a filter function safely.

    On failure or empty result, returns the original DataFrame with a warning.

    Args:
        df: Input DataFrame to filter.
        filter_fn: Callable that takes a DataFrame and returns a filtered DataFrame.
        filter_name: Human-readable name for the filter (shown in warnings).

    Returns:
        Filtered DataFrame, or original if the filter fails.
    """
    try:
        result = filter_fn(df)
        if result is None or (isinstance(result, pd.DataFrame) and result.empty):
            st.warning(f"Filter '{filter_name}' returned no results. Showing all data.")
            return df
        return result
    except Exception as e:
        st.warning(f"Filter '{filter_name}' failed: {e}. Showing unfiltered data.")
        return df
