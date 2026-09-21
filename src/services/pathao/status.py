"""Pathao order status and credential verification helpers with persistent disk caching."""

import json
import os
import time

from src.config.constants import RESOURCES_DIR
from src.config.settings import get_pathao_config
from src.services.pathao.client import PathaoClient
from src.utils.http import request_with_backoff

PATHAO_CACHE_FILE = os.path.join(RESOURCES_DIR, "pathao_status_cache.json")

TERMINAL_PATHAO_STATUSES = {
    "delivered",
    "returned",
    "return_delivered",
    "cancelled",
    "partial_delivered",
    "refunded",
    "failed",
    "status not found",
}


def _load_pathao_disk_cache() -> dict:
    """Load persistent Pathao status cache from disk."""
    if os.path.exists(PATHAO_CACHE_FILE):
        try:
            with open(PATHAO_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_pathao_disk_cache(cache: dict):
    """Save persistent Pathao status cache to disk."""
    try:
        os.makedirs(RESOURCES_DIR, exist_ok=True)
        with open(PATHAO_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_pathao_credentials() -> dict | None:
    """Extract Pathao credentials from supported config sources."""
    creds = get_pathao_config(required=False)
    required = ("base_url", "client_id", "client_secret", "username", "password")
    if not all(creds.get(key) for key in required):
        return None
    return creds


def _build_pathao_client() -> tuple[PathaoClient | None, str | None]:
    """Create a Pathao client from configured credentials."""
    creds = get_pathao_credentials()
    if not creds:
        return None, (
            "Pathao credentials are missing. Configure a complete [pathao] "
            "section in .streamlit/secrets.toml or set the PATHAO_* env vars."
        )

    try:
        return PathaoClient(**creds), None
    except Exception as exc:
        return None, f"Failed to initialize Pathao client: {exc}"


def get_pathao_order_status(
    consignment_id: str, force_refresh: bool = False, cache_ttl_seconds: int = 3600
) -> dict:
    """
    Fetch status of a Pathao order with persistent disk caching to prevent API rate limiting.

    Terminal statuses (Delivered, Returned, etc.) are served permanently from cache.
    Non-terminal statuses are cached for `cache_ttl_seconds` (default 1 hour).
    """
    if not consignment_id or not str(consignment_id).strip():
        return {"error": "Invalid consignment ID"}

    cid = str(consignment_id).strip()
    disk_cache = _load_pathao_disk_cache()

    if not force_refresh and cid in disk_cache:
        cached_entry = disk_cache[cid]
        cached_data = cached_entry.get("data", {})
        cached_ts = cached_entry.get("timestamp", 0)

        status_str = ""
        if isinstance(cached_data, dict):
            status_str = str(
                cached_data.get("data", {}).get("order_status", "")
                or cached_data.get("order_status", "")
            ).lower()

        # Terminal status -> Return permanently from cache
        if any(term in status_str for term in TERMINAL_PATHAO_STATUSES):
            return cached_data

        # Non-terminal status -> Check TTL (1 hour)
        if time.time() - cached_ts < cache_ttl_seconds:
            return cached_data

    # Fetch fresh status from Pathao API
    client, error = _build_pathao_client()
    if error:
        if cid in disk_cache:
            return disk_cache[cid].get("data", {})
        return {"error": error}

    try:
        headers = client._get_headers()
        if not client.access_token:
            if cid in disk_cache:
                return disk_cache[cid].get("data", {})
            return {
                "error": "Authentication failed. Pathao access token is unavailable."
            }

        status_url = f"{client.base_url}/aladdin/api/v1/orders/{cid}/info"
        status_response = request_with_backoff(
            "GET", status_url, headers=headers, timeout=10
        )

        if status_response.status_code == 200:
            resp_json = status_response.json()
            disk_cache[cid] = {
                "timestamp": time.time(),
                "data": resp_json,
            }
            _save_pathao_disk_cache(disk_cache)
            return resp_json

        if cid in disk_cache:
            return disk_cache[cid].get("data", {})

        return {
            "error": f"Failed to fetch status: {status_response.status_code} - {status_response.text}"
        }

    except Exception as exc:
        if cid in disk_cache:
            return disk_cache[cid].get("data", {})
        return {"error": f"Request failed: {exc}"}


def batch_get_pathao_order_statuses(
    consignment_ids: list, force_refresh: bool = False, max_workers: int = 3
) -> dict[str, str]:
    """
    Fetch statuses for a list of consignment IDs in batch, serving cached records first
    and only querying Pathao API for uncached orders to avoid blocking/rate-limiting.
    """
    if not consignment_ids:
        return {}

    unique_cids = list(
        set([str(c).strip() for c in consignment_ids if c and str(c).strip()])
    )
    results = {}
    missing_cids = []

    disk_cache = _load_pathao_disk_cache()

    for cid in unique_cids:
        if not force_refresh and cid in disk_cache:
            cached_entry = disk_cache[cid]
            cached_data = cached_entry.get("data", {})
            cached_ts = cached_entry.get("timestamp", 0)

            st_str = ""
            if isinstance(cached_data, dict):
                st_str = str(
                    cached_data.get("data", {}).get("order_status", "")
                    or cached_data.get("order_status", "")
                ).strip()

            st_lower = st_str.lower()
            if any(term in st_lower for term in TERMINAL_PATHAO_STATUSES) or (
                time.time() - cached_ts < 3600
            ):
                results[cid] = st_str if st_str else "Status Not Found"
                continue

        missing_cids.append(cid)

    if not missing_cids:
        return results

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(cid):
        res = get_pathao_order_status(cid, force_refresh=force_refresh)
        status_val = "Status Not Found"
        if isinstance(res, dict):
            if (
                "data" in res
                and isinstance(res["data"], dict)
                and "order_status" in res["data"]
            ):
                status_val = res["data"]["order_status"]
            elif "order_status" in res:
                status_val = res["order_status"]
        return cid, status_val

    with ThreadPoolExecutor(
        max_workers=min(len(missing_cids), max_workers)
    ) as executor:
        future_to_cid = {executor.submit(_fetch_one, cid): cid for cid in missing_cids}
        for future in as_completed(future_to_cid):
            cid = future_to_cid[future]
            try:
                _, status_val = future.result()
                results[cid] = status_val
            except Exception:
                results[cid] = "Status Not Found"

    return results


# Alias for backward/naming compatibility
bulk_get_pathao_order_statuses = batch_get_pathao_order_statuses


def fetch_pending_pathao_orders(
    client, max_pages: int = 5
) -> tuple[list[dict], str | None]:
    """Fetch orders directly from Pathao API and filter for pending / in-transit orders.

    Returns (pending_orders, error_message).
    """
    if client is None:
        return [], "Pathao client not initialized."

    pending_list = []
    seen_consignments = set()

    for page in range(1, max_pages + 1):
        orders, meta, err = client.get_orders(page=page, limit=50)
        if err:
            return pending_list, err
        if not orders:
            break

        for o in orders:
            if not isinstance(o, dict):
                continue
            cid = str(o.get("consignment_id", "")).strip()
            if not cid or cid in seen_consignments:
                continue

            raw_status = str(o.get("order_status", "")).strip()
            st_lower = raw_status.lower()

            # Filter out terminal statuses (delivered, returned, cancelled, etc.)
            if st_lower in TERMINAL_PATHAO_STATUSES or not st_lower:
                continue

            seen_consignments.add(cid)
            collected = o.get("collected_amount", 0)
            try:
                amt = float(collected) if collected is not None else 0.0
            except (ValueError, TypeError):
                amt = 0.0

            pending_list.append(
                {
                    "Consignment ID": cid,
                    "Order ID": str(o.get("merchant_order_id", "")).strip(),
                    "Customer Name": str(o.get("recipient_name", "")).strip(),
                    "Phone": str(o.get("recipient_phone", "")).strip(),
                    "Address": str(o.get("recipient_address", "")).strip(),
                    "Date": str(o.get("created_at", "")).split(" ")[0],
                    "COD Amount": amt,
                    "Status": raw_status.replace("_", " ").title(),
                    "Store": str(o.get("store_name", "")).strip(),
                }
            )

        if meta and meta.get("last_page") is not None:
            if page >= int(meta["last_page"]):
                break

    return pending_list, None


def fetch_wc_pending_in_pathao(wc_df, force_refresh: bool = False) -> list[dict]:
    """Filter WooCommerce orders with Pathao tracking IDs whose Pathao status is pending/in-transit."""
    import pandas as pd

    if wc_df is None or wc_df.empty:
        return []

    # Find tracking column
    tracking_col = next(
        (
            c
            for c in wc_df.columns
            if any(k in str(c).lower() for k in ["consignment", "tracking", "pathao"])
        ),
        None,
    )
    if not tracking_col:
        return []

    valid_mask = (
        wc_df[tracking_col].notna()
        & (wc_df[tracking_col].astype(str).str.strip() != "")
        & (wc_df[tracking_col].astype(str).str.lower() != "nan")
    )
    filtered = wc_df[valid_mask].copy()
    if filtered.empty:
        return []

    id_col = next(
        (
            c
            for c in filtered.columns
            if "order id" in str(c).lower() or "order number" in str(c).lower()
        ),
        filtered.columns[0],
    )
    name_col = next((c for c in filtered.columns if "name" in str(c).lower()), "")
    phone_col = next((c for c in filtered.columns if "phone" in str(c).lower()), "")
    date_col = next((c for c in filtered.columns if "date" in str(c).lower()), "")
    amount_col = next(
        (
            c
            for c in filtered.columns
            if "total" in str(c).lower() or "amount" in str(c).lower()
        ),
        "",
    )

    cids = filtered[tracking_col].astype(str).str.strip().unique().tolist()
    status_map = bulk_get_pathao_order_statuses(cids, force_refresh=force_refresh)

    results = []
    seen_cids = set()
    for _, row in filtered.iterrows():
        cid = str(row[tracking_col]).strip()
        if not cid or cid in seen_cids:
            continue

        p_status = status_map.get(cid, "Unknown")
        st_lower = p_status.lower().strip()

        if st_lower in TERMINAL_PATHAO_STATUSES or st_lower == "status not found":
            continue

        seen_cids.add(cid)
        amt_raw = row[amount_col] if amount_col else 0
        try:
            amt = float(amt_raw) if pd.notna(amt_raw) else 0.0
        except (ValueError, TypeError):
            amt = 0.0

        results.append(
            {
                "Consignment ID": cid,
                "Order ID": str(row[id_col]) if id_col else "",
                "Customer Name": str(row[name_col]) if name_col else "",
                "Phone": str(row[phone_col]) if phone_col else "",
                "Address": str(
                    row.get("Address 1&2 (Shipping)", row.get("Shipping Address", ""))
                ),
                "Date": str(row[date_col]).split(" ")[0] if date_col else "",
                "COD Amount": amt,
                "Status": p_status.replace("_", " ").title(),
                "Store": "WooCommerce",
            }
        )

    return results
