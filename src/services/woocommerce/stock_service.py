"""WooCommerce product catalog stock sync service.

Fetches product variations and inventory levels from the WooCommerce REST API
and merges them with warehouse stock levels.
"""

from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd
from requests.auth import HTTPBasicAuth

from src.config.settings import get_woocommerce_config
from src.processing.categorization import get_category_for_sales
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event


def fetch_live_woocommerce_stock(max_pages: int = 10) -> pd.DataFrame:
    """Fetch live product catalog and variation stock quantities from WooCommerce REST API.

    Returns a DataFrame with columns:
    ``Product``, ``Size``, ``SKU``, ``Category``, ``Warehouse``, ``Price``, ``Status``.
    """
    wc_cfg = get_woocommerce_config(required=False)
    store_url = wc_cfg.get("store_url")
    ck = wc_cfg.get("consumer_key")
    cs = wc_cfg.get("consumer_secret")

    if not store_url or not ck or not cs:
        log_system_event(
            "WC_STOCK_SYNC_SKIPPED", "WooCommerce credentials not configured."
        )
        return pd.DataFrame()

    base_url = store_url.rstrip("/")
    auth = HTTPBasicAuth(ck, cs)
    headers = {"User-Agent": "DEEN-OPS/1.0", "Accept": "application/json"}

    rows: List[Dict[str, Any]] = []

    try:
        page = 1
        while page <= max_pages:
            url = f"{base_url}/wp-json/wc/v3/products?per_page=100&page={page}"
            res = request_with_backoff(
                "GET", url, auth=auth, headers=headers, timeout=20
            )
            if res.status_code != 200:
                break

            products = res.json()
            if not isinstance(products, list) or len(products) == 0:
                break

            for p in products:
                p_name = str(p.get("name", "")).strip()
                p_id = p.get("id")
                p_type = p.get("type", "simple")
                p_price = float(p.get("price") or 0.0)

                categories = [
                    c.get("name")
                    for c in p.get("categories", [])
                    if isinstance(c, dict)
                ]
                cat_name = (
                    categories[0] if categories else get_category_for_sales(p_name)
                )

                # If variable product, fetch its variations
                if p_type == "variable" or p.get("variations"):
                    var_url = f"{base_url}/wp-json/wc/v3/products/{p_id}/variations?per_page=100"
                    try:
                        v_res = request_with_backoff(
                            "GET", var_url, auth=auth, headers=headers, timeout=20
                        )
                        if v_res.status_code == 200:
                            variations = v_res.json()
                            if isinstance(variations, list) and variations:
                                for v in variations:
                                    v_sku = str(v.get("sku", "")).strip()
                                    v_stock = int(v.get("stock_quantity") or 0)
                                    v_price = float(v.get("price") or p_price)
                                    # Extract size from attributes
                                    size_val = ""
                                    for attr in v.get("attributes", []):
                                        if (
                                            isinstance(attr, dict)
                                            and "size"
                                            in str(attr.get("name", "")).lower()
                                        ):
                                            size_val = str(
                                                attr.get("option", "")
                                            ).strip()
                                            break
                                    if not size_val and v.get("attributes"):
                                        size_val = str(
                                            v["attributes"][0].get("option", "")
                                        ).strip()

                                    rows.append(
                                        {
                                            "Product": p_name,
                                            "Size": size_val,
                                            "SKU": v_sku,
                                            "Category": cat_name,
                                            "Warehouse": v_stock,
                                            "Price": v_price,
                                            "Status": "In Stock"
                                            if v_stock > 0
                                            else "Out of Stock",
                                        }
                                    )
                                continue
                    except Exception as ve:
                        log_system_event(
                            "WC_VAR_FETCH_ERROR",
                            f"Error fetching variations for {p_id}: {ve}",
                        )

                # Simple or single product
                p_sku = str(p.get("sku", "")).strip()
                p_stock = int(p.get("stock_quantity") or 0)
                rows.append(
                    {
                        "Product": p_name,
                        "Size": "",
                        "SKU": p_sku,
                        "Category": cat_name,
                        "Warehouse": p_stock,
                        "Price": p_price,
                        "Status": "In Stock" if p_stock > 0 else "Out of Stock",
                    }
                )

            total_pages = int(res.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1

    except Exception as e:
        log_system_event("WC_STOCK_SYNC_ERROR", f"Stock sync failed: {e}")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df
