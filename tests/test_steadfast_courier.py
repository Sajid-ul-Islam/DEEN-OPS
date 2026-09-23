"""Unit tests for SteadfastCourierClient (P3)."""

from unittest.mock import MagicMock, patch

from src.services.courier.steadfast import SteadfastCourierClient


def test_unconfigured_client_returns_error():
    """Client with missing keys returns clear error."""
    client = SteadfastCourierClient(api_key="", secret_key="")
    assert client.is_configured is False
    res = client.create_order(
        order_id="101",
        recipient_name="John Doe",
        recipient_phone="01712345678",
        recipient_address="Dhaka",
        amount_to_collect=500,
    )
    assert res["success"] is False
    assert "not configured" in res["error"]


def test_invalid_phone_returns_error():
    """Invalid phone number is caught before making network call."""
    client = SteadfastCourierClient(api_key="key", secret_key="sec")
    res = client.create_order(
        order_id="101",
        recipient_name="John Doe",
        recipient_phone="12345",  # Invalid
        recipient_address="Dhaka",
        amount_to_collect=500,
    )
    assert res["success"] is False
    assert "Invalid recipient phone number" in res["error"]


def test_create_order_success():
    """Mock successful order creation with Steadfast."""
    client = SteadfastCourierClient(api_key="valid_key", secret_key="valid_sec")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": 200,
        "message": "Order created successfully",
        "consignment": {
            "consignment_id": 998877,
            "invoice": "101",
            "tracking_code": "STDF998877",
            "status": "in_review",
            "cod_amount": 500,
        },
    }

    with patch("requests.request", return_value=mock_resp) as mock_req:
        res = client.create_order(
            order_id="101",
            recipient_name="Test Customer",
            recipient_phone="+8801711223344",
            recipient_address="Mirpur 10, Dhaka",
            amount_to_collect=500.0,
            item_description="1x Panjabi",
        )

        assert res["success"] is True
        assert res["consignment_id"] == "998877"
        assert res["tracking_code"] == "STDF998877"
        assert res["status"] == "in_review"

        # Verify normalized payload
        mock_req.assert_called_once()
        _, kwargs = mock_req.call_args
        payload = kwargs["json"]
        assert payload["recipient_phone"] == "01711223344"
        assert payload["cod_amount"] == 500
        assert payload["invoice"] == "101"


def test_get_order_status_success():
    """Mock status check by invoice."""
    client = SteadfastCourierClient(api_key="k", secret_key="s")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": 200,
        "delivery_status": "delivered",
    }

    with patch("requests.request", return_value=mock_resp):
        res = client.get_order_status(order_id="101")
        assert res["success"] is True
        assert res["delivery_status"] == "delivered"
