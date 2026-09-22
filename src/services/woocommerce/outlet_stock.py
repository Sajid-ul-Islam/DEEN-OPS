"""
Auto-discovery outlet stock extraction from WooCommerce custom plugins.

Detects how your custom plugin stores outlet/warehouse stock data and pulls it
live via the WooCommerce REST API. Supports multiple storage patterns:

1. Product meta fields (e.g., _outlet_mirpur_qty, _warehouse_wari_stock)
2. Custom REST API endpoints (e.g., /wp-json/custom-inventory/v1/outlet-stock)
3. Product attributes (e.g., attribute "Outlet" with terms "Mirpur: 50")
4. Custom plugin tables exposed via REST (e.g., /wp-json/wc/v3/inventory)
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
from src.utils.streamlit_runtime import cache_data
from requests.auth import HTTPBasicAuth

from src.config.settings import get_woocommerce_config
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event

# Known patterns for outlet stock storage in custom plugins
_KNOWN_OUTLET_PATTERNS = [
    # Pattern 1: _outlet_{location}_qty / _outlet_{location}_stock
    re.compile(r"^_outlet_(?P<loc>[a-z]+)_(?:qty|stock|quantity)$", re.IGNORECASE),
    # Pattern 2: _warehouse_{location}_stock / _warehouse_{location}_qty
    re.compile(r"^_warehouse_(?P<loc>[a-z]+)_(?:stock|qty|quantity)$", re.IGNORECASE),
    # Pattern 3: _stock_{location} / _qty_{location}
    re.compile(r"^_(?:stock|qty|quantity)_(?P<loc>[a-z]+)$", re.IGNORECASE),
    # Pattern 4: outlet_{location}_stock / outlet_{location}_qty
    re.compile(r"^outlet_(?P<loc>[a-z]+)_(?:stock|qty|quantity)$", re.IGNORECASE),
    # Pattern 5: wms_{location}_qty / wms_{location}_stock
    re.compile(r"^wms_(?P<loc>[a-z]+)_(?:qty|stock|quantity)$", re.IGNORECASE),
    # Pattern 6: si_{location}_stock / si_{location}_qty (SmartInventory)
    re.compile(r"^si_(?P<loc>[a-z]+)_(?:stock|qty|quantity)$", re.IGNORECASE),
    # Pattern 7: multi_location_{location}_stock
    re.compile(r"^multi_location_(?P<loc>[a-z]+)_(?:stock|qty)$", re.IGNORECASE),
]

# Known custom REST API endpoints for outlet stock
_KNOWN_CUSTOM_ENDPOINTS = [
    "/wp-json/wc/v3/sip/outlet-stock",
    "/wp-json/sip/v1/outlet-stock",
    "/wp-json/custom-inventory/v1/outlet-stock",
    "/wp-json/wc/v3/inventory",
    "/wp-json/wms/v1/stock",
    "/wp-json/si/v1/outlet-stock",
    "/wp-json/multi-location/v1/stock",
    "/wp-json/inventory/v1/outlets",
    "/wp-json/wc/v3/products/bulk-stock",
]


def _get_auth_and_url() -> Tuple[Optional[HTTPBasicAuth], Optional[str]]:
    """Get WooCommerce auth and base URL."""
    cfg = get_woocommerce_config(required=False)
    if not cfg or not cfg.get("store_url") or not cfg.get("consumer_key"):
        return None, None
    auth = HTTPBasicAuth(cfg["consumer_key"], cfg["consumer_secret"])
    return auth, cfg["store_url"].rstrip("/")


def discover_outlet_meta_keys(sample_size: int = 50) -> Dict[str, List[str]]:
    """
    Scan recent products to discover outlet stock meta keys.
    Returns dict of {location_pattern: [list_of_matching_meta_keys]}.
    """
    auth, base_url = _get_auth_and_url()
    if not auth:
        return {}

    endpoint = f"{base_url}/wp-json/wc/v3/products"
    try:
        res = request_with_backoff(
            "GET",
            endpoint,
            params={
                "per_page": sample_size,
                "status": "any",
                "_fields": "id,meta_data",
            },
            auth=auth,
            timeout=15,
        )
        if res.status_code != 200:
            return {}

        products = json.loads(res.text.lstrip("﻿"))
        discovered: Dict[str, List[str]] = {}

        for product in products:
            for meta in product.get("meta_data", []):
                key = meta.get("key", "")
                for pattern in _KNOWN_OUTLET_PATTERNS:
                    match = pattern.match(key)
                    if match:
                        loc = match.group("loc").capitalize()
                        if loc not in discovered:
                            discovered[loc] = []
                        if key not in discovered[loc]:
                            discovered[loc].append(key)

        return discovered

    except Exception as e:
        log_system_event("OUTLET_DISCOVERY_ERROR", str(e))
        return {}


def discover_custom_endpoints() -> Optional[str]:
    """
    Probe known custom REST API endpoints to find one that exists.
    Returns the base endpoint URL if found, None otherwise.
    """
    auth, base_url = _get_auth_and_url()
    if not auth:
        return None

    for path in _KNOWN_CUSTOM_ENDPOINTS:
        try:
            res = request_with_backoff(
                "GET",
                f"{base_url}{path}",
                params={"per_page": 1},
                auth=auth,
                timeout=10,
            )
            if res.status_code == 200:
                return f"{base_url}{path}"
        except Exception:
            continue

    return None


def fetch_outlet_stock_from_meta(
    outlet_meta_keys: Dict[str, List[str]],
) -> Optional[pd.DataFrame]:
    """
    Fetch outlet stock by reading product meta fields.
    Returns DataFrame with columns: [SKU, Product, Outlet1, Outlet2, ...]
    """
    auth, base_url = _get_auth_and_url()
    if not auth or not outlet_meta_keys:
        return None

    endpoint = f"{base_url}/wp-json/wc/v3/products"
    all_products = []

    try:
        page = 1
        while True:
            res = request_with_backoff(
                "GET",
                endpoint,
                params={
                    "per_page": 100,
                    "page": page,
                    "status": "any",
                    "_fields": "id,name,sku,meta_data",
                },
                auth=auth,
                timeout=25,
            )
            if res.status_code != 200:
                break

            products = json.loads(res.text.lstrip("﻿"))
            if not products:
                break
            all_products.extend(products)
            if len(products) < 100:
                break
            page += 1

        rows = []
        for product in all_products:
            sku = product.get("sku", "")
            name = product.get("name", "")
            meta = {m["key"]: m.get("value", 0) for m in product.get("meta_data", [])}

            row = {"SKU": sku, "Product": name}
            has_stock = False

            for loc, keys in outlet_meta_keys.items():
                total_qty = 0
                for key in keys:
                    val = meta.get(key, 0)
                    try:
                        qty = float(val) if val else 0
                        total_qty += qty
                    except (ValueError, TypeError):
                        pass
                row[loc] = int(total_qty)
                if total_qty > 0:
                    has_stock = True

            if has_stock:
                rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            # Reorder columns: SKU, Product, then outlets alphabetically
            cols = ["SKU", "Product"] + sorted(
                [c for c in df.columns if c not in ["SKU", "Product"]]
            )
            return df[cols]
        return None

    except Exception as e:
        log_system_event("OUTLET_META_FETCH_ERROR", str(e))
        return None


def fetch_outlet_stock_from_custom_endpoint(
    endpoint_url: str,
) -> Optional[pd.DataFrame]:
    """
    Fetch outlet stock from a custom REST API endpoint.
    Handles common response formats.
    """
    auth, _ = _get_auth_and_url()
    if not auth:
        return None

    try:
        res = request_with_backoff(
            "GET",
            endpoint_url,
            params={"per_page": 100},
            auth=auth,
            timeout=25,
        )
        if res.status_code != 200:
            return None

        data = json.loads(res.text.lstrip("﻿"))

        # Handle different response formats
        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict):
                first = {str(k).lower(): v for k, v in data[0].items()}
                outlet_key = next(
                    (k for k in ["outlet", "outlet_name", "outlet_slug"] if k in first),
                    None,
                )
                qty_key = next(
                    (
                        k
                        for k in ["stock_qty", "qty", "stock", "quantity"]
                        if k in first
                    ),
                    None,
                )
                if outlet_key and qty_key:
                    # Format 1A: Tabular rows [{product, size, sku, outlet, stock_qty}, ...] -> Pivot
                    pivot = {}
                    for item in data:
                        item_map = {str(k).lower(): v for k, v in item.items()}
                        sku = str(item_map.get("sku", "")).strip()
                        prod = str(
                            item_map.get("product", item_map.get("product_name", ""))
                        ).strip()
                        size = str(
                            item_map.get("size", item_map.get("variation_name", ""))
                        ).strip()
                        outlet_name = str(item_map.get(outlet_key, "")).strip().title()
                        try:
                            qty = int(float(item_map.get(qty_key, 0)))
                        except (ValueError, TypeError):
                            qty = 0

                        key = (sku, prod, size)
                        if key not in pivot:
                            pivot[key] = {"SKU": sku, "Product": prod}
                            if size:
                                pivot[key]["Size"] = size
                        pivot[key][outlet_name] = qty

                    df = pd.DataFrame(list(pivot.values()))
                    base_cols = [
                        c for c in ["SKU", "Product", "Size"] if c in df.columns
                    ]
                    outlet_cols = sorted([c for c in df.columns if c not in base_cols])
                    return df[base_cols + outlet_cols].fillna(0)
                else:
                    # Format 1B: Already pivoted {sku, product, Mirpur: 5, Wari: 3, ...}
                    df = pd.DataFrame(data)
                    df.columns = [
                        c.strip().title() if c.lower() != "sku" else "SKU"
                        for c in df.columns
                    ]
                    return df

        elif isinstance(data, dict):
            # Format 2: {products: [...], stock: {sku: {outlet: qty}}}
            if "products" in data and "stock" in data:
                rows = []
                for product in data["products"]:
                    sku = product.get("sku", "")
                    name = product.get("name", "")
                    stock = data["stock"].get(sku, {})
                    row = {"SKU": sku, "Product": name}
                    row.update(stock)
                    rows.append(row)
                return pd.DataFrame(rows) if rows else None

            # Format 3: {outlets: [...], stock: [{sku, outlet, qty}]}
            elif "outlets" in data and "stock" in data:
                pivot = {}
                for item in data["stock"]:
                    sku = item.get("sku", "")
                    outlet = item.get("outlet", "")
                    qty = item.get("qty", 0)
                    if sku not in pivot:
                        pivot[sku] = {"SKU": sku}
                    pivot[sku][outlet] = qty
                rows = list(pivot.values())
                return pd.DataFrame(rows) if rows else None

        return None

    except Exception as e:
        log_system_event("OUTLET_CUSTOM_FETCH_ERROR", str(e))
        return None


SIP_STOCK_ENDPOINT = "/wp-json/wc/v3/sip/outlet-stock"
# Canonical ordering for SIP outlet columns in the pivoted DataFrame
_SIP_OUTLET_ORDER = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet", "Warehouse"]


def fetch_sip_outlet_stock(endpoint_url: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Fetch live SIP outlet stock from the Smart Inventory with POS plugin.

    Expects the plugin's Current Stock Report shape — either flat tabular rows
    ``{product, size, sku, outlet, stock_qty, price, last_updated}`` (pivoted
    here into one row per SKU/Size) or an already-pivoted list. Delegates the
    parsing/pivoting to ``fetch_outlet_stock_from_custom_endpoint`` so all
    legacy response formats keep working.

    Returns a DataFrame with columns ``[SKU, Product, Size?, <Outlet>...]`` or
    None when the endpoint is unavailable (e.g. not yet deployed).
    """
    auth, base_url = _get_auth_and_url()
    if not auth or not base_url:
        return None

    if endpoint_url:
        url = endpoint_url
    else:
        url = f"{base_url}{SIP_STOCK_ENDPOINT}"

    df = fetch_outlet_stock_from_custom_endpoint(url)
    if df is None or df.empty:
        return None

    # Ensure Size column survives even when the API omits it
    if "Size" not in df.columns:
        df = df.copy()
        df["Size"] = ""

    # Normalise outlet column values to numeric, missing outlets to 0
    outlet_cols = [
        c for c in df.columns if c not in ("SKU", "Product", "Size", "Price", "Last Updated")
    ]
    for col in outlet_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Stable outlet column ordering: canonical outlets first, extras after
    ordered = [c for c in _SIP_OUTLET_ORDER if c in outlet_cols]
    ordered += sorted(c for c in outlet_cols if c not in ordered)
    base_cols = [c for c in ["SKU", "Product", "Size"] if c in df.columns]
    return df[base_cols + ordered]


