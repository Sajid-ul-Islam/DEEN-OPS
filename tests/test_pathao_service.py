"""Synthetic-only regressions for the processed parcel/API boundary."""

import json
import os
import time
from unittest.mock import Mock
from pathlib import Path

import pandas as pd
import pytest
from requests import Response
from requests.exceptions import HTTPError, Timeout

from src.services.pathao import client as client_module
from src.services.pathao import status as status_module
from src.services.pathao.client import PathaoClient
from src.services.pathao.orders import PathaoOrderError, build_order_payload
from src.services.pathao.status import (
    fetch_pending_pathao_orders,
    fetch_wc_pending_in_pathao,
)


@pytest.fixture
def parcel():
    return {
        "MerchantOrderId": "SYNTHETIC-101",
        "RecipientName(*)": "Synthetic Recipient",
        "RecipientPhone(*)": "01712345678",
        "RecipientAddress(*)": "House 10, Road 4",
        "RecipientCity(*)": "Dhaka",
        "RecipientZone(*)": "Mirpur",
        "RecipientArea": "Section 10",
        "AmountToCollect(*)": 1599.5,
        "ItemQuantity": 3,
        "ItemWeight": "0.5",
        "ItemDesc": "Three synthetic items",
        "SpecialInstruction": "SPLIT PARCEL",
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Never load a real token or real merchant credentials.
    monkeypatch.setattr(PathaoClient, "_load_token", lambda self: None)
    monkeypatch.setattr(client_module, "log_system_event", lambda *args: None)
    instance = PathaoClient("https://pathao.invalid", "test", "test", "test", "test")
    instance.token_file = str(tmp_path / "pathao_token.json")
    instance.access_token = "synthetic-token"
    instance.expires_at = time.time() + 3600
    return instance


def response(status=200, document=None):
    result = Response()
    result.status_code = status
    result._content = json.dumps(document).encode()
    return result


def test_payload_preserves_processor_fields_and_split_instructions(parcel):
    result = build_order_payload(
        pd.Series(parcel), "42", special_instructions="Call first"
    )
    assert result == {
        "store_id": 42,
        "merchant_order_id": "SYNTHETIC-101",
        "recipient_name": "Synthetic Recipient",
        "recipient_phone": "01712345678",
        "recipient_address": "House 10, Road 4, Section 10, Mirpur, Dhaka",
        "delivery_type": 48,
        "item_type": 2,
        "item_quantity": 3,
        "item_weight": 0.5,
        "amount_to_collect": 1599.5,
        "item_description": "Three synthetic items",
        "special_instruction": "SPLIT PARCEL | Call first",
    }
    assert not {"recipient_city", "recipient_zone", "recipient_area"}.intersection(
        result
    )


def test_prepaid_zero_cod_is_valid_and_locations_are_not_repeated(parcel):
    parcel["AmountToCollect(*)"] = "0"
    parcel["RecipientAddress(*)"] = "House 10, Section 10, Mirpur, Dhaka"
    result = build_order_payload(parcel, 42)
    assert result["amount_to_collect"] == 0
    assert result["recipient_address"] == parcel["RecipientAddress(*)"]


@pytest.mark.parametrize(
    "phone",
    [
        "+8801712345678",
        "8801712345678",
        1712345678,
        1712345678.0,
        "01712-345678",
        "০১৭১২৩৪৫৬৭৮",
    ],
)
def test_phone_input_variants_are_normalized(parcel, phone):
    parcel["RecipientPhone(*)"] = phone
    assert build_order_payload(parcel, 42)["recipient_phone"] == "01712345678"


@pytest.mark.parametrize(
    "field,value",
    [
        ("MerchantOrderId", ""),
        ("MerchantOrderId", pd.NA),
        ("RecipientName(*)", "Customer"),
        ("RecipientName(*)", None),
        ("RecipientPhone(*)", "01700000000"),
        ("RecipientPhone(*)", "0171***5678"),
        ("RecipientPhone(*)", "01112345678"),
        ("RecipientPhone(*)", "01712345678 01812345678"),
        ("RecipientAddress(*)", "Address Missing"),
        ("RecipientAddress(*)", ""),
        ("AmountToCollect(*)", None),
        ("AmountToCollect(*)", float("nan")),
        ("AmountToCollect(*)", float("inf")),
        ("AmountToCollect(*)", -1),
        ("ItemQuantity", 1.5),
        ("ItemQuantity", 0),
        ("ItemQuantity", True),
        ("ItemWeight", 0),
        ("ItemWeight", "infinity"),
        ("ItemWeight", pd.NA),
    ],
)
def test_invalid_rows_are_blocked_before_dispatch(parcel, field, value):
    parcel[field] = value
    with pytest.raises(
        ValueError,
        match=field.replace("(", r"\(").replace(")", r"\)").replace("*", r"\*"),
    ):
        build_order_payload(parcel, 42)


@pytest.mark.parametrize(
    "store_id", [None, 0, -1, 2.5, True, "not-a-store", float("inf")]
)
def test_pickup_store_must_be_explicit_and_valid(parcel, store_id):
    with pytest.raises(ValueError, match="Pickup store"):
        build_order_payload(parcel, store_id)


def test_old_generic_schema_is_not_silently_sent_as_dummy_order():
    with pytest.raises(ValueError, match="MerchantOrderId"):
        build_order_payload({"Order ID": "123", "Name": "Example", "COD": 150}, 42)


def test_create_order_sends_single_request_and_requires_consignment(
    client, parcel, monkeypatch
):
    transport = Mock(
        return_value=response(
            200,
            {
                "type": "success",
                "data": {
                    "consignment_id": "TEST-CID",
                    "merchant_order_id": "SYNTHETIC-101",
                },
            },
        )
    )
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    payload = build_order_payload(parcel, 42)
    assert client.create_order(payload)["consignment_id"] == "TEST-CID"
    transport.assert_called_once_with(
        "POST",
        "https://pathao.invalid/aladdin/api/v1/orders",
        headers={
            "Authorization": "Bearer synthetic-token",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30,
        max_attempts=1,
        allow_redirects=False,
    )


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {"data": {}},
        {"data": {"consignment_id": " "}},
        {"data": {"consignment_id": None}},
        {"data": []},
    ],
)
def test_success_without_consignment_is_uncertain(client, monkeypatch, document):
    transport = Mock(return_value=response(200, document))
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    with pytest.raises(PathaoOrderError) as error:
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    assert error.value.uncertain
    assert "merchant portal" in str(error.value)
    assert transport.call_count == 1


