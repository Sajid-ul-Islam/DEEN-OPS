"""Shared HTTP helpers with bounded retry/backoff behavior."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import requests

DEFAULT_MAX_ATTEMPTS = int(os.getenv("API_RETRY_MAX_ATTEMPTS", "4"))
DEFAULT_BACKOFF_FACTOR = float(os.getenv("API_BACKOFF_FACTOR_SECONDS", "1"))
DEFAULT_MAX_BACKOFF = float(os.getenv("API_BACKOFF_MAX_SECONDS", "16"))
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

LOGGER = logging.getLogger(__name__)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _compute_backoff_seconds(
    attempt: int,
    retry_after_header: str | None,
    *,
    backoff_factor: float,
    max_backoff: float,
) -> float:
    retry_after = _parse_retry_after(retry_after_header)
    if retry_after is not None:
        return min(max_backoff, retry_after)

    return min(max_backoff, backoff_factor * (2 ** max(0, attempt - 1)))


def _is_retryable_exception(
    exc: requests.RequestException,
    retryable_status_codes: set[int] | frozenset[int],
) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True

    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        return response is not None and response.status_code in retryable_status_codes

    return False


def request_with_backoff(
    method: str,
    url: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    retryable_status_codes: set[int] | frozenset[int] = RETRYABLE_STATUS_CODES,
    request_func: Callable[..., requests.Response] | None = None,
    sleep_func: Callable[[float], Any] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    """Execute an HTTP request with bounded exponential backoff."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    request_callable = request_func or requests.request
    last_exc: requests.RequestException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = request_callable(method, url, **kwargs)
            if response.status_code in retryable_status_codes:
                error = requests.HTTPError(
                    f"Retryable HTTP {response.status_code} for {method.upper()} {url}"
                )
                error.response = response
                raise error

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if not _is_retryable_exception(exc, retryable_status_codes):
                raise
            if attempt >= max_attempts:
                raise

            response = getattr(exc, "response", None)
            wait_seconds = _compute_backoff_seconds(
                attempt,
                response.headers.get("Retry-After") if response is not None else None,
                backoff_factor=backoff_factor,
                max_backoff=max_backoff,
            )
            LOGGER.warning(
                "Retrying %s %s after attempt %s/%s in %.2fs: %s",
                method.upper(),
                url,
                attempt,
                max_attempts,
                wait_seconds,
                exc,
            )
            sleep_func(wait_seconds)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Request loop exited unexpectedly for {method.upper()} {url}")
