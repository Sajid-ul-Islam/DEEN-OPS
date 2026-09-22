"""Startup version guard — warns when the active Streamlit version drifts
from the version pinned in requirements.lock.

Pure stdlib (no Streamlit import) so it is safe to use from scripts and tests.

The check is advisory only: it never raises and never blocks startup. Set
DEEN_OPS_SKIP_VERSION_CHECK=true to silence it deliberately (e.g. when testing
against a different Streamlit on purpose).
"""

from __future__ import annotations

import os
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCK_FILE = PROJECT_ROOT / "requirements.lock"
REQ_FILE = PROJECT_ROOT / "requirements.txt"

SKIP_ENV_VAR = "DEEN_OPS_SKIP_VERSION_CHECK"

# Matches "streamlit==1.63.0" / "streamlit>=1.38.0" at line start, ignoring
# environment markers and inline comments. Anchored after leading whitespace
# so "# via streamlit" style lines never match.
_PIN_RE = re.compile(
    r"^\s*streamlit(?P<op>==|>=)\s*(?P<ver>[0-9][^\s;#]*)",
    re.IGNORECASE | re.MULTILINE,
)


def _numeric_key(version: str) -> tuple[int, ...]:
    """Best-effort numeric tuple of the first three version segments."""
    parts = re.findall(r"\d+", version)[:3]
    while len(parts) < 3:
        parts.append("0")
    return tuple(int(part) for part in parts)


def get_pinned_streamlit_version() -> Optional[tuple[str, str]] | None:
    """Return (operator, version) pinned for Streamlit.

    Reads requirements.lock first (exact pin), falling back to
    requirements.txt (floor constraint). Returns None when neither file
    yields a parseable Streamlit entry.
    """
    for path in (LOCK_FILE, REQ_FILE):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = _PIN_RE.search(text)
        if match:
            return match.group("op"), match.group("ver").strip()
    return None


def get_installed_streamlit_version() -> str | None:
    """Installed Streamlit version via importlib.metadata (no import needed)."""
    try:
        return _dist_version("streamlit")
    except PackageNotFoundError:
        return None


def _skip_check_enabled() -> bool:
    return os.getenv(SKIP_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


def build_streamlit_version_warning() -> str | None:
    """Return a human-readable warning when the active Streamlit version does
    not satisfy the project pin, or None when versions align (or the check
    cannot run). Never raises.
    """
    try:
        if _skip_check_enabled():
            return None

        installed = get_installed_streamlit_version()
        pinned = get_pinned_streamlit_version()
        if not installed or not pinned:
            return None

        op, expected = pinned

        if op == ">=":
            # Floor constraint (requirements.txt fallback): warn only when older.
            if _numeric_key(installed) >= _numeric_key(expected):
                return None
            return (
                f"⚠️ Streamlit {installed} is older than the minimum required "
                f"version {expected} ({REQ_FILE.name}). Some features may not "
                f"work as expected. Fix: pip install 'streamlit>={expected}'."
            )

        if installed == expected:
            return None

        installed_key = _numeric_key(installed)
        expected_key = _numeric_key(expected)
        if installed_key < expected_key:
            relation = "older than"
        elif installed_key > expected_key:
            relation = "newer than"
        else:
            relation = "different from"

        return (
            f"⚠️ Streamlit version mismatch — running {installed}, but the "
            f"project pins {expected} ({relation} the pinned version). "
            "Config options or rendering may behave unexpectedly. Fix: "
            f"pip install streamlit=={expected}, or launch via run_app.bat / make run."
        )
    except Exception:
        # Advisory check only — never break startup.
        return None
