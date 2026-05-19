import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.utils.url_fetch import fetch_dataframe_from_url


class TestFetchDataframeFromUrl:
    def test_empty_url_raises_value_error(self):
        with pytest.raises(ValueError, match="URL cannot be empty"):
            fetch_dataframe_from_url("")

    @patch("src.utils.url_fetch.request_with_backoff")
    def test_csv_detection_by_extension(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/octet-stream"}
        mock_resp.text = "a,b\n1,2\n3,4\n"
        mock_get.return_value = mock_resp

        df = fetch_dataframe_from_url("https://example.com/data.csv")

        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    @patch("src.utils.url_fetch.request_with_backoff")
    def test_csv_detection_by_query_param(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/octet-stream"}
        mock_resp.text = "x,y\n10,20\n"
        mock_get.return_value = mock_resp

        df = fetch_dataframe_from_url(
            "https://docs.google.com/spreadsheets/d/abc/export?output=csv"
        )

        assert list(df.columns) == ["x", "y"]
        assert len(df) == 1

    @patch("src.utils.url_fetch.request_with_backoff")
    def test_csv_detection_by_content_type(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/csv; charset=utf-8"}
        mock_resp.text = "col1,col2\nA,B\n"
        mock_get.return_value = mock_resp

        df = fetch_dataframe_from_url("https://example.com/unknown-path")

        assert list(df.columns) == ["col1", "col2"]
        assert df.iloc[0]["col1"] == "A"

    @patch("src.utils.url_fetch.request_with_backoff")
    def test_excel_fallback_to_csv(self, mock_get):
        """When URL has no CSV indicators and read_excel fails, fall back to CSV."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/octet-stream"}
        mock_resp.text = "name,value\nalpha,100\n"
        # Make content something that is NOT valid Excel so read_excel raises
        mock_resp.content = b"name,value\nalpha,100\n"
        mock_get.return_value = mock_resp

        df = fetch_dataframe_from_url("https://example.com/data")

        assert list(df.columns) == ["name", "value"]
        assert len(df) == 1
