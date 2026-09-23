"""Unit tests for notifications engine (P5)."""

from unittest.mock import MagicMock, patch

from src.utils.notifications import (
    send_shift_report_notification,
    send_telegram_message,
    send_webhook_alert,
)


def test_unconfigured_telegram_returns_false():
    """Unconfigured token/chat_id safely returns False without raising."""
    with patch("src.utils.notifications.get_telegram_config", return_value=("", "")):
        assert send_telegram_message("Test message") is False


def test_telegram_message_success():
    """Successful Telegram dispatch."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with (
        patch(
            "src.utils.notifications.get_telegram_config",
            return_value=("token123", "chat456"),
        ),
        patch("requests.request", return_value=mock_resp) as mock_req,
    ):
        assert send_telegram_message("Shift Summary", chat_id="chat456") is True
        mock_req.assert_called_once()
        _, kwargs = mock_req.call_args
        assert kwargs["json"]["chat_id"] == "chat456"
        assert kwargs["json"]["text"] == "Shift Summary"


def test_webhook_alert_success():
    """Successful generic webhook dispatch."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with (
        patch(
            "src.utils.notifications.get_webhook_url",
            return_value="https://hooks.slack.com/services/test",
        ),
        patch("requests.request", return_value=mock_resp) as mock_req,
    ):
        assert (
            send_webhook_alert("Critical Sync Error", "WooCommerce 500", level="error")
            is True
        )
        mock_req.assert_called_once()
        _, kwargs = mock_req.call_args
        assert "🚨" in kwargs["json"]["text"]


def test_send_shift_report_notification():
    """Shift report broadcast triggers ops alert."""
    with patch("src.utils.notifications.send_ops_alert", return_value=True) as mock_ops:
        assert send_shift_report_notification("Gross: 100K") is True
        mock_ops.assert_called_once()
