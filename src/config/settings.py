import json
import os
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_SCHEMA_PATH = PROJECT_ROOT / "src" / "config" / "secrets_schema.json"

WOOCOMMERCE_ENV_KEYS = {
    "store_url": "WC_URL",
    "consumer_key": "WC_KEY",
    "consumer_secret": "WC_SECRET",
}

PATHAO_ENV_KEYS = {
    "base_url": "PATHAO_BASE_URL",
    "client_id": "PATHAO_CLIENT_ID",
    "client_secret": "PATHAO_CLIENT_SECRET",
    "username": "PATHAO_USERNAME",
    "password": "PATHAO_PASSWORD",
}

LLM_PROVIDER_SOURCES = {
    "openrouter": {
        "section_key": "openrouter_key",
        "env": "OPENROUTER_API_KEY",
        "legacy_secret": "OPENROUTER_KEYS",
    },
    "gemini_free": {
        "section_key": "gemini_key",
        "env": "GEMINI_API_KEY",
        "legacy_secret": "GEMINI_KEYS",
    },
    "groq_free": {
        "section_key": "groq_key",
        "env": "GROQ_API_KEY",
        "legacy_secret": "GROQ_KEYS",
    },
    "huggingface": {
        "section_key": "huggingface_key",
        "env": "HF_API_KEY",
        "legacy_secret": "HF_KEYS",
    },
}


def _secrets_root():
    try:
        return st.secrets
    except Exception:
        return {}


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)
    except Exception:
        return {}