@pytest.mark.parametrize(
    "status,uncertain",
    [
        (400, False),
        (401, False),
        (403, False),
        (408, True),
        (422, False),
        (429, False),
        (500, True),
        (502, True),
        (503, True),
    ],
)
def test_http_failures_are_classified_without_leaking_response(
    client, monkeypatch, status, uncertain
):
    error_response = response(
        status,
        {
            "message": "secret-token",
            "errors": {
                "recipient_phone": ["PRIVATE CUSTOMER DATA"],
                "private_customer": ["PRIVATE"],
            },
        },
    )
    transport = Mock(
        side_effect=HTTPError("secret-token PRIVATE", response=error_response)
    )
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    with pytest.raises(PathaoOrderError) as error:
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    assert error.value.uncertain is uncertain
    assert "secret-token" not in str(error.value)
    assert "PRIVATE" not in str(error.value)
    assert "private_customer" not in str(error.value)
    assert transport.call_count == 1


def test_timeout_is_uncertain_and_not_retried(client, monkeypatch):
    transport = Mock(side_effect=Timeout("secret-token PRIVATE"))
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    with pytest.raises(PathaoOrderError) as error:
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    assert error.value.uncertain
    assert "secret-token" not in str(error.value)
    assert transport.call_count == 1
    assert transport.call_args.kwargs["max_attempts"] == 1


