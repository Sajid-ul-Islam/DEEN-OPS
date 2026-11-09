"""Unit tests for dispatch_export_view component."""

from unittest.mock import patch
import pandas as pd

from src.components.dashboard.dispatch_export_view import render_dispatch_export


def test_render_dispatch_export_empty_df():
    # Should safely return without error when dataframe is empty
    with patch("streamlit.session_state", {}):
        render_dispatch_export(raw_df=pd.DataFrame())


def test_render_dispatch_export_none_df():
    with patch("streamlit.session_state", {}):
        render_dispatch_export(raw_df=None)
