import pandas as pd
import streamlit as st
from io import BytesIO


@st.cache_data(show_spinner=False)
def read_sales_file(file_obj, file_name):
    """Reads CSV/XLSX from uploader, file path, or bytes buffer."""
    if str(file_name).lower().endswith(".csv"):
        return pd.read_csv(file_obj)
    return pd.read_excel(file_obj)


def read_uploaded(uploaded_file):
    """Generic file reader for uploaded files."""
    if not uploaded_file:
        return None
    uploaded_file.seek(0)
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def to_excel_bytes(
    df: pd.DataFrame,
    sheet_name: str = "Sheet1",
    style_fn: callable | None = None,
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