def test_invalid_json_after_post_is_uncertain(client, monkeypatch):
    result = response()
    result._content = b"not-json"
    monkeypatch.setattr(
        client_module, "request_with_backoff", Mock(return_value=result)
    )
    with pytest.raises(PathaoOrderError) as error:
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    assert error.value.uncertain


def test_semantic_rejection_is_not_reported_as_success(client, monkeypatch):
    monkeypatch.setattr(
        client_module,
        "request_with_backoff",
        Mock(
            return_value=response(
                200,
                {"type": "error", "code": 422, "errors": {"store_id": ["not allowed"]}},
            )
        ),
    )
    with pytest.raises(PathaoOrderError, match="store_id") as error:
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    assert not error.value.uncertain


@pytest.mark.parametrize("refresh_token", [None, "expired-refresh"])
def test_failed_auth_with_expired_token_never_posts_order(
    client, monkeypatch, refresh_token
):
    client.expires_at = 0
    client.refresh_token = refresh_token
    monkeypatch.setattr(client, "issue_access_token", Mock(return_value=False))
    monkeypatch.setattr(client, "refresh_access_token", Mock(return_value=False))
    transport = Mock()
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    with pytest.raises(PathaoOrderError, match="authentication") as error:
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    assert not error.value.uncertain
    assert client.access_token is None
    transport.assert_not_called()


def test_auth_response_without_token_never_posts_order(client, monkeypatch):
    client.expires_at = 0
    transport = Mock(return_value=response(200, {"access_token": None}))
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    with pytest.raises(PathaoOrderError, match="authentication"):
        client.create_order({"merchant_order_id": "SYNTHETIC-101"})
    transport.assert_called_once()
    assert transport.call_args.args[1].endswith("issue-token")


def test_stores_pagination_loads_all_pickup_choices(client, monkeypatch):
    transport = Mock(
        side_effect=[
            response(
                200,
                {
                    "data": {
                        "data": [{"store_id": 10, "store_name": "Outlet A"}],
                        "current_page": 1,
                        "last_page": 2,
                    }
                },
            ),
            response(
                200,
                {
                    "data": {
                        "data": [{"store_id": 20, "store_name": "Outlet B"}],
                        "current_page": 2,
                        "last_page": 2,
                    }
                },
            ),
        ]
    )
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    stores, error = client.get_stores()
    assert error is None
    assert [store["store_id"] for store in stores] == [10, 20]
    assert [call.kwargs["params"] for call in transport.call_args_list] == [
        {"page": 1},
        {"page": 2},
    ]
    assert all(call.args[0] == "GET" for call in transport.call_args_list)


def test_stores_next_page_url_cannot_redirect_credentials(client, monkeypatch):
    transport = Mock(
        side_effect=[
            response(
                200,
                {
                    "data": {
                        "data": [{"store_id": 10, "store_name": "Outlet A"}],
                        "current_page": 1,
                        "next_page_url": "https://untrusted.invalid/collect",
                    }
                },
            ),
            response(
                200,
                {
                    "data": {
                        "data": [{"store_id": 20, "store_name": "Outlet B"}],
                        "current_page": 2,
                        "next_page_url": None,
                    }
                },
            ),
        ]
    )
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    stores, error = client.get_stores()
    assert error is None and len(stores) == 2
    assert all(
        call.args[1] == "https://pathao.invalid/aladdin/api/v1/stores"
        for call in transport.call_args_list
    )


def test_store_loading_failures_are_actionable_and_sanitized(client, monkeypatch):
    transport = Mock(
        side_effect=HTTPError("secret-token PRIVATE", response=response(401))
    )
    monkeypatch.setattr(client_module, "request_with_backoff", transport)
    stores, error = client.get_stores()
    assert stores == []
    assert "401" in error and "credentials" in error
    assert "secret-token" not in error and "PRIVATE" not in error


