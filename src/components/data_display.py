import streamlit as st
import pandas as pd

def render_numbered_dataframe(data, *args, **kwargs):
    """Renders a dataframe with 1-indexed row numbers safely."""
    try:
        if isinstance(data, (pd.DataFrame, pd.Series)):
            d = data.copy()
            if len(d) > 0:
                d.index = range(1, len(d) + 1)
            return st.dataframe(d, *args, **kwargs)
    except Exception:
        pass
    return st.dataframe(data, *args, **kwargs)