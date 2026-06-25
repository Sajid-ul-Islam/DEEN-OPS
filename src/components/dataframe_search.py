import streamlit as st
import pandas as pd


def render_dataframe_search(
    df: pd.DataFrame,
    key_prefix: str = "search",
    height: int = 400,
) -> pd.DataFrame:
    """Renders a text search input above a dataframe. Returns filtered copy."""
    if df is None or df.empty:
        return df

    search_term = st.text_input(
        "🔍 Search",
        placeholder="Type to filter across all columns...",
        key=f"{key_prefix}_search_input",
        label_visibility="collapsed",
    )

    if search_term:
        mask = df.astype(str).apply(
            lambda row: row.str.contains(search_term, case=False, na=False).any(),
            axis=1,
        )
        filtered = df[mask]
        if len(filtered) < len(df):
            st.caption(f"Showing {len(filtered)} of {len(df)} rows")
        return filtered

    return df
