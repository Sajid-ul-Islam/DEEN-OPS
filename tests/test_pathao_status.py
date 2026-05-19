import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.pathao import status


def _pathao_config():
    return {
        "base_url": "https://courier-api.pathao.com",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "username": "user@example.com",
        "password": "secret",
    }


def test_verify_pathao_connection_uses_client_token_flow(monkeypatch):
    class DummyClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.access_token = None
            self.ensure_calls = 0

        def ensure_token(self):
            self.ensure_calls += 1
            self.access_token = "token-123"

    monkeypatch.setattr(status, "get_pathao_config", lambda required=False: _pathao_config())
    monkeypatch.setattr(status, "PathaoClient", DummyClient)

    ok, message = status.verify_pathao_connection()

    assert ok is True
    assert "Credentials are working" in message


def test_get_pathao_order_status_uses_existing_client_headers(monkeypatch):
    class DummyClient:
        def __init__(self, **kwargs):
            self.base_url = kwargs["base_url"].rstrip("/")
            self.access_token = "token-123"

        def _get_headers(self):
            return {"Authorization": "Bearer token-123"}

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": {"order_status": "Delivered"}}

    monkeypatch.setattr(status, "get_pathao_config", lambda required=False: _pathao_config())
    monkeypatch.setattr(status, "PathaoClient", DummyClient)

    with patch.object(status, "request_with_backoff", return_value=response) as mock_get:
        result = status.get_pathao_order_status("DD123456")

    assert result["data"]["order_status"] == "Delivered"
    mock_get.assert_called_once_with(
        "GET",
        "https://courier-api.pathao.com/aladdin/api/v1/orders/DD123456/info",
        headers={"Authorization": "Bearer token-123"},
        timeout=10,
    )


def test_get_pathao_order_status_returns_config_error_when_missing_credentials(monkeypatch):
    monkeypatch.setattr(status, "get_pathao_config", lambda required=False: {})

    result = status.get_pathao_order_status("DD123456")

    assert "error" in result
    assert "Pathao credentials are missing" in result["error"]
