from collections.abc import Callable
from io import BytesIO

import pandas as pd
import streamlit as st


@st.cache_data(show_spinner=False)
def read_sales_file(file_obj, file_name):
    """Reads CSV/XLSX from uploader, file path, or bytes buffer."""
    if str(file_name).lower().endswith(".csv"):
        return pd.read_csv(file_obj)
    return pd.read_excel(file_obj)


def read_uploaded(uploaded_file):
    """Generic reader for uploaded files (CSV/XLSX or an already-loaded DataFrame)."""
    if uploaded_file is None:
        return None
    if isinstance(uploaded_file, pd.DataFrame):
        return uploaded_file
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    name = getattr(uploaded_file, "name", "")
    if isinstance(name, str) and name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    try:
        return pd.read_excel(uploaded_file)
    except Exception:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        return pd.read_csv(uploaded_file)


def to_excel_bytes(
    df: pd.DataFrame,
    sheet_name: str = "Sheet1",
    style_fn: Callable | None = None,
) -> bytes:
    """Convert a DataFrame to an in-memory Excel file.

    Args:
        df: The DataFrame to export.
        sheet_name: Name of the worksheet (default ``"Sheet1"``).
        style_fn: Optional callback ``fn(worksheet, workbook)`` invoked
            after the data is written.  Use it to apply column widths,
            freeze panes, number formats, etc.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        if style_fn is not None:
            style_fn(writer.book[sheet_name], writer.book)
    output.seek(0)
    return output.read()
