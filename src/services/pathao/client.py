import hashlib
import json
import math
import os
import tempfile
import time

from requests.exceptions import HTTPError, RequestException

from src.services.pathao.orders import PathaoOrderError
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event


class PathaoClient:
    def __init__(self, base_url, client_id, client_secret, username, password):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.account_scope = hashlib.sha256(
            json.dumps(
                [self.base_url, self.client_id, self.username], ensure_ascii=False
            ).encode()
        ).hexdigest()
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.token_file = "pathao_token.json"
        self._load_token()

    def _save_token(self, data):
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("access_token"), str)
            or not data["access_token"].strip()
        ):
            raise ValueError("Pathao did not return an access token.")
        expires_in = float(data.get("expires_in", 3600))
        if not math.isfinite(expires_in) or expires_in <= 60:
            raise ValueError("Pathao did not return a usable token lifetime.")
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        # expires_in is usually in seconds
        self.expires_at = time.time() + expires_in - 60  # 1 min buffer

        token_data = {
            "account_scope": self.account_scope,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }
        # mkstemp creates a private file; replace atomically so concurrent readers
        # cannot consume a partially written token cache.
        fd, temporary = tempfile.mkstemp(
            prefix=".pathao-token-",
            dir=os.path.dirname(os.path.abspath(self.token_file)),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(token_data, f)
            os.replace(temporary, self.token_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load_token(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                # Old unscoped tokens require a fresh login, as do tokens issued
                # for another merchant or API environment.
                if data.get("account_scope") != self.account_scope:
                    return
                access_token = data.get("access_token")
                expires_at = float(data.get("expires_at", 0))
                if not isinstance(access_token, str) or not access_token.strip():
                    return
                if not math.isfinite(expires_at):
                    return
                self.access_token = access_token
                refresh_token = data.get("refresh_token")
                self.refresh_token = (
                    refresh_token if isinstance(refresh_token, str) else None
                )
                self.expires_at = expires_at
            except Exception:
                pass

    def ensure_token(self):
        if self.access_token and time.time() < self.expires_at:
            return True
        # Do not keep an expired token available after authentication fails.
        self.access_token = None
        if self.refresh_token:
            authenticated = self.refresh_access_token()
        else:
            authenticated = self.issue_access_token()
        return bool(
            authenticated and self.access_token and time.time() < self.expires_at
        )

    def issue_access_token(self):
        url = f"{self.base_url}/aladdin/api/v1/issue-token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
        }
        try:
            res = request_with_backoff("POST", url, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                self._save_token(data)
                return True
            else:
                log_system_event("PATHAO_AUTH_FAILED", f"HTTP {res.status_code}")
                return False
        except Exception as e:
            log_system_event("PATHAO_AUTH_ERROR", type(e).__name__)
            return False

    def refresh_access_token(self):
        url = f"{self.base_url}/aladdin/api/v1/issue-token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            res = request_with_backoff("POST", url, json=payload, timeout=10)
            if res.status_code == 200:
                self._save_token(res.json())
                return True
            else:
                log_system_event("PATHAO_REFRESH_FAILED", f"HTTP {res.status_code}")
                return self.issue_access_token()
        except Exception:
            return self.issue_access_token()

    def _get_headers(self):
        if not self.ensure_token():
            raise PathaoOrderError(
                "Pathao authentication failed. Check the API credentials and reconnect."
            )
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_stores(self):
        """Return every pickup store, following pagination without trusting URLs."""
        url = f"{self.base_url}/aladdin/api/v1/stores"
        stores = []
        seen_ids = set()
        try:
            headers = self._get_headers()
            for page in range(1, 101):
                response = request_with_backoff(
                    "GET", url, headers=headers, params={"page": page}, timeout=10
                )
                if response.status_code != 200:
                    return [], (
                        f"Could not load pickup stores (HTTP {response.status_code}). "
                        "Check Pathao access and try again."
                    )
                document = response.json()
                if not isinstance(document, dict) or document.get("type") == "error":
                    return [], (
                        "Pathao did not return a usable store list. "
                        "Check merchant access and try again."
                    )
                container = document.get("data")
                rows = (
                    container.get("data") if isinstance(container, dict) else container
                )
                if not isinstance(rows, list) or any(
                    not isinstance(row, dict) for row in rows
                ):
                    return [], (
                        "Pathao returned an invalid store list. "
                        "Try loading pickup stores again."
                    )
                for row in rows:
                    store_id = str(row.get("store_id", ""))
                    if store_id and store_id not in seen_ids:
                        stores.append(row)
                        seen_ids.add(store_id)
                if not isinstance(container, dict):
                    return stores, None
                last_page = container.get("last_page")
                if last_page is not None:
                    if int(last_page) <= page:
                        return stores, None
                elif not container.get("next_page_url"):
                    return stores, None
                if not rows or int(container.get("current_page", page)) != page:
                    return [], (
                        "Pathao store pagination was incomplete. "
                        "Try loading pickup stores again."
                    )
            return [], (
                "Pathao returned too many store pages. "
                "Contact support to verify your store list."
            )
        except PathaoOrderError as exc:
            return [], str(exc)
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return [], (
                f"Could not load pickup stores (HTTP {status}). "
                "Check credentials and merchant access, then try again."
            )
        except (RequestException, ValueError, TypeError, AttributeError, OverflowError):
            return [], (
                "Could not load pickup stores. Check the connection and try again."
            )

    @staticmethod
    def _order_failure(status, document=None):
        """Expose only known field names, never echoed customer data or tokens."""
        uncertain = status == 408 or status >= 500 or status < 400
        if uncertain:
            return PathaoOrderError(
                f"Pathao order outcome is unconfirmed (HTTP {status}). "
                "Check the merchant portal for this merchant order ID before retrying.",
                uncertain=True,
            )
        fields = []
        if isinstance(document, dict) and isinstance(document.get("errors"), dict):
            allowed = {
                "store_id",
                "merchant_order_id",
                "recipient_name",
                "recipient_phone",
                "recipient_address",
                "delivery_type",
                "item_type",
                "item_quantity",
                "item_weight",
                "amount_to_collect",
                "special_instruction",
                "item_description",
            }
            fields = sorted(allowed.intersection(document["errors"]))
        detail = (
            f" Review: {', '.join(fields)}."
            if fields
            else " Review the order details and pickup store."
        )
        if status in (401, 403):
            detail = " Check Pathao credentials and merchant permissions."
        elif status == 429:
            detail = " Pathao is rate limiting requests; wait before retrying."
        return PathaoOrderError(f"Pathao rejected the order (HTTP {status}).{detail}")

    def create_order(self, payload):
        """Create once; an unknown outcome must be reconciled before retrying."""
        # Authentication completes before the non-idempotent request starts.
        headers = self._get_headers()
        try:
            response = request_with_backoff(
                "POST",
                f"{self.base_url}/aladdin/api/v1/orders",
                headers=headers,
                json=payload,
                timeout=30,
                max_attempts=1,
                allow_redirects=False,
            )
        except HTTPError as exc:
            response = exc.response
            if response is None:
                raise PathaoOrderError(
                    "Pathao order outcome is unconfirmed. Check the merchant "
                    "portal for this merchant order ID before retrying.",
                    uncertain=True,
                ) from None
            try:
                document = response.json()
            except ValueError:
                document = None
            raise self._order_failure(response.status_code, document) from None
        except RequestException:
            raise PathaoOrderError(
                "Connection interrupted during order creation. Check the merchant "
                "portal for this merchant order ID before retrying.",
                uncertain=True,
            ) from None

        try:
            document = response.json()
        except ValueError:
            document = None
        if not 200 <= response.status_code < 300:
            raise self._order_failure(response.status_code, document)
        if isinstance(document, dict) and document.get("type") == "error":
            try:
                status = int(document.get("code", 422))
            except (ValueError, TypeError):
                status = 422
            raise self._order_failure(status, document)
        data = document.get("data") if isinstance(document, dict) else None
        consignment = data.get("consignment_id") if isinstance(data, dict) else None
        if not isinstance(consignment, str) or not consignment.strip():
            raise PathaoOrderError(
                "Pathao returned no confirmed consignment ID. Check the merchant "
                "portal for this merchant order ID before retrying.",
                uncertain=True,
            )
        return {**data, "consignment_id": consignment.strip()}

    def get_cities(self):
        url = f"{self.base_url}/aladdin/api/v1/cities"
        try:
            res = request_with_backoff(
                "GET", url, headers=self._get_headers(), timeout=10
            )
            if res.status_code == 200:
                return res.json().get("data", {}).get("data", []), None
            else:
                return [], f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            return [], f"Connection Error: {e}"

    def get_zones(self, city_id):
        url = f"{self.base_url}/aladdin/api/v1/cities/{city_id}/zone-list"
        try:
            res = request_with_backoff(
                "GET", url, headers=self._get_headers(), timeout=10
            )
            if res.status_code == 200:
                return res.json().get("data", {}).get("data", []), None
            else:
                return [], f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            return [], f"Connection Error: {e}"

    def get_areas(self, zone_id):
        url = f"{self.base_url}/aladdin/api/v1/zones/{zone_id}/area-list"
        try:
            res = request_with_backoff(
                "GET", url, headers=self._get_headers(), timeout=10
            )
            if res.status_code == 200:
                return res.json().get("data", {}).get("data", []), None
            else:
                return [], f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            return [], f"Connection Error: {e}"

    def get_orders(
        self,
        page: int = 1,
        limit: int = 50,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict], dict | None, str | None]:
        """Fetch a page of orders from the Pathao Aladdin API.

        Returns (orders_list, pagination_metadata, error_message).
        """
        url = f"{self.base_url}/aladdin/api/v1/orders"
        params: dict = {"page": page}
        if limit:
            params["limit"] = limit
        if search and str(search).strip():
            params["search"] = str(search).strip()
        if status and str(status).strip():
            params["status"] = str(status).strip()

        try:
            headers = self._get_headers()
            res = request_with_backoff(
                "GET", url, headers=headers, params=params, timeout=15
            )
            if res.status_code != 200:
                return (
                    [],
                    None,
                    f"Pathao API error (HTTP {res.status_code}): {res.text[:200]}",
                )
            doc = res.json()
            data_container = doc.get("data", {})
            if isinstance(data_container, dict):
                orders = data_container.get("data", [])
                meta = {
                    "current_page": data_container.get("current_page", page),
                    "last_page": data_container.get("last_page", 1),
                    "total": data_container.get("total", len(orders)),
                }
                return orders, meta, None
            elif isinstance(data_container, list):
                return data_container, None, None
            return [], None, None
        except PathaoOrderError as exc:
            return [], None, str(exc)
        except Exception as e:
            return [], None, f"Connection Error: {e}"
