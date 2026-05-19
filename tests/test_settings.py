import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings


def _clear_env(monkeypatch, *keys):
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_get_pathao_config_uses_env_fallback(monkeypatch):
    monkeypatch.setattr(settings, "st", SimpleNamespace(secrets={}))
    monkeypatch.setenv("PATHAO_BASE_URL", "https://courier-api.pathao.com")
    monkeypatch.setenv("PATHAO_CLIENT_ID", "client-id")
    monkeypatch.setenv("PATHAO_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PATHAO_USERNAME", "user@example.com")
    monkeypatch.setenv("PATHAO_PASSWORD", "secret")

    config = settings.get_pathao_config(required=True)

    assert config["base_url"] == "https://courier-api.pathao.com"
    assert config["client_id"] == "client-id"
    assert config["username"] == "user@example.com"


def test_get_pathao_config_has_no_hardcoded_fallback(monkeypatch):
    monkeypatch.setattr(settings, "st", SimpleNamespace(secrets={}))
    _clear_env(
        monkeypatch,
        "PATHAO_BASE_URL",
        "PATHAO_CLIENT_ID",
        "PATHAO_CLIENT_SECRET",
        "PATHAO_USERNAME",
        "PATHAO_PASSWORD",
    )

    assert settings.get_pathao_config(required=False) == {}


def test_validate_runtime_configuration_reports_partial_pathao_section(monkeypatch):
    monkeypatch.setattr(
        settings,
        "st",
        SimpleNamespace(
            secrets={
                "pathao": {
                    "base_url": "https://courier-api.pathao.com",
                    "client_id": "client-id",
                }
            }
        ),
    )
    _clear_env(
        monkeypatch,
        "PATHAO_BASE_URL",
        "PATHAO_CLIENT_ID",
        "PATHAO_CLIENT_SECRET",
        "PATHAO_USERNAME",
        "PATHAO_PASSWORD",
    )

    issues = settings.validate_runtime_configuration()

    assert any("Pathao configuration is incomplete" in issue for issue in issues)
    assert any("client_secret" in issue for issue in issues)


def test_get_llm_provider_keys_collects_section_legacy_and_env_values(monkeypatch):
    monkeypatch.setattr(
        settings,
        "st",
        SimpleNamespace(
            secrets={
                "llm": {"openrouter_key": "openrouter-key"},
                "GROQ_KEYS": ["groq-key-1", "groq-key-2"],
            }
        ),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("HF_API_KEY", raising=False)

    providers = settings.get_llm_provider_keys()

    assert providers["openrouter"] == ["openrouter-key"]
    assert providers["gemini_free"] == ["gemini-key"]
    assert providers["groq_free"] == ["groq-key-1", "groq-key-2"]
    assert providers["huggingface"] == []


def test_is_auth_configured_requires_complete_google_block(monkeypatch):
    monkeypatch.setattr(
        settings,
        "st",
        SimpleNamespace(
            secrets={
                "auth": {
                    "redirect_uri": "https://example.com/callback",
                    "cookie_secret": "cookie-secret",
                    "google": {
                        "client_id": "google-client",
                        "client_secret": "",
                        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
                    },
                }
            }
        ),
    )

    assert settings.is_auth_configured() is False