def _normalize_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.split(",") if "," in value else [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = [value]

    normalized: list[str] = []
    for candidate in candidates:
        text = str(candidate).strip()
        if text:
            normalized.append(text)
    return normalized


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def get_secret_section(section_name: str) -> dict[str, Any]:
    secrets = _secrets_root()
    try:
        return _as_dict(secrets.get(section_name, {}))
    except Exception:
        try:
            return _as_dict(secrets[section_name])
        except Exception:
            return {}


def get_top_level_secret(key: str, default: Any = None) -> Any:
    secrets = _secrets_root()
    try:
        return secrets.get(key, default)
    except Exception:
        return default


def _env_present(env_keys: dict[str, str]) -> bool:
    return any(os.getenv(env_name) for env_name in env_keys.values())


def _config_missing_keys(config: dict[str, Any], required_keys: tuple[str, ...]) -> list[str]:
    return [key for key in required_keys if not config.get(key)]


def get_setting(key, default=None):
    """Reads setting from Streamlit secrets first, then env var."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


def get_woocommerce_config(required: bool = False) -> dict[str, str]:
    """Return WooCommerce credentials from Streamlit secrets or env vars."""
    section = get_secret_section("woocommerce")
    config = {
        "store_url": section.get("store_url") or section.get("url") or os.getenv("WC_URL"),
        "consumer_key": section.get("consumer_key") or os.getenv("WC_KEY"),
        "consumer_secret": section.get("consumer_secret") or os.getenv("WC_SECRET"),
    }
    missing = _config_missing_keys(
        config, ("store_url", "consumer_key", "consumer_secret")
    )
    if required and missing:
        raise ValueError(
            "WooCommerce configuration is incomplete. Missing keys: "
            + ", ".join(missing)
        )
    return {key: value for key, value in config.items() if value}


def get_pathao_config(required: bool = False) -> dict[str, str]:
    """Return Pathao credentials from Streamlit secrets or env vars."""
    section = get_secret_section("pathao")
    config = {
        "base_url": section.get("base_url") or os.getenv("PATHAO_BASE_URL"),
        "client_id": section.get("client_id") or os.getenv("PATHAO_CLIENT_ID"),
        "client_secret": section.get("client_secret")
        or os.getenv("PATHAO_CLIENT_SECRET"),
        "username": section.get("username") or os.getenv("PATHAO_USERNAME"),
        "password": section.get("password") or os.getenv("PATHAO_PASSWORD"),
    }
    missing = _config_missing_keys(
        config, ("base_url", "client_id", "client_secret", "username", "password")
    )
    if required and missing:
        raise ValueError(
            "Pathao configuration is incomplete. Missing keys: "
            + ", ".join(missing)
        )
    return {key: value for key, value in config.items() if value}


def get_llm_provider_keys() -> dict[str, list[str]]:
    """Return configured LLM provider keys from supported secret and env formats."""
    llm_section = get_secret_section("llm")
    providers: dict[str, list[str]] = {}

    for provider, source in LLM_PROVIDER_SOURCES.items():
        values: list[str] = []
        values.extend(_normalize_values(llm_section.get(source["section_key"])))
        values.extend(_normalize_values(get_top_level_secret(source["legacy_secret"])))
        values.extend(_normalize_values(os.getenv(source["env"])))
        providers[provider] = _dedupe(values)

    return providers


def is_auth_configured() -> bool:
    """Return True when the OIDC auth block is present and complete."""
    auth = get_secret_section("auth")
    if not auth:
        return False

    google = _as_dict(auth.get("google"))
    return all(auth.get(key) for key in ("redirect_uri", "cookie_secret")) and all(
        google.get(key)
        for key in ("client_id", "client_secret", "server_metadata_url")
    )


def load_secrets_schema() -> dict[str, Any]:
    """Load the checked-in secrets schema for docs and validation."""
    try:
        with SECRETS_SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
            return json.load(schema_file)
    except (OSError, json.JSONDecodeError):
        return {}


def validate_runtime_configuration() -> list[str]:
    """Validate partially configured integrations and return actionable issues."""
    issues: list[str] = []
    schema = load_secrets_schema().get("sections", {})
    woocommerce_keys = tuple(
        schema.get("woocommerce", {}).get("keys", {}).keys()
    ) or ("store_url", "consumer_key", "consumer_secret")
    pathao_keys = tuple(schema.get("pathao", {}).get("keys", {}).keys()) or (
        "base_url",
        "client_id",
        "client_secret",
        "username",
        "password",
    )
    auth_keys = tuple(schema.get("auth", {}).get("keys", {}).keys()) or (
        "redirect_uri",
        "cookie_secret",
    )
    auth_google_keys = tuple(
        schema.get("auth", {})
        .get("children", {})
        .get("google", {})
        .get("keys", {})
        .keys()
    ) or ("client_id", "client_secret", "server_metadata_url")
    llm_requires_one = bool(schema.get("llm", {}).get("at_least_one", False))

    woocommerce_section = get_secret_section("woocommerce")
    woocommerce_config = get_woocommerce_config(required=False)
    if woocommerce_section or _env_present(WOOCOMMERCE_ENV_KEYS):
        missing = _config_missing_keys(woocommerce_config, woocommerce_keys)
        if missing:
            issues.append(
                "WooCommerce configuration is incomplete. Missing keys: "
                + ", ".join(missing)
                + "."
            )

    pathao_section = get_secret_section("pathao")
    pathao_config = get_pathao_config(required=False)
    if pathao_section or _env_present(PATHAO_ENV_KEYS):
        missing = _config_missing_keys(pathao_config, pathao_keys)
        if missing:
            issues.append(
                "Pathao configuration is incomplete. Missing keys: "
                + ", ".join(missing)
                + "."
            )

    auth = get_secret_section("auth")
    if auth and not is_auth_configured():
        google = _as_dict(auth.get("google"))
        missing_auth = [key for key in auth_keys if not auth.get(key)]
        missing_google = [key for key in auth_google_keys if not google.get(key)]
        if missing_auth:
            issues.append(
                "Auth configuration is incomplete. Missing auth keys: "
                + ", ".join(missing_auth)
                + "."
            )
        if missing_google:
            issues.append(
                "Auth configuration is incomplete. Missing auth.google keys: "
                + ", ".join(missing_google)
                + "."
            )

    llm_section = get_secret_section("llm")
    llm_keys = get_llm_provider_keys()
    llm_present = bool(llm_section) or any(
        get_top_level_secret(source["legacy_secret"]) or os.getenv(source["env"])
        for source in LLM_PROVIDER_SOURCES.values()
    )
    if llm_present and llm_requires_one and not any(llm_keys.values()):
        issues.append(
            "LLM configuration is present but no provider keys were resolved."
        )

    return issues


def get_gcp_service_account_info():
    """Returns service account info from st.secrets or env JSON."""
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass

    raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except Exception as e:
            raise ValueError(f"Invalid GCP_SERVICE_ACCOUNT_JSON: {e}")

    return None
