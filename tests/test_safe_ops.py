"""Unit tests for src/utils/safe_ops.py rendering and filtering guards."""

from unittest.mock import MagicMock, patch
import pandas as pd
from src.utils.safe_ops import safe_render, safe_filter


def test_safe_render_standard_call():
    fn = MagicMock(return_value=42)
    result = safe_render(fn, fallback_msg="Failed to render")
    assert result == 42
    fn.assert_called_once()


def test_safe_render_inverted_arguments_defensively_handled():
    fn = MagicMock(return_value="rendered_ok")
    # Caller accidentally passed ("Section Title", fn)
    result = safe_render("Section Title", fn)  # type: ignore[arg-type]
    assert result == "rendered_ok"
    fn.assert_called_once()


@patch("src.utils.safe_ops.st.warning")
def test_safe_render_catches_exception(mock_warning):
    def faulty_render():
        raise ValueError("Something went wrong")

    result = safe_render(faulty_render, fallback_msg="Metrics failed")
    assert result is None
    mock_warning.assert_called_once()
    assert "Metrics failed Error: Something went wrong" in mock_warning.call_args[0][0]


@patch("src.utils.safe_ops.st.warning")
def test_safe_render_inverted_exception_displays_correct_fallback(mock_warning):
    def faulty_render():
        raise RuntimeError("Crash")

    result = safe_render("Operational KPI Metrics", faulty_render)  # type: ignore[arg-type]
    assert result is None
    mock_warning.assert_called_once()
    assert "Operational KPI Metrics Error: Crash" in mock_warning.call_args[0][0]


def test_safe_filter_success():
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = safe_filter(df, lambda d: d[d["a"] > 1], filter_name="gt1")
    assert len(result) == 2


@patch("src.utils.safe_ops.st.warning")
def test_safe_filter_fallback_on_exception(mock_warning):
    df = pd.DataFrame({"a": [1, 2, 3]})

    def bad_filter(d):
        raise KeyError("missing")

    result = safe_filter(df, bad_filter, filter_name="bad")
    assert len(result) == 3
    mock_warning.assert_called_once()
