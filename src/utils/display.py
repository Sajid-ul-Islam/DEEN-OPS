"""Display utilities for chart labels and text formatting."""

from __future__ import annotations


def truncate_label(text: str, max_len: int = 25) -> str:
    """Truncate a string to *max_len* characters, appending '...' if needed.

    Args:
        text: The label text to truncate.
        max_len: Maximum allowed length (including the ellipsis).

    Returns:
        The original string if short enough, otherwise truncated with '...'.
    """
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