def fetch_outlet_stock_from_attributes() -> Optional[pd.DataFrame]:
    """
    Fetch outlet stock stored as product attributes.
    Some plugins store outlet stock as attribute values like "Mirpur: 50".
    """
    auth, base_url = _get_auth_and_url()
    if not auth:
        return None

    endpoint = f"{base_url}/wp-json/wc/v3/products"
    all_products = []

    try:
        page = 1
        while True:
            res = request_with_backoff(
                "GET",
                endpoint,
                params={
                    "per_page": 100,
                    "page": page,
                    "status": "any",
                    "_fields": "id,name,sku,attributes",
                },
                auth=auth,
                timeout=25,
            )
            if res.status_code != 200:
                break

            products = json.loads(res.text.lstrip("﻿"))
            if not products:
                break
            all_products.extend(products)
            if len(products) < 100:
                break
            page += 1

        rows = []
        for product in all_products:
            sku = product.get("sku", "")
            name = product.get("name", "")
            attrs = product.get("attributes", [])

            row = {"SKU": sku, "Product": name}
            has_stock = False

            for attr in attrs:
                attr_name = attr.get("name", "").lower()
                if (
                    "outlet" in attr_name
                    or "warehouse" in attr_name
                    or "stock" in attr_name
                ):
                    for option in attr.get("options", []):
                        # Parse "Mirpur: 50" or "Wari - 20" or "Cumilla: 15 pcs"
                        match = re.match(
                            r"^(?P<loc>[a-z\s]+)[:\\-]?\s*(?P<qty>\d+)",
                            option.strip(),
                            re.IGNORECASE,
                        )
                        if match:
                            loc = match.group("loc").strip().capitalize()
                            qty = int(match.group("qty"))
                            row[loc] = row.get(loc, 0) + qty
                            has_stock = True

            if has_stock:
                rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            cols = ["SKU", "Product"] + sorted(
                [c for c in df.columns if c not in ["SKU", "Product"]]
            )
            return df[cols]
        return None

    except Exception as e:
        log_system_event("OUTLET_ATTR_FETCH_ERROR", str(e))
        return None



@cache_data(ttl=300, show_spinner="Fetching SIP outlet stock...")
def fetch_live_sip_stock() -> Optional[pd.DataFrame]:
    """Cached SIP stock fetch for UI use (5-minute TTL).

    Returns None when SIP credentials are missing or the endpoint is not
    deployed yet — callers should show a friendly 'not live yet' state.
    """
    return fetch_sip_outlet_stock()
