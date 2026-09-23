"""Steadfast Courier REST API Client for DEEN-OPS.

Integrates with Steadfast Courier (Bangladesh) for automated consignment booking,
tracking, and delivery reconciliation alongside Pathao.
"""

from __future__ import annotations

import os
from typing import Any, Optional


from src.services.courier.base import BaseCourierClient
from src.utils.http import request_with_backoff
from src.utils.logging import log_error, log_system_event
from src.utils.text import normalize_phone_number

STEADFAST_BASE_URL = "https://portal.steadfast.com.bd/api/v1"


class SteadfastCourierClient(BaseCourierClient):
    """Client for Steadfast Courier merchant REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: str = STEADFAST_BASE_URL,
    ) -> None:
        self.base_url = (base_url or STEADFAST_BASE_URL).rstrip("/")
        # Fallback to environment variables if not passed
        self.api_key = api_key or os.getenv("STEADFAST_API_KEY", "")
        self.secret_key = secret_key or os.getenv("STEADFAST_SECRET_KEY", "")

    @property
    def is_configured(self) -> bool:
        """Returns True if valid API credentials are present."""
        return bool(self.api_key and self.secret_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Api-Key": self.api_key,
            "Secret-Key": self.secret_key,
            "Content-Type": "application/json",
        }

    def create_order(
        self,
        order_id: str | int,
        recipient_name: str,
        recipient_phone: str,
        recipient_address: str,
        amount_to_collect: float | int,
        item_description: str = "",
        special_instruction: str = "",
        store_id: Optional[int | str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Book a parcel consignment with Steadfast Courier.

        Returns a standardized dictionary:
          {"success": bool, "consignment_id": str, "tracking_code": str, "error": Optional[str]}
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "Steadfast Courier credentials not configured (STEADFAST_API_KEY / STEADFAST_SECRET_KEY)",
            }

        norm_phone = normalize_phone_number(recipient_phone)
        if not norm_phone or len(norm_phone) != 11:
            return {
                "success": False,
                "error": f"Invalid recipient phone number: '{recipient_phone}' (must be 11-digit BD mobile)",
            }

        payload = {
            "invoice": str(order_id),
            "recipient_name": str(recipient_name).strip(),
            "recipient_phone": norm_phone,
            "recipient_address": str(recipient_address).strip(),
            "cod_amount": int(round(float(amount_to_collect))),
            "note": str(item_description or special_instruction).strip(),
        }

        url = f"{self.base_url}/create_order"
        try:
            response = request_with_backoff(
                "POST", url, headers=self._headers(), json=payload, timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == 200 and "consignment" in data:
                    c = data["consignment"]
                    cid = str(c.get("consignment_id", ""))
                    code = str(c.get("tracking_code", ""))
                    log_system_event(
                        "STEADFAST_ORDER_CREATED", f"Invoice: {order_id} -> CID: {cid}"
                    )
                    return {
                        "success": True,
                        "consignment_id": cid,
                        "tracking_code": code,
                        "status": str(c.get("status", "in_review")),
                        "data": c,
                    }
                return {
                    "success": False,
                    "error": data.get("message") or "Steadfast returned error response",
                }
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
            }
        except Exception as exc:
            log_error(exc, context="Steadfast create_order")
            return {"success": False, "error": str(exc)}

    def get_order_status(
        self,
        consignment_id: Optional[str] = None,
        order_id: Optional[str | int] = None,
    ) -> dict[str, Any]:
        """Check consignment status by invoice (order_id) or consignment_id."""
        if not self.is_configured:
            return {"success": False, "error": "Steadfast Courier not configured"}

        if order_id:
            url = f"{self.base_url}/status_by_invoice/{order_id}"
        elif consignment_id:
            url = f"{self.base_url}/status_by_cid/{consignment_id}"
        else:
            return {
                "success": False,
                "error": "Either order_id or consignment_id required",
            }

        try:
            response = request_with_backoff(
                "GET", url, headers=self._headers(), timeout=12
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == 200:
                    delivery_status = str(data.get("delivery_status", "")).lower()
                    return {
                        "success": True,
                        "delivery_status": delivery_status,
                        "data": data,
                    }
                return {
                    "success": False,
                    "error": data.get("message", "Status lookup failed"),
                }
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_stores(self) -> list[dict[str, Any]]:
        """Steadfast uses single merchant profile; returns default central warehouse store."""
        return [{"store_id": 1, "store_name": "Central Warehouse (Steadfast)"}]
