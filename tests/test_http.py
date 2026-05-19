import os
import sys
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils.http import request_with_backoff


def _response(status_code, headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    if status_code >= 400:
        http_error = requests.HTTPError(f"{status_code} error")
        http_error.response = response
        response.raise_for_status.side_effect = http_error
    else:
        response.raise_for_status.return_value = None
    return response


def test_request_with_backoff_retries_retry_after_header():
    calls = []
    sleeps = []
    responses = iter([
        _response(429, {"Retry-After": "3"}),
        _response(200),
    ])

    def request_func(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return next(responses)

    response = request_with_backoff(
        "GET",
        "https://example.com/data",
        request_func=request_func,
        sleep_func=sleeps.append,
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert sleeps == [3.0]


def test_request_with_backoff_retries_timeout_then_succeeds():
    sleeps = []
    attempts = {"count": 0}

    def request_func(method, url, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise requests.Timeout("temporary timeout")
        return _response(200)

    response = request_with_backoff(
        "GET",
        "https://example.com/data",
        request_func=request_func,
        sleep_func=sleeps.append,
        backoff_factor=0.5,
    )

    assert response.status_code == 200
    assert attempts["count"] == 2
    assert sleeps == [0.5]


def test_request_with_backoff_does_not_retry_non_retryable_error():
    sleeps = []

    with pytest.raises(requests.HTTPError):
        request_with_backoff(
            "GET",
            "https://example.com/missing",
            request_func=lambda method, url, **kwargs: _response(404),
            sleep_func=sleeps.append,
        )

    assert sleeps == []
