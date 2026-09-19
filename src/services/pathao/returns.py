"""Pathao returns enrichment service.

Enriches a list of WooCommerce return-order rows with live Pathao tracking
status and return reason by calling the Pathao Aladdin API.

Uses the existing disk-cached batch_get_pathao_order_statuses infrastructure
to avoid rate-limiting, only making live API calls for uncached consignments.
"""

from __future__ import annotations

from src.services.pathao.status import (
    TERMINAL_PATHAO_STATUSES,
    _build_pathao_client,
    _load_pathao_disk_cache,
    _save_pathao_disk_cache,
)
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event


# ── Return-reason extraction ─────────────────────────────────────────────────


def get_pathao_return_reason(consignment_id: str) -> tuple[str, str]:
    """Fetch the Pathao return reason for a single consignment.

    Returns (order_status, return_reason).
    Pulls from disk cache if available and terminal; otherwise makes a live call.

    Parameters
    ----------
    consignment_id : str
        Pathao consignment ID.

    Returns
    -------
    (order_status, return_reason)
        order_status  : e.g. "returned", "return_delivered", "Returned" (human-readable)
        return_reason : e.g. "Customer not available", "Wrong product" or "" if N/A
    """
    if not consignment_id or not str(consignment_id).strip():
        return "", ""

    cid = str(consignment_id).strip()

    # Check disk cache first
    disk_cache = _load_pathao_disk_cache()
    cached_entry = disk_cache.get(cid)
    if cached_entry:
        data = cached_entry.get("data", {})
        inner = data.get("data", {}) if isinstance(data, dict) else {}
        status = str(inner.get("order_status", "") or data.get("order_status", "")).strip()
        reason = str(inner.get("return_reason", "") or inner.get("returnReason", "") or data.get("return_reason", "")).strip()
        if status.lower() in TERMINAL_PATHAO_STATUSES:
            # Permanent cache hit — return immediately
            return status, reason

    # Fetch from API
    client, error = _build_pathao_client()
    if error or client is None:
        return "", ""

    try:
        headers = client._get_headers()
        url = f"{client.base_url}/aladdin/api/v1/orders/{cid}/info"
        res = request_with_backoff("GET", url, headers=headers, timeout=10)

        if res.status_code != 200:
            return "", ""

        resp_json = res.json()

        # Update disk cache
        import time
        disk_cache[cid] = {"timestamp": time.time(), "data": resp_json}
        _save_pathao_disk_cache(disk_cache)

        inner = resp_json.get("data", {}) if isinstance(resp_json, dict) else {}
        status = str(inner.get("order_status", "") or "").strip()
        reason = str(
            inner.get("return_reason", "")
            or inner.get("returnReason", "")
            or inner.get("return_note", "")
            or ""
        ).strip()
        return status, reason

    except Exception as exc:
        log_system_event("PATHAO_RETURN_REASON_ERROR", f"{cid}: {exc}")
        return "", ""


def batch_get_pathao_return_info(
    consignment_ids: list[str],
    force_refresh: bool = False,
    max_workers: int = 3,
) -> dict[str, dict]:
    """Batch-fetch Pathao status + return reason for a list of consignment IDs.

    Returns a mapping: consignment_id -> {"status": str, "return_reason": str}

    Serves cached (terminal) statuses immediately; only queries the API for
    non-cached or stale entries to avoid rate limiting.

    Parameters
    ----------
    consignment_ids : list[str]
        Pathao consignment IDs to look up.
    force_refresh : bool
        If True, bypass the cache and always fetch from the API.
    max_workers : int
        Max concurrent API workers.
    """
    if not consignment_ids:
        return {}

    unique_cids = list(
        {str(c).strip() for c in consignment_ids if c and str(c).strip()}
    )
    results: dict[str, dict] = {}
    missing_cids: list[str] = []

    import time

    disk_cache = _load_pathao_disk_cache()

    for cid in unique_cids:
        if not force_refresh and cid in disk_cache:
            cached_entry = disk_cache[cid]
            cached_data = cached_entry.get("data", {})
            cached_ts = cached_entry.get("timestamp", 0)

            inner = cached_data.get("data", {}) if isinstance(cached_data, dict) else {}
            status = str(inner.get("order_status", "") or cached_data.get("order_status", "")).strip()
            reason = str(
                inner.get("return_reason", "")
                or inner.get("returnReason", "")
                or inner.get("return_note", "")
                or cached_data.get("return_reason", "")
                or ""
            ).strip()

            st_lower = status.lower()
            is_terminal = any(t in st_lower for t in TERMINAL_PATHAO_STATUSES)
            is_fresh = (time.time() - cached_ts) < 3600  # 1 hour TTL for non-terminal

            if is_terminal or is_fresh:
                results[cid] = {
                    "status": status if status else "Status Not Found",
                    "return_reason": reason,
                }
                continue

        missing_cids.append(cid)

    if not missing_cids:
        return results

    # Fetch uncached / stale entries concurrently
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(cid: str) -> tuple[str, dict]:
        status, reason = get_pathao_return_reason(cid)
        return cid, {
            "status": status if status else "Status Not Found",
            "return_reason": reason,
        }

    with ThreadPoolExecutor(max_workers=min(len(missing_cids), max_workers)) as executor:
        future_to_cid = {executor.submit(_fetch_one, cid): cid for cid in missing_cids}
        for future in as_completed(future_to_cid):
            cid = future_to_cid[future]
            try:
                _, info = future.result()
                results[cid] = info
            except Exception:
                results[cid] = {"status": "Status Not Found", "return_reason": ""}

    return results


def enrich_return_orders_with_pathao(
    orders: list[dict],
    force_refresh: bool = False,
) -> list[dict]:
    """Enrich a list of WooCommerce return order rows with Pathao data.

    Adds "Pathao Status" and "Return Reason (Pathao)" columns to each row.
    Rows without a Consignment ID receive "N/A" values.

    Parameters
    ----------
    orders : list[dict]
        Flat WC return order rows (output of fetch_wc_return_orders).
    force_refresh : bool
        Force Pathao API re-fetch even for cached statuses.

    Returns
    -------
    list[dict]
        Same list with "Pathao Status" and "Return Reason (Pathao)" added.
    """
    if not orders:
        return orders

    # Collect all unique consignment IDs
    cid_to_rows: dict[str, list[int]] = {}
    for idx, row in enumerate(orders):
        cid = str(row.get("Consignment ID", "")).strip()
        if cid:
            cid_to_rows.setdefault(cid, []).append(idx)

    if not cid_to_rows:
        # No consignment IDs — fill with N/A
        for row in orders:
            row["Pathao Status"] = "N/A (No Consignment ID)"
            row["Return Reason (Pathao)"] = ""
        return orders

    # Batch-fetch Pathao data
    pathao_info = batch_get_pathao_return_info(
        list(cid_to_rows.keys()), force_refresh=force_refresh
    )

    # Apply back to rows
    for idx, row in enumerate(orders):
        cid = str(row.get("Consignment ID", "")).strip()
        if cid and cid in pathao_info:
            info = pathao_info[cid]
            raw_status = info.get("status", "Status Not Found")
            row["Pathao Status"] = raw_status.replace("_", " ").title()
            row["Return Reason (Pathao)"] = info.get("return_reason", "")
        else:
            row["Pathao Status"] = "N/A (No Consignment ID)" if not cid else "Status Not Found"
            row["Return Reason (Pathao)"] = ""

    return orders
