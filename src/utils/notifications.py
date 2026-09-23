"""Proactive Observability & Notification Engine for DEEN-OPS.

Supports instant alerting via:
  1. Telegram Bot (direct message or channel dispatch)
  2. Generic Webhooks (Slack, Discord, MS Teams, internal webhooks)

Fails silently with logged diagnostics if notifications are unconfigured,
ensuring zero disruption to primary terminal workflows.
"""

from __future__ import annotations

import os
from typing import Optional


from src.utils.http import request_with_backoff
from src.utils.logging import log_error, log_system_event


def _get_secret(section: str, key: str, env_var: str) -> str:
    """Retrieve secret from environment variable or streamlit secrets."""
    val = os.getenv(env_var, "")
    if val:
        return val
    try:
        import streamlit as st

        if hasattr(st, "secrets") and section in st.secrets:
            return str(st.secrets[section].get(key, ""))
    except Exception:
        pass
    return ""


def get_telegram_config() -> tuple[str, str]:
    """Return (bot_token, chat_id) for Telegram notifications."""
    token = _get_secret("telegram", "bot_token", "TELEGRAM_BOT_TOKEN")
    chat_id = _get_secret("telegram", "chat_id", "TELEGRAM_CHAT_ID")
    return token, chat_id


def get_webhook_url() -> str:
    """Return webhook URL for generic alerts (Slack/Discord)."""
    return _get_secret("notifications", "webhook_url", "ALERT_WEBHOOK_URL")


def send_telegram_message(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "Markdown",
) -> bool:
    """Dispatch a message to Telegram channel or direct chat."""
    bot_token, default_chat_id = get_telegram_config()
    target_chat = chat_id or default_chat_id

    if not bot_token or not target_chat:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        resp = request_with_backoff(
            "POST", url, json=payload, timeout=10, max_attempts=2
        )
        if resp.status_code == 200:
            log_system_event("TELEGRAM_ALERT_SENT", "Dispatched message successfully")
            return True
        log_system_event(
            "TELEGRAM_ALERT_FAILED", f"HTTP {resp.status_code}: {resp.text}"
        )
        return False
    except Exception as exc:
        log_error(exc, context="send_telegram_message")
        return False


def send_webhook_alert(
    title: str,
    message: str,
    level: str = "warning",
) -> bool:
    """Send JSON payload to configured Slack, Discord, or custom webhook."""
    webhook_url = get_webhook_url()
    if not webhook_url:
        return False

    emoji = "🚨" if level == "error" else "⚠️" if level == "warning" else "ℹ️"
    payload = {
        "text": f"{emoji} *{title}*\n{message}",
        "title": title,
        "level": level,
        "content": message,
    }

    try:
        resp = request_with_backoff(
            "POST", webhook_url, json=payload, timeout=8, max_attempts=2
        )
        return resp.status_code in (200, 204)
    except Exception as exc:
        log_error(exc, context="send_webhook_alert")
        return False


def send_ops_alert(
    title: str,
    message: str,
    level: str = "warning",
) -> bool:
    """Broadcast an operational alert across all configured notification channels."""
    tg_sent = send_telegram_message(f"*{title}*\n{message}")
    wh_sent = send_webhook_alert(title, message, level=level)
    return tg_sent or wh_sent


def send_shift_report_notification(report_text: str) -> bool:
    """Broadcast the formatted Shift Handover Report to management channels."""
    header = "📋 *DEEN-OPS Shift Handover Report Broadcast*\n\n"
    full_message = header + report_text
    return send_ops_alert("Shift Handover Report", full_message, level="info")
