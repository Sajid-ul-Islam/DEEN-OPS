"""Fetch DataFrames from public CSV/XLSX URLs with auto-detection."""

from __future__ import annotations

from io import BytesIO, StringIO

import pandas as pd

from src.utils.http import request_with_backoff


def fetch_dataframe_from_url(url: str, timeout: int = 15) -> pd.DataFrame:
    """Fetch a DataFrame from a public CSV or XLSX URL.

    Auto-detects the file format based on URL extension, query parameters,
    and HTTP Content-Type header.

    Args:
        url: Public URL pointing to a CSV or XLSX file.
        timeout: Request timeout in seconds.

    Returns:
        Parsed DataFrame.

    Raises:
        ValueError: If URL is empty or the response cannot be parsed.
        requests.RequestException: On network errors.
    """
    if not url or not url.strip():
        raise ValueError("URL cannot be empty.")

    url = url.strip()
    
    # Auto-convert standard Google Sheets URLs to CSV export URLs
    if "docs.google.com/spreadsheets" in url and "export?format=csv" not in url:
        import re
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        if match:
            doc_id = match.group(1)
            gid_match = re.search(r"[#&]gid=([0-9]+)", url)
            gid = f"&gid={gid_match.group(1)}" if gid_match else ""
            url = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv{gid}"

    resp = request_with_backoff("GET", url, timeout=timeout)

    content_type = resp.headers.get("content-type", "").lower()
    url_lower = url.lower()

    is_csv = (
        url_lower.endswith(".csv")
        or "output=csv" in url_lower
        or "text/csv" in content_type
        or "text/plain" in content_type
    )

    if is_csv:
        return pd.read_csv(StringIO(resp.text))

    # Try Excel first, fall back to CSV
    try:
        return pd.read_excel(BytesIO(resp.content))
    except Exception:
        return pd.read_csv(StringIO(resp.text))
