"""Unit tests for Data Pilot page rendering and error regression."""

from __future__ import annotations

import pandas as pd
from streamlit.testing.v1 import AppTest


def test_data_pilot_page_renders_without_unbound_local_error(tmp_path):
    """Ensure Data Pilot page renders cleanly without 'prompt' UnboundLocalError."""
    script_content = """import streamlit as st
from src.pages.data_pilot import render_ai_pilot_page

render_ai_pilot_page()
"""
    test_file = tmp_path / "test_pilot_render.py"
    test_file.write_text(script_content, encoding="utf-8")

    at = AppTest.from_file(str(test_file))
    at.session_state["snapshot_loaded"] = True
    at.session_state["wc_curr_df"] = pd.DataFrame({"order_id": [1, 2]})
    at.run(timeout=15)

    # Verify no exceptions occurred during execution
    assert not at.exception, f"Data Pilot page raised exception: {at.exception}"
    # Verify title or header is present
    assert any("DATA PILOT" in str(elem.value) for elem in at.markdown)
