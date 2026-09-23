"""Tests for the Streamlit version guard (src/utils/version_check.py)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.utils import version_check as vc

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_skip_env(monkeypatch):
    monkeypatch.delenv(vc.SKIP_ENV_VAR, raising=False)


class TestGetPinnedStreamlitVersion:
    def test_reads_exact_pin_from_requirements_lock(self):
        result = vc.get_pinned_streamlit_version()
        assert result is not None
        op, version = result
        assert op == "=="
        assert re.match(r"^\d+\.\d+\.\d+$", version)

    def test_lock_pin_matches_requirements_floor(self):
        """The lock's exact pin must satisfy requirements.txt's floor."""
        lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        req_text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lock_match = vc._PIN_RE.search(lock_text)
        req_match = vc._PIN_RE.search(req_text)
        assert lock_match and req_match
        assert vc._numeric_key(lock_match.group("ver")) >= vc._numeric_key(
            req_match.group("ver")
        )

    def test_returns_none_when_no_pin_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vc, "LOCK_FILE", tmp_path / "missing.lock")
        monkeypatch.setattr(vc, "REQ_FILE", tmp_path / "missing.txt")
        assert vc.get_pinned_streamlit_version() is None

    def test_falls_back_to_requirements_txt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vc, "LOCK_FILE", tmp_path / "missing.lock")
        req = tmp_path / "requirements.txt"
        req.write_text("streamlit>=1.38.0\nrequests\n", encoding="utf-8")
        monkeypatch.setattr(vc, "REQ_FILE", req)
        assert vc.get_pinned_streamlit_version() == (">=", "1.38.0")

    def test_ignores_via_streamlit_comment_lines(self, tmp_path, monkeypatch):
        req = tmp_path / "requirements.lock"
        req.write_text("# via streamlit\nsomepkg==1.0\n", encoding="utf-8")
        monkeypatch.setattr(vc, "LOCK_FILE", req)
        monkeypatch.setattr(vc, "REQ_FILE", tmp_path / "missing.txt")
        assert vc.get_pinned_streamlit_version() is None


class TestBuildWarning:
    def _patch(self, monkeypatch, installed, pinned):
        monkeypatch.setattr(vc, "get_installed_streamlit_version", lambda: installed)
        monkeypatch.setattr(vc, "get_pinned_streamlit_version", lambda: pinned)

    def test_no_warning_when_versions_match(self, monkeypatch):
        self._patch(monkeypatch, "1.63.0", ("==", "1.63.0"))
        assert vc.build_streamlit_version_warning() is None

    def test_warning_when_older_than_pin(self, monkeypatch):
        self._patch(monkeypatch, "1.58.0", ("==", "1.63.0"))
        warning = vc.build_streamlit_version_warning()
        assert warning is not None
        assert "1.58.0" in warning and "1.63.0" in warning
        assert "older than" in warning

    def test_warning_when_newer_than_pin(self, monkeypatch):
        self._patch(monkeypatch, "1.70.0", ("==", "1.63.0"))
        warning = vc.build_streamlit_version_warning()
        assert warning is not None
        assert "newer than" in warning

    def test_no_warning_when_within_floor(self, monkeypatch):
        self._patch(monkeypatch, "1.63.0", (">=", "1.38.0"))
        assert vc.build_streamlit_version_warning() is None

    def test_warning_when_below_floor(self, monkeypatch):
        self._patch(monkeypatch, "1.30.0", (">=", "1.38.0"))
        warning = vc.build_streamlit_version_warning()
        assert warning is not None
        assert "older than the minimum" in warning

    def test_no_warning_when_uninstalled(self, monkeypatch):
        self._patch(monkeypatch, None, ("==", "1.63.0"))
        assert vc.build_streamlit_version_warning() is None

    def test_no_warning_when_no_pin(self, monkeypatch):
        self._patch(monkeypatch, "1.58.0", None)
        assert vc.build_streamlit_version_warning() is None

    def test_skip_env_var_silences_warning(self, monkeypatch):
        monkeypatch.setenv(vc.SKIP_ENV_VAR, "true")
        self._patch(monkeypatch, "1.58.0", ("==", "1.63.0"))
        assert vc.build_streamlit_version_warning() is None

    def test_never_raises_on_internal_error(self, monkeypatch):
        def boom():
            raise RuntimeError("boom")

        monkeypatch.setattr(vc, "get_installed_streamlit_version", boom)
        assert vc.build_streamlit_version_warning() is None
