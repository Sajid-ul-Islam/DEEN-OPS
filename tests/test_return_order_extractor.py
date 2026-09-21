"""Unit tests for the Return Orders Extractor service layer.

Tests cover:
- src/services/woocommerce/returns.py
- src/services/pathao/returns.py
- src/pages/return_order_extractor.py (helper functions)

All tests use synthetic data only; no real API calls are made.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
from requests import Response

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_response(
    status: int = 200, body: dict | list | None = None, headers: dict | None = None
) -> Response:
    """Fabricate a `requests.Response` with controlled status, body, and headers."""
    r = Response()
    r.status_code = status
    payload = body if body is not None else []
    r._content = json.dumps(payload).encode("utf-8")
    if headers:
        r.headers.update(headers)
    r.headers.setdefault("X-WP-TotalPages", "1")
    r.headers.setdefault(
        "X-WP-Total", str(len(payload) if isinstance(payload, list) else 1)
    )
    return r


def _minimal_wc_order(
    order_id: int = 101,
    order_number: str = "1001",
    status: str = "refunded",
    consignment_id: str = "",
    refund_reason: str = "",
) -> dict:
    """Return a minimal WooCommerce order dict matching the API response shape."""
    meta = []
    if consignment_id:
        meta.append({"key": "ptc_consignment_id", "value": consignment_id})
    refunds = []
    if refund_reason:
        refunds.append({"reason": refund_reason, "amount": "500.00"})
    return {
        "id": order_id,
        "number": order_number,
        "status": status,
        "date_created_gmt": "2026-09-01T12:00:00Z",
        "date_modified_gmt": "2026-09-02T10:00:00Z",
        "billing": {
            "first_name": "Test",
            "last_name": "User",
            "phone": "01712345678",
            "email": "test@example.com",
            "city": "Dhaka",
            "address_1": "House 10",
        },
        "shipping": {},
        "payment_method_title": "Cash on Delivery",
        "total": "1500.00",
        "discount_total": "0.00",
        "meta_data": meta,
        "line_items": [
            {
                "id": 1,
                "name": "Test Product A",
                "sku": "PROD-A",
                "quantity": 2,
                "price": 750.0,
                "subtotal": "1500.00",
                "total": "1500.00",
            }
        ],
        "fee_lines": [],
        "coupon_lines": [],
        "refunds": refunds,
    }


# ── Tests: woocommerce/returns.py ────────────────────────────────────────────


class TestExtractConsignmentId:
    """Tests for the _extract_consignment_id internal helper."""

    def test_extracts_ptc_consignment_id(self):
        from src.services.woocommerce.returns import _extract_consignment_id

        order = _minimal_wc_order(consignment_id="ABC-123")
        assert _extract_consignment_id(order) == "ABC-123"

    def test_extracts_pathao_consignment_id_key(self):
        from src.services.woocommerce.returns import _extract_consignment_id

        order = {"meta_data": [{"key": "pathao_consignment_id", "value": "XYZ-999"}]}
        assert _extract_consignment_id(order) == "XYZ-999"

    def test_returns_empty_string_when_no_meta(self):
        from src.services.woocommerce.returns import _extract_consignment_id

        order = {"meta_data": []}
        assert _extract_consignment_id(order) == ""

    def test_ignores_null_values(self):
        from src.services.woocommerce.returns import _extract_consignment_id

        order = {
            "meta_data": [
                {"key": "ptc_consignment_id", "value": "null"},
                {"key": "tracking_number", "value": "REAL-456"},
            ]
        }
        # Should skip null and return the next valid key
        assert _extract_consignment_id(order) == "REAL-456"

    def test_ignores_nan_values(self):
        from src.services.woocommerce.returns import _extract_consignment_id

        order = {
            "meta_data": [
                {"key": "ptc_consignment_id", "value": "nan"},
            ]
        }
        assert _extract_consignment_id(order) == ""


class TestBdToUtcIso:
    """Tests for the BD → UTC datetime conversion helper."""

    def test_converts_bd_midnight_to_utc(self):
        from src.services.woocommerce.returns import _bd_to_utc_iso

        bd_dt = datetime(2026, 9, 1, 0, 0, 0)  # Midnight BD
        utc_str = _bd_to_utc_iso(bd_dt)
        # BD is UTC+6, so midnight BD = 18:00 of the previous day UTC
        assert utc_str == "2026-08-31T18:00:00"

    def test_converts_bd_noon_to_utc(self):
        from src.services.woocommerce.returns import _bd_to_utc_iso

        bd_dt = datetime(2026, 9, 15, 12, 0, 0)  # Noon BD
        utc_str = _bd_to_utc_iso(bd_dt)
        assert utc_str == "2026-09-15T06:00:00"


class TestFlattenReturnOrder:
    """Tests for the _flatten_return_order helper."""

    def test_produces_one_row_per_line_item(self):
        from src.services.woocommerce.returns import _flatten_return_order

        order = _minimal_wc_order()
        rows = _flatten_return_order(order)
        assert len(rows) == 1
        assert rows[0]["Product Description"] == "Test Product A"

    def test_includes_consignment_id(self):
        from src.services.woocommerce.returns import _flatten_return_order

        order = _minimal_wc_order(consignment_id="JKT-777")
        rows = _flatten_return_order(order)
        assert rows[0]["Consignment ID"] == "JKT-777"

    def test_includes_wc_status(self):
        from src.services.woocommerce.returns import _flatten_return_order

        order = _minimal_wc_order(status="cancelled")
        rows = _flatten_return_order(order)
        assert rows[0]["WC Return Status"] == "cancelled"

    def test_includes_refund_reason(self):
        from src.services.woocommerce.returns import _flatten_return_order

        order = _minimal_wc_order(refund_reason="Customer changed mind")
        rows = _flatten_return_order(order)
        assert rows[0]["Refund Reason (WC)"] == "Customer changed mind"

    def test_handles_no_line_items(self):
        from src.services.woocommerce.returns import _flatten_return_order

        order = _minimal_wc_order()
        order["line_items"] = []
        rows = _flatten_return_order(order)
        # Should still return one row with empty product info
        assert len(rows) == 1
        assert rows[0]["Product Description"] == ""


class TestFetchWcReturnOrders:
    """Tests for the fetch_wc_return_orders public function."""

    @patch("src.services.woocommerce.returns.get_woocommerce_config")
    def test_returns_error_when_no_credentials(self, mock_cfg):
        from src.services.woocommerce.returns import fetch_wc_return_orders

        mock_cfg.return_value = {}
        rows, err = fetch_wc_return_orders(datetime(2026, 9, 1), datetime(2026, 9, 30))
        assert rows == []
        assert err is not None
        assert "credentials" in err.lower()

    @patch("src.services.woocommerce.returns.get_woocommerce_config")
    @patch("src.services.woocommerce.returns.request_with_backoff")
    def test_returns_empty_when_api_returns_no_orders(self, mock_req, mock_cfg):
        from src.services.woocommerce.returns import fetch_wc_return_orders

        mock_cfg.return_value = {
            "store_url": "https://fake.store",
            "consumer_key": "key",
            "consumer_secret": "secret",
        }
        mock_req.return_value = _make_response(200, [], {"X-WP-TotalPages": "1"})

        rows, err = fetch_wc_return_orders(datetime(2026, 9, 1), datetime(2026, 9, 30))
        assert rows == []
        assert err is None

    @patch("src.services.woocommerce.returns.get_woocommerce_config")
    @patch("src.services.woocommerce.returns.request_with_backoff")
    def test_fetches_and_flattens_orders(self, mock_req, mock_cfg):
        from src.services.woocommerce.returns import fetch_wc_return_orders

        mock_cfg.return_value = {
            "store_url": "https://fake.store",
            "consumer_key": "key",
            "consumer_secret": "secret",
        }
        order = _minimal_wc_order(order_id=200, order_number="2001", status="refunded")
        mock_req.return_value = _make_response(200, [order], {"X-WP-TotalPages": "1"})

        rows, err = fetch_wc_return_orders(datetime(2026, 9, 1), datetime(2026, 9, 30))
        assert err is None
        assert len(rows) == 1
        assert rows[0]["Order Number"] == "2001"
        assert rows[0]["WC Return Status"] == "refunded"

    @patch("src.services.woocommerce.returns.get_woocommerce_config")
    @patch("src.services.woocommerce.returns.request_with_backoff")
    def test_order_number_filter_applied_post_fetch(self, mock_req, mock_cfg):
        from src.services.woocommerce.returns import fetch_wc_return_orders

        mock_cfg.return_value = {
            "store_url": "https://fake.store",
            "consumer_key": "key",
            "consumer_secret": "secret",
        }
        orders = [
            _minimal_wc_order(order_id=1, order_number="1001"),
            _minimal_wc_order(order_id=2, order_number="1002"),
            _minimal_wc_order(order_id=3, order_number="1003"),
        ]
        mock_req.return_value = _make_response(200, orders, {"X-WP-TotalPages": "1"})

        rows, err = fetch_wc_return_orders(
            datetime(2026, 9, 1),
            datetime(2026, 9, 30),
            order_numbers=["1002"],
        )
        assert err is None
        assert len(rows) == 1
        assert rows[0]["Order Number"] == "1002"


# ── Tests: pathao/returns.py ─────────────────────────────────────────────────


class TestEnrichReturnOrdersWithPathao:
    """Tests for enrich_return_orders_with_pathao."""

    def test_handles_empty_orders_list(self):
        from src.services.pathao.returns import enrich_return_orders_with_pathao

        result = enrich_return_orders_with_pathao([])
        assert result == []

    def test_adds_na_when_no_consignment_id(self):
        from src.services.pathao.returns import enrich_return_orders_with_pathao

        orders = [
            {
                "Order Number": "1001",
                "WC Return Status": "refunded",
                "Consignment ID": "",
                "Product Description": "Test Item",
            }
        ]
        result = enrich_return_orders_with_pathao(orders)
        assert result[0]["Pathao Status"] == "N/A (No Consignment ID)"
        assert result[0]["Return Reason (Pathao)"] == ""

    @patch("src.services.pathao.returns.batch_get_pathao_return_info")
    def test_maps_pathao_status_correctly(self, mock_batch):
        from src.services.pathao.returns import enrich_return_orders_with_pathao

        mock_batch.return_value = {
            "JKT-001": {"status": "returned", "return_reason": "Customer unavailable"},
        }
        orders = [
            {
                "Order Number": "1001",
                "WC Return Status": "refunded",
                "Consignment ID": "JKT-001",
                "Product Description": "Test Item",
            }
        ]
        result = enrich_return_orders_with_pathao(orders)
        assert result[0]["Pathao Status"] == "Returned"  # .title() applied
        assert result[0]["Return Reason (Pathao)"] == "Customer unavailable"

    @patch("src.services.pathao.returns.batch_get_pathao_return_info")
    def test_skips_pathao_call_when_no_valid_consignment_ids(self, mock_batch):
        from src.services.pathao.returns import enrich_return_orders_with_pathao

        orders = [
            {"Order Number": "1001", "Consignment ID": ""},
            {"Order Number": "1002", "Consignment ID": ""},
        ]
        result = enrich_return_orders_with_pathao(orders)
        # Should NOT call batch_get_pathao_return_info
        mock_batch.assert_not_called()
        for r in result:
            assert r["Pathao Status"] == "N/A (No Consignment ID)"


class TestGetPathaoReturnReason:
    """Tests for the get_pathao_return_reason helper."""

    def test_returns_empty_strings_for_empty_consignment_id(self):
        from src.services.pathao.returns import get_pathao_return_reason

        status, reason = get_pathao_return_reason("")
        assert status == ""
        assert reason == ""

    @patch("src.services.pathao.returns._build_pathao_client")
    @patch("src.services.pathao.returns._load_pathao_disk_cache")
    @patch("src.services.pathao.returns._save_pathao_disk_cache")
    @patch("src.services.pathao.returns.request_with_backoff")
    def test_fetches_reason_from_api(self, mock_req, mock_save, mock_load, mock_client):
        from src.services.pathao.returns import get_pathao_return_reason

        mock_load.return_value = {}
        mock_save.return_value = None

        mock_pathao_client = MagicMock()
        mock_pathao_client.base_url = "https://api.pathao.com"
        mock_pathao_client._get_headers.return_value = {
            "Authorization": "Bearer fake-token"
        }
        mock_client.return_value = (mock_pathao_client, None)

        api_resp = Response()
        api_resp.status_code = 200
        api_resp._content = json.dumps(
            {
                "type": "success",
                "data": {
                    "order_status": "returned",
                    "return_reason": "Customer not at home",
                },
            }
        ).encode()
        mock_req.return_value = api_resp

        status, reason = get_pathao_return_reason("JKT-555")
        assert status == "returned"
        assert reason == "Customer not at home"

    @patch("src.services.pathao.returns._build_pathao_client")
    @patch("src.services.pathao.returns._load_pathao_disk_cache")
    def test_returns_empty_when_client_error(self, mock_load, mock_client):
        from src.services.pathao.returns import get_pathao_return_reason

        mock_load.return_value = {}
        mock_client.return_value = (None, "Authentication failed")

        status, reason = get_pathao_return_reason("JKT-999")
        assert status == ""
        assert reason == ""


# ── Tests: return_order_extractor.py (page helpers) ─────────────────────────


class TestReturnOrderExtractorHelpers:
    """Tests for utility functions in the page module."""

    def test_parse_multivalue_input_comma_separated(self):
        from src.pages.return_order_extractor import _parse_multivalue_input

        result = _parse_multivalue_input("1001, 1002, 1003")
        assert result == ["1001", "1002", "1003"]

    def test_parse_multivalue_input_newline_separated(self):
        from src.pages.return_order_extractor import _parse_multivalue_input

        result = _parse_multivalue_input("1001\n1002\n1003")
        assert result == ["1001", "1002", "1003"]

    def test_parse_multivalue_input_empty_string(self):
        from src.pages.return_order_extractor import _parse_multivalue_input

        assert _parse_multivalue_input("") == []
        assert _parse_multivalue_input("   ") == []

    def test_compute_summary_metrics_calculates_correctly(self):
        from src.pages.return_order_extractor import _compute_summary_metrics

        df = pd.DataFrame(
            [
                {
                    "Order Number": "1001",
                    "Order Total": 1500.0,
                    "WC Return Status": "refunded",
                    "Pathao Status": "Returned",
                    "Return Reason (Pathao)": "Wrong size",
                },
                {
                    "Order Number": "1001",
                    "Order Total": 1500.0,
                    "WC Return Status": "refunded",
                    "Pathao Status": "Returned",
                    "Return Reason (Pathao)": "",
                },
                {
                    "Order Number": "1002",
                    "Order Total": 800.0,
                    "WC Return Status": "cancelled",
                    "Pathao Status": "Delivered",
                    "Return Reason (Pathao)": "",
                },
            ]
        )
        metrics = _compute_summary_metrics(df)
        assert metrics["unique_orders"] == 2
        assert metrics["total_line_items"] == 3
        # Total value should be sum of unique order totals: 1500 + 800 = 2300
        assert metrics["total_value"] == 2300.0
        # Mismatch: 1002 is cancelled in WC but "Delivered" in Pathao → 1 mismatch
        assert metrics["mismatches"] == 1
        # "Wrong size" is a non-empty return reason → 1
        assert metrics["has_reason"] == 1

    def test_build_date_defaults_last_7_days(self):
        from src.pages.return_order_extractor import _build_date_defaults

        start, end = _build_date_defaults("Last 7 Days")
        assert (end - start).days == 7

    def test_build_date_defaults_last_30_days(self):
        from src.pages.return_order_extractor import _build_date_defaults

        start, end = _build_date_defaults("Last 30 Days")
        assert (end - start).days == 30

    def test_build_date_defaults_last_3_months(self):
        from src.pages.return_order_extractor import _build_date_defaults

        start, end = _build_date_defaults("Last 3 Months")
        assert (end - start).days == 90
