"""WooCommerce returns service — fetch refunded / cancelled / return orders by date range.

Fetches orders whose statuses indicate a return or cancellation event:
- refunded, cancelled, failed  (valid native WC statuses)

For Pathao-returned orders, the correct flow is:
1. Fetch Pathao orders with status="returned" → get merchant_order_id list
2. Fetch those WC orders by ID (they are "completed" in WC, not "returned")

Supports filtering by:
- Date range (after / before, BD-local → UTC conversion applied internally)
- Optional order number list
- Optional WC status list override
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from requests.auth import HTTPBasicAuth

from src.config.settings import get_woocommerce_config
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event

# ── Constants ────────────────────────────────────────────────────────────────

# Valid WooCommerce native return/cancel statuses (no "returned" — that's Pathao-side)
DEFAULT_RETURN_STATUSES = [
    "refunded",
    "cancelled",
    "failed",
]

# WC REST API fields to request (minimise payload)
_WC_FIELDS = (
    "id,number,date_created,date_created_gmt,date_modified,date_modified_gmt,"
    "status,billing,shipping,payment_method_title,line_items,total,"
    "discount_total,fee_lines,coupon_lines,meta_data,refunds"
)

# Known meta_data keys that store Pathao consignment IDs (matches woocommerce/client.py)
_CONSIGNMENT_META_KEYS = {
    "ptc_consignment_id",
    "pathao_consignment_id",
    "consignment_id",
    "tracking_number",
    "tracking_code",
    "_pathao_consignment_id",
    "pathao_tracking",
    "shipment_id",
    "_tracking_number",
    "courier_consignment_id",
}


# ── Internal helpers ─────────────────────────────────────────────────────────


def _extract_consignment_id(order: dict) -> str:
    """Extract Pathao consignment ID from WooCommerce order meta_data."""
    for meta in order.get("meta_data", []):
        k = str(meta.get("key", "")).lower().strip()
        if k in _CONSIGNMENT_META_KEYS:
            v = str(meta.get("value", "")).strip()
            if v and v.lower() not in {"none", "nan", "null", "n/a", "0", ""}:
                return v
    return ""


def _bd_to_utc_iso(dt: datetime) -> str:
    """Convert a BD-local (UTC+6) naive datetime to a UTC ISO string for WC API."""
    utc_dt = dt - timedelta(hours=6)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")


def _flatten_return_order(order: dict) -> list[dict]:
    """Flatten a WooCommerce return/cancel order into one row per line item.

    Returns a list of dicts, each representing one product in the order.
    """
    oid = order.get("id")
    onum = order.get("number")
    raw_date = order.get("date_created_gmt") or order.get("date_created", "")
    if (
        raw_date
        and isinstance(raw_date, str)
        and not raw_date.endswith("Z")
        and "+" not in raw_date
        and "-" not in raw_date[10:]
    ):
        raw_date = raw_date + "Z"

    wc_status = str(order.get("status", "")).strip()
    bill = order.get("billing", {})
    ship = order.get("shipping", {})
    customer_name = f"{bill.get('first_name', '')} {bill.get('last_name', '')}".strip()
    phone = bill.get("phone", "")
    pmt = order.get("payment_method_title", "")
    order_total = order.get("total", "0")

    consignment_id = _extract_consignment_id(order)

    # Shipping address resolution (prefer shipping, fall back to billing)
    ship_city = str(ship.get("city") or bill.get("city") or "").strip()
    ship_addr = str(ship.get("address_1") or bill.get("address_1") or "").strip()

    # Extract refund notes if any
    refund_note = ""
    refunds = order.get("refunds", [])
    if refunds and isinstance(refunds, list):
        reasons = [str(r.get("reason", "")).strip() for r in refunds if r.get("reason")]
        refund_note = "; ".join(filter(None, reasons))

    line_items = order.get("line_items", [])
    if not line_items:
        # Return one row per order even if no line items (edge case)
        return [
            {
                "Order ID": oid,
                "Order Number": onum,
                "Order Date": raw_date,
                "WC Return Status": wc_status,
                "Consignment ID": consignment_id,
                "Product Description": "",
                "SKU": "",
                "Quantity": 0,
                "Item Price": 0.0,
                "Order Total": order_total,
                "Customer Name": customer_name,
                "Phone": phone,
                "City": ship_city,
                "Address": ship_addr,
                "Payment Method": pmt,
                "Refund Reason (WC)": refund_note,
            }
        ]

    rows = []
    for item in line_items:
        qty_raw = item.get("quantity", 1)
        try:
            qty = int(float(str(qty_raw))) if qty_raw else 1
        except (ValueError, TypeError):
            qty = 1

        item_total = float(item.get("total", 0) or 0)
        item_qty = max(qty, 1)
        unit_price = (
            item_total / item_qty if item_total else float(item.get("price", 0) or 0)
        )

        rows.append(
            {
                "Order ID": oid,
                "Order Number": onum,
                "Order Date": raw_date,
                "WC Return Status": wc_status,
                "Consignment ID": consignment_id,
                "Product Description": item.get("name", ""),
                "SKU": item.get("sku", ""),
                "Quantity": qty,
                "Item Price": round(unit_price, 2),
                "Order Total": order_total,
                "Customer Name": customer_name,
                "Phone": phone,
                "City": ship_city,
                "Address": ship_addr,
                "Payment Method": pmt,
                "Refund Reason (WC)": refund_note,
            }
        )
    return rows


def _fetch_page(
    url: str, params: dict, auth: HTTPBasicAuth, page: int
) -> tuple[list[dict], int]:
    """Fetch one page of WC orders. Returns (rows, total_pages)."""
    res = request_with_backoff(
        "GET", url, params={**params, "page": page}, auth=auth, timeout=15
    )
    res.raise_for_status()
    data = json.loads(res.content.decode("utf-8-sig"))
    rows: list[dict] = []
    for order in data:
        rows.extend(_flatten_return_order(order))
    total_pages = int(res.headers.get("X-WP-TotalPages", 1))
    return rows, total_pages


# ── Public API ────────────────────────────────────────────────────────────────


def fetch_wc_return_orders(
    after_dt: datetime,
    before_dt: datetime,
    order_numbers: list[str] | None = None,
    statuses: list[str] | None = None,
    include_pathao_statuses: bool = True,
) -> tuple[list[dict], str | None]:
    """Fetch WooCommerce return / cancellation orders in a given time range.

    Parameters
    ----------
    after_dt : datetime
        Start of range (BD-local naive datetime, UTC+6).
    before_dt : datetime
        End of range (BD-local naive datetime, UTC+6).
    order_numbers : list[str] | None
        Optional list of WC order numbers to filter to (case-insensitive).
    statuses : list[str] | None
        WC status list override. Defaults to DEFAULT_RETURN_STATUSES.
    include_pathao_statuses : bool
        If True, the consignment_id column is populated for Pathao enrichment.

    Returns
    -------
    (rows, error_message)
        rows: list of flat order dicts ready for DataFrame conversion.
        error_message: None on success, str on failure.
    """
    cfg = get_woocommerce_config(required=False)
    if not cfg or not all(
        cfg.get(k) for k in ("store_url", "consumer_key", "consumer_secret")
    ):
        return (
            [],
            "WooCommerce credentials are not configured. Add [woocommerce] in secrets.toml.",
        )

    endpoint = f"{cfg['store_url'].rstrip('/')}/wp-json/wc/v3/orders"
    auth = HTTPBasicAuth(cfg["consumer_key"], cfg["consumer_secret"])

    # Convert BD-local datetimes to UTC for the WC API
    after_utc = _bd_to_utc_iso(after_dt)
    before_utc = _bd_to_utc_iso(before_dt)

    selected_statuses = statuses if statuses else DEFAULT_RETURN_STATUSES
    # WC REST API accepts a comma-separated status string
    status_str = ",".join(selected_statuses)

    params: dict[str, Any] = {
        "per_page": 100,
        "after": after_utc,
        "before": before_utc,
        "status": status_str,
        "orderby": "date",
        "order": "desc",
        "_fields": _WC_FIELDS,
    }

    try:
        rows, total_pages = _fetch_page(endpoint, params, auth, page=1)
    except Exception as exc:
        log_system_event("WC_RETURNS_FETCH_ERROR", str(exc))
        return [], f"Failed to connect to WooCommerce: {exc}"

    # Fetch remaining pages concurrently
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=min(total_pages, 4)) as executor:
            futures = [
                executor.submit(_fetch_page, endpoint, params, auth, pg)
                for pg in range(2, total_pages + 1)
            ]
            for future in futures:
                try:
                    extra_rows, _ = future.result()
                    rows.extend(extra_rows)
                except Exception as exc:
                    log_system_event("WC_RETURNS_PAGE_ERROR", str(exc))

    # Optional order-number filter (applied post-fetch since WC REST does not support it directly)
    if order_numbers:
        normalised = {
            str(on).strip().lower() for on in order_numbers if str(on).strip()
        }
        rows = [
            r
            for r in rows
            if str(r.get("Order Number", "")).strip().lower() in normalised
        ]

    return rows, None


def fetch_wc_orders_by_ids(
    order_ids: list[int | str],
    pathao_meta: dict[str, dict] | None = None,
) -> tuple[list[dict], str | None]:
    """Fetch WooCommerce orders by their numeric order IDs.

    Uses the WC REST API ``include`` parameter to retrieve specific orders
    regardless of their status (Pathao-returned orders are ``completed`` in WC).

    Parameters
    ----------
    order_ids : list
        List of WC order IDs (integers or strings) to fetch.
    pathao_meta : dict | None
        Optional mapping of WC order number -> Pathao metadata dict
        (keys: ``consignment_id``, ``pathao_status``, ``return_reason``).
        If provided, these fields are merged into each returned row.

    Returns
    -------
    (rows, error_message)
    """
    if not order_ids:
        return [], None

    cfg = get_woocommerce_config(required=False)
    if not cfg or not all(
        cfg.get(k) for k in ("store_url", "consumer_key", "consumer_secret")
    ):
        return [], "WooCommerce credentials are not configured."

    endpoint = f"{cfg['store_url'].rstrip('/')}/wp-json/wc/v3/orders"
    auth = HTTPBasicAuth(cfg["consumer_key"], cfg["consumer_secret"])

    # WC REST supports `include` as a comma-separated list of order IDs
    # (max 100 per page — batch if needed)
    unique_ids = list({str(oid).strip() for oid in order_ids if str(oid).strip()})
    all_rows: list[dict] = []

    # Process in batches of 100 (WC per_page max)
    batch_size = 100
    for i in range(0, len(unique_ids), batch_size):
        batch = unique_ids[i : i + batch_size]
        params: dict[str, Any] = {
            "per_page": batch_size,
            "include": ",".join(batch),
            "orderby": "date",
            "order": "desc",
            "_fields": _WC_FIELDS,
        }
        try:
            rows, _ = _fetch_page(endpoint, params, auth, page=1)
            all_rows.extend(rows)
        except Exception as exc:
            log_system_event("WC_RETURNS_BY_ID_ERROR", f"batch {i}: {exc}")
            return all_rows, f"Failed to connect to WooCommerce: {exc}"

    # Merge Pathao metadata if provided
    if pathao_meta and all_rows:
        for row in all_rows:
            wc_num = str(row.get("Order Number", "")).strip()
            meta = pathao_meta.get(wc_num, {})
            row.setdefault("Consignment ID", meta.get("consignment_id", ""))
            row["Pathao Status"] = meta.get("pathao_status", "Returned")
            row["Return Reason (Pathao)"] = meta.get("return_reason", "")

    return all_rows, None


def fetch_pathao_returned_orders(
    after_dt: datetime,
    before_dt: datetime,
    max_pages: int = 20,
) -> tuple[list[dict], str | None]:
    """Fetch orders that Pathao has marked as ``returned`` within a date range.

    Uses the Pathao Aladdin API to get returned parcels, then looks up the
    corresponding WooCommerce orders (which are ``completed`` in WC) by their
    merchant_order_id (= WC order number / order ID).

    Parameters
    ----------
    after_dt : datetime
        Start of range (BD-local naive datetime, UTC+6).
    before_dt : datetime
        End of range (BD-local naive datetime, UTC+6).
    max_pages : int
        Maximum Pathao API pages to fetch (50 orders per page).

    Returns
    -------
    (rows, error_message)
        rows: flat list of order dicts with all standard fields plus
              ``Pathao Status`` and ``Return Reason (Pathao)``.
        error_message: None on success, str on failure.
    """
    from src.services.pathao.status import _build_pathao_client

    client, err = _build_pathao_client()
    if err or client is None:
        return [], f"Pathao authentication failed: {err}"

    # Collect all Pathao returned orders, paginating until exhausted or max_pages
    pathao_rows: list[dict] = []
    seen_cids: set[str] = set()

    for page in range(1, max_pages + 1):
        try:
            orders, meta, api_err = client.get_orders(
                page=page, limit=50, status="returned"
            )
        except Exception as exc:
            log_system_event("PATHAO_RETURNED_FETCH_ERROR", str(exc))
            break

        if api_err:
            log_system_event("PATHAO_RETURNED_API_ERROR", api_err)
            break

        if not orders:
            break

        for o in orders:
            if not isinstance(o, dict):
                continue

            cid = str(o.get("consignment_id", "")).strip()
            if not cid or cid in seen_cids:
                continue

            # Date filter: Pathao returns created_at as "YYYY-MM-DD HH:MM:SS"
            created_raw = str(
                o.get("created_at", "") or o.get("updated_at", "")
            ).strip()
            if created_raw:
                try:
                    # Parse Pathao datetime (assumed BD local, UTC+6)
                    created_dt = datetime.strptime(
                        created_raw[:19], "%Y-%m-%d %H:%M:%S"
                    )
                    if created_dt < after_dt or created_dt > before_dt:
                        continue
                except ValueError:
                    pass  # Keep order if date can't be parsed

            seen_cids.add(cid)
            merchant_oid = str(o.get("merchant_order_id", "")).strip()
            return_reason = str(
                o.get("return_reason", "") or o.get("return_note", "")
            ).strip()

            collected = o.get("collected_amount", 0)
            try:
                amt = float(collected) if collected is not None else 0.0
            except (ValueError, TypeError):
                amt = 0.0

            pathao_rows.append(
                {
                    "_wc_order_ref": merchant_oid,  # used for WC lookup
                    "Consignment ID": cid,
                    "Order Number": merchant_oid,
                    "Pathao Status": "Returned",
                    "Return Reason (Pathao)": return_reason,
                    "Customer Name": str(o.get("recipient_name", "")).strip(),
                    "Phone": str(o.get("recipient_phone", "")).strip(),
                    "Address": str(o.get("recipient_address", "")).strip(),
                    "Order Date": created_raw,
                    "COD Amount": amt,
                    "Store": str(o.get("store_name", "")).strip(),
                }
            )

        if meta and meta.get("last_page") is not None:
            if page >= int(meta["last_page"]):
                break

    if not pathao_rows:
        return [], None

    # Build a mapping: WC order number -> Pathao metadata for WC enrichment
    pathao_meta: dict[str, dict] = {}
    wc_order_numbers: list[str] = []
    for pr in pathao_rows:
        ref = pr["_wc_order_ref"]
        if ref:
            pathao_meta[ref] = {
                "consignment_id": pr["Consignment ID"],
                "pathao_status": pr["Pathao Status"],
                "return_reason": pr["Return Reason (Pathao)"],
            }
            wc_order_numbers.append(ref)

    # Fetch WC orders by their order numbers (merchant_order_id = WC order number)
    # WC REST API uses numeric IDs; if the merchant_order_id is the WC order number,
    # we can use it directly with the include= parameter.
    wc_rows, wc_err = fetch_wc_orders_by_ids(wc_order_numbers, pathao_meta=pathao_meta)

    if wc_err:
        # Fall back to Pathao-only data if WC lookup fails
        log_system_event("PATHAO_WC_LOOKUP_ERROR", wc_err)
        clean_rows = []
        for pr in pathao_rows:
            pr.pop("_wc_order_ref", None)
            clean_rows.append(pr)
        return clean_rows, None

    if wc_rows:
        return wc_rows, None

    # WC returned no rows (order IDs not found) — return Pathao-only data
    clean_rows = []
    for pr in pathao_rows:
        pr.pop("_wc_order_ref", None)
        # Fill in missing WC fields
        pr.setdefault("WC Return Status", "completed (WC)")
        pr.setdefault("Product Description", "")
        pr.setdefault("SKU", "")
        pr.setdefault("Quantity", "")
        pr.setdefault("Item Price", "")
        pr.setdefault("Order Total", pr.pop("COD Amount", ""))
        pr.setdefault("Payment Method", "")
        pr.setdefault("Refund Reason (WC)", "")
        pr.setdefault("City", "")
        clean_rows.append(pr)
    return clean_rows, None