@pytest.mark.parametrize("changed_field", ["base_url", "client_id", "username"])
def test_token_cache_is_never_reused_by_another_account(
    monkeypatch, tmp_path, changed_field
):
    monkeypatch.chdir(tmp_path)
    credentials = dict(
        base_url="https://pathao.invalid",
        client_id="client-a",
        client_secret="synthetic",
        username="merchant-a",
        password="synthetic",
    )
    original = PathaoClient(**credentials)
    original._save_token(
        {
            "access_token": "synthetic-token-a",
            "refresh_token": "synthetic-refresh-a",
            "expires_in": 3600,
        }
    )
    same_account = PathaoClient(**credentials)
    assert same_account.access_token == "synthetic-token-a"
    assert same_account.ensure_token()
    credentials[changed_field] += "-other"
    other_account = PathaoClient(**credentials)
    assert other_account.access_token is None
    assert other_account.refresh_token is None
    assert other_account.expires_at == 0


def test_legacy_cache_is_ignored_and_new_cache_is_private(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    instance = PathaoClient("https://pathao.invalid", "test", "test", "test", "test")
    instance._save_token({"access_token": "synthetic", "expires_in": 3600})
    token_path = Path(instance.token_file)
    if os.name != "nt":
        assert token_path.stat().st_mode & 0o777 == 0o600
    original_json_load = json.load

    def legacy_cache(file):
        data = original_json_load(file)
        data.pop("account_scope")
        return data

    monkeypatch.setattr(client_module.json, "load", legacy_cache)
    reopened = PathaoClient("https://pathao.invalid", "test", "test", "test", "test")
    assert reopened.access_token is None
    assert not list(tmp_path.glob(".pathao-token-*"))


def test_pathao_client_get_orders_success(monkeypatch, client):
    payload = {
        "data": {
            "data": [
                {
                    "consignment_id": "PT12345",
                    "merchant_order_id": "ORD-1",
                    "recipient_name": "Test Customer",
                    "recipient_phone": "01711111111",
                    "recipient_address": "Dhaka, Bangladesh",
                    "created_at": "2026-09-15 10:00:00",
                    "collected_amount": 750.0,
                    "order_status": "In_Transit",
                    "store_name": "Main Warehouse",
                }
            ],
            "current_page": 1,
            "last_page": 2,
            "total": 1,
        }
    }
    captured_params = {}

    def mock_request(method, url, headers=None, params=None, timeout=None):
        captured_params.update(params or {})
        return response(200, payload)

    monkeypatch.setattr(client_module, "request_with_backoff", mock_request)
    orders, meta, err = client.get_orders(
        page=1, limit=50, search="ORD-1", status="In_Transit"
    )

    assert err is None
    assert len(orders) == 1
    assert orders[0]["consignment_id"] == "PT12345"
    assert meta == {"current_page": 1, "last_page": 2, "total": 1}
    assert captured_params == {
        "page": 1,
        "limit": 50,
        "search": "ORD-1",
        "status": "In_Transit",
    }


def test_pathao_client_get_orders_error_handling(monkeypatch, client):
    def mock_request(method, url, headers=None, params=None, timeout=None):
        res = Response()
        res.status_code = 500
        res._content = b"Server Unavailable"
        return res

    monkeypatch.setattr(client_module, "request_with_backoff", mock_request)
    orders, meta, err = client.get_orders()
    assert orders == []
    assert meta is None
    assert "500" in err


def test_fetch_pending_pathao_orders_filters_terminal(monkeypatch, client):
    page_1_data = [
        {
            "consignment_id": "PT001",
            "merchant_order_id": "ORD-001",
            "recipient_name": "Pending User",
            "recipient_phone": "01710000001",
            "recipient_address": "Dhaka",
            "created_at": "2026-09-14 12:00:00",
            "collected_amount": 1200.0,
            "order_status": "in_transit",
            "store_name": "Store 1",
        },
        {
            "consignment_id": "PT002",
            "merchant_order_id": "ORD-002",
            "recipient_name": "Delivered User",
            "recipient_phone": "01710000002",
            "recipient_address": "Chittagong",
            "created_at": "2026-09-14 12:00:00",
            "collected_amount": 500.0,
            "order_status": "delivered",
            "store_name": "Store 1",
        },
        {
            "consignment_id": "PT003",
            "merchant_order_id": "ORD-003",
            "recipient_name": "Pickup User",
            "recipient_phone": "01710000003",
            "recipient_address": "Sylhet",
            "created_at": "2026-09-14 12:00:00",
            "collected_amount": 800.0,
            "order_status": "pickup_requested",
            "store_name": "Store 1",
        },
        {
            "consignment_id": "PT004",
            "merchant_order_id": "ORD-004",
            "recipient_name": "Returned User",
            "recipient_phone": "01710000004",
            "recipient_address": "Rajshahi",
            "created_at": "2026-09-14 12:00:00",
            "collected_amount": 400.0,
            "order_status": "returned",
            "store_name": "Store 1",
        },
    ]

    def mock_get_orders(page=1, limit=50, search=None, status=None):
        return page_1_data, {"current_page": 1, "last_page": 1, "total": 4}, None

    monkeypatch.setattr(client, "get_orders", mock_get_orders)
    pending_list, err = fetch_pending_pathao_orders(client, max_pages=1)

    assert err is None
    assert len(pending_list) == 2
    cids = [item["Consignment ID"] for item in pending_list]
    assert cids == ["PT001", "PT003"]
    statuses = [item["Status"] for item in pending_list]
    assert statuses == ["In Transit", "Pickup Requested"]
    assert pending_list[0]["COD Amount"] == 1200.0
    assert pending_list[1]["COD Amount"] == 800.0


def test_fetch_wc_pending_in_pathao(monkeypatch):
    wc_df = pd.DataFrame(
        [
            {
                "Order ID": "WC-101",
                "Consignment ID": "PT-WC-001",
                "Customer Name": "Customer A",
                "Phone": "01711111111",
                "Shipping Address": "Dhaka",
                "Order Date": "2026-09-13",
                "Order Total Amount": 1500.0,
            },
            {
                "Order ID": "WC-102",
                "Consignment ID": "PT-WC-002",
                "Customer Name": "Customer B",
                "Phone": "01722222222",
                "Shipping Address": "Dhaka",
                "Order Date": "2026-09-13",
                "Order Total Amount": 600.0,
            },
            {
                "Order ID": "WC-103",
                "Consignment ID": "PT-WC-003",
                "Customer Name": "Customer C",
                "Phone": "01733333333",
                "Shipping Address": "Dhaka",
                "Order Date": "2026-09-13",
                "Order Total Amount": 900.0,
            },
            {
                "Order ID": "WC-104",
                "Consignment ID": "",
                "Customer Name": "Customer D",
                "Phone": "01744444444",
                "Shipping Address": "Dhaka",
                "Order Date": "2026-09-13",
                "Order Total Amount": 1000.0,
            },
        ]
    )

    mock_status_map = {
        "PT-WC-001": "in_transit",
        "PT-WC-002": "delivered",
        "PT-WC-003": "Status Not Found",
    }

    monkeypatch.setattr(
        status_module,
        "bulk_get_pathao_order_statuses",
        lambda cids, force_refresh=False: mock_status_map,
    )

    pending = fetch_wc_pending_in_pathao(wc_df)
    assert len(pending) == 1
    assert pending[0]["Consignment ID"] == "PT-WC-001"
    assert pending[0]["Order ID"] == "WC-101"
    assert pending[0]["Status"] == "In Transit"
    assert pending[0]["COD Amount"] == 1500.0
    assert pending[0]["Store"] == "WooCommerce"
