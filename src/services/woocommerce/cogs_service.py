"""WooCommerce Cost of Goods Sold (COGS) fetching and enrichment service.

Fetches product and variation purchase costs (e.g. `_sip_buying_price`, `_alg_wc_cog_cost`)
via the WooCommerce REST API, caches values persistently in `resources/cogs_cache.json`,
and enriches order export DataFrames with unit COGS, total line COGS, gross profit, and margin.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
from requests.auth import HTTPBasicAuth

from src.config.settings import get_woocommerce_config
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event

CACHE_FILE = Path("resources") / "cogs_cache.json"

# Common meta keys used by DEEN (SIP POS) and standard WooCommerce COGS plugins
COGS_META_KEYS = (
    "_sip_buying_price",
    "sip_buying_price",
    "_alg_wc_cog_cost",
    "_wc_cog_cost",
    "_cogs_cost",
    "_cogs",
    "cogs",
    "_cost_price",
    "cost_price",
    "_cost",
)

# In-memory session cache: key is str (sku or id), value is float
_MEMORY_COGS_CACHE: dict[str, float] = {}
_CACHE_LOADED = False


def _load_cogs_cache() -> None:
    """Load cached COGS mappings from disk into memory."""
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return

    _CACHE_LOADED = True
    if not CACHE_FILE.exists():
        return

    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    if v is not None:
                        _MEMORY_COGS_CACHE[str(k).strip()] = float(v)
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        log_system_event(
            "COGS_CACHE_LOAD_ERROR", f"Failed loading cogs_cache.json: {e}"
        )


def _save_cogs_cache() -> None:
    """Save in-memory COGS mappings to disk."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(_MEMORY_COGS_CACHE, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log_system_event("COGS_CACHE_SAVE_ERROR", f"Failed saving cogs_cache.json: {e}")


def extract_cogs_from_meta(meta_list: list[dict[str, Any]] | None) -> float | None:
    """Extract numeric buying cost from a product or variation's meta_data array."""
    if not meta_list or not isinstance(meta_list, list):
        return None

    for meta in meta_list:
        if not isinstance(meta, dict):
            continue
        key = str(meta.get("key", "")).strip().lower()
        if key in COGS_META_KEYS:
            val = meta.get("value")
            if val is not None and str(val).strip() != "":
                try:
                    num = float(str(val).replace(",", "").strip())
                    if num >= 0:
                        return num
                except (ValueError, TypeError):
                    continue
    return None


def fetch_cogs_for_product(
    product_id: int | str,
    base_url: str,
    auth: HTTPBasicAuth,
) -> dict[str, float]:
    """Fetch COGS for a product and all of its variations via WooCommerce REST API.

    Returns mapping of {id_str: cogs_val, sku: cogs_val}.
    """
    found: dict[str, float] = {}
    p_id_str = str(product_id).strip()
    if not p_id_str or p_id_str == "0" or p_id_str == "None":
        return found

    url = f"{base_url}/wp-json/wc/v3/products/{p_id_str}"
    try:
        res = request_with_backoff("GET", url, auth=auth, timeout=12)
        if res.status_code != 200:
            return found
        p_data = res.json()
        if not isinstance(p_data, dict):
            return found

        # Product level COGS
        p_cogs = extract_cogs_from_meta(p_data.get("meta_data"))
        p_sku = str(p_data.get("sku", "")).strip()
        if p_cogs is not None:
            found[f"p_{p_id_str}"] = p_cogs
            if p_sku:
                found[p_sku] = p_cogs

        # If variable product, fetch all variations in one call
        if p_data.get("type") == "variable" or p_data.get("variations"):
            var_url = (
                f"{base_url}/wp-json/wc/v3/products/{p_id_str}/variations?per_page=100"
            )
            v_res = request_with_backoff("GET", var_url, auth=auth, timeout=15)
            if v_res.status_code == 200:
                v_data = v_res.json()
                if isinstance(v_data, list):
                    for var in v_data:
                        v_id_str = str(var.get("id", "")).strip()
                        v_sku = str(var.get("sku", "")).strip()
                        v_cogs = extract_cogs_from_meta(var.get("meta_data"))
                        # Fallback to parent product COGS if variation meta is empty
                        eff_cogs = v_cogs if v_cogs is not None else p_cogs
                        if eff_cogs is not None:
                            if v_id_str:
                                found[f"v_{v_id_str}"] = eff_cogs
                            if v_sku:
                                found[v_sku] = eff_cogs
    except Exception as e:
        log_system_event("COGS_FETCH_ERROR", f"Error fetching product {p_id_str}: {e}")

    return found


def fetch_cogs_by_sku(
    sku: str,
    base_url: str,
    auth: HTTPBasicAuth,
) -> float | None:
    """Fetch COGS for a specific SKU directly via REST API query."""
    clean_sku = str(sku).strip()
    if not clean_sku:
        return None

    url = f"{base_url}/wp-json/wc/v3/products?sku={clean_sku}"
    try:
        res = request_with_backoff("GET", url, auth=auth, timeout=12)
        if res.status_code != 200:
            return None
        data = res.json()
        if isinstance(data, list) and len(data) > 0:
            p_data = data[0]
            # Check meta directly
            cogs = extract_cogs_from_meta(p_data.get("meta_data"))
            if cogs is not None:
                return cogs
            # If variable, check variations
            p_id = p_data.get("id")
            if p_id:
                var_url = (
                    f"{base_url}/wp-json/wc/v3/products/{p_id}/variations?per_page=100"
                )
                v_res = request_with_backoff("GET", var_url, auth=auth, timeout=15)
                if v_res.status_code == 200:
                    v_data = v_res.json()
                    if isinstance(v_data, list):
                        for var in v_data:
                            if str(var.get("sku", "")).strip() == clean_sku:
                                return extract_cogs_from_meta(var.get("meta_data"))
    except Exception as e:
        log_system_event("COGS_SKU_FETCH_ERROR", f"Error fetching SKU {clean_sku}: {e}")

    return None


def get_cogs_for_item(
    sku: str = "",
    product_id: int | str | None = None,
    variation_id: int | str | None = None,
) -> float | None:
    """Lookup COGS from in-memory cache using variation ID, product ID, or SKU."""
    _load_cogs_cache()

    # 1. Try Variation ID
    if variation_id:
        v_key = f"v_{str(variation_id).strip()}"
        if v_key in _MEMORY_COGS_CACHE:
            return _MEMORY_COGS_CACHE[v_key]

    # 2. Try SKU
    clean_sku = str(sku).strip()
    if clean_sku and clean_sku in _MEMORY_COGS_CACHE:
        return _MEMORY_COGS_CACHE[clean_sku]

    # 3. Try Product ID
    if product_id:
        p_key = f"p_{str(product_id).strip()}"
        if p_key in _MEMORY_COGS_CACHE:
            return _MEMORY_COGS_CACHE[p_key]

    return None


def enrich_dataframe_with_cogs(
    df: pd.DataFrame,
    fetch_missing: bool = True,
    max_workers: int = 5,
) -> pd.DataFrame:
    """Enrich an order line items DataFrame with COGS and profit metrics.

    Adds the following columns:
    - ``Unit COGS``: Buying cost per item (৳).
    - ``Total COGS``: Total buying cost for the line item (Unit COGS * Quantity).
    - ``Gross Profit``: Line Total - Total COGS.
    - ``Profit Margin (%)``: (Gross Profit / Line Total * 100) rounded to 1 decimal.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame of shipped or completed line items.
    fetch_missing : bool
        Whether to query WooCommerce REST API in parallel for missing items.
    max_workers : int
        Max concurrent worker threads for REST API queries.
    """
    if df is None or df.empty:
        return df

    _load_cogs_cache()
    enriched = df.copy()

    # Identify SKU, Product ID, Variation ID columns defensively
    sku_col = next(
        (c for c in ["SKU", "sku", "Item SKU"] if c in enriched.columns), None
    )
    pid_col = next(
        (c for c in ["Product ID", "product_id"] if c in enriched.columns), None
    )
    vid_col = next(
        (c for c in ["Variation ID", "variation_id"] if c in enriched.columns), None
    )
    qty_col = next(
        (c for c in ["Quantity", "Qty", "qty"] if c in enriched.columns), None
    )
    total_col = next(
        (c for c in ["Line Total", "Total Amount", "Total"] if c in enriched.columns),
        None,
    )

    # 1. Determine which unique products/SKUs need to be fetched via REST API
    needed_pids = set()
    needed_skus = set()

    for _, row in enriched.iterrows():
        s = str(row[sku_col]).strip() if sku_col else ""
        p = row[pid_col] if pid_col else None
        v = row[vid_col] if vid_col else None

        cogs_val = get_cogs_for_item(sku=s, product_id=p, variation_id=v)
        if cogs_val is None:
            if p and str(p).strip() not in ("0", "None", ""):
                needed_pids.add(str(p).strip())
            elif s:
                needed_skus.add(s)

    # 2. Fetch missing items via REST API in parallel
    if fetch_missing and (needed_pids or needed_skus):
        wc_info = get_woocommerce_config(required=False)
        wc_url = wc_info.get("store_url")
        wc_key = wc_info.get("consumer_key")
        wc_secret = wc_info.get("consumer_secret")

        if wc_url and wc_key and wc_secret:
            base_url = wc_url.rstrip("/")
            auth = HTTPBasicAuth(wc_key, wc_secret)

            cache_dirty = False
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for pid in needed_pids:
                    futures[
                        executor.submit(fetch_cogs_for_product, pid, base_url, auth)
                    ] = ("pid", pid)
                for sku_val in needed_skus:
                    futures[
                        executor.submit(fetch_cogs_by_sku, sku_val, base_url, auth)
                    ] = ("sku", sku_val)

                for fut in as_completed(futures):
                    kind, key = futures[fut]
                    try:
                        res = fut.result()
                        if isinstance(res, dict):
                            _MEMORY_COGS_CACHE.update(res)
                            cache_dirty = True
                        elif isinstance(res, (int, float)) and res is not None:
                            _MEMORY_COGS_CACHE[key] = float(res)
                            cache_dirty = True
                    except Exception as e:
                        log_system_event(
                            "COGS_BATCH_WORKER_ERROR",
                            f"Worker failed for {kind}:{key}: {e}",
                        )

            if cache_dirty:
                _save_cogs_cache()

    # 3. Apply COGS to each row
    unit_cogs_list: list[float] = []
    for _, row in enriched.iterrows():
        s = str(row[sku_col]).strip() if sku_col else ""
        p = row[pid_col] if pid_col else None
        v = row[vid_col] if vid_col else None
        val = get_cogs_for_item(sku=s, product_id=p, variation_id=v)
        unit_cogs_list.append(round(val, 2) if val is not None else 0.0)

    enriched["Unit COGS"] = unit_cogs_list

    # Ensure quantity is numeric
    if qty_col:
        qty_series = pd.to_numeric(enriched[qty_col], errors="coerce").fillna(1)
    else:
        qty_series = pd.Series(1, index=enriched.index)

    # Calculate Total COGS
    enriched["Total COGS"] = (enriched["Unit COGS"] * qty_series).round(2)

    # Calculate Gross Profit and Margin
    if total_col:
        line_total_series = pd.to_numeric(enriched[total_col], errors="coerce").fillna(
            0.0
        )
    else:
        line_total_series = pd.Series(0.0, index=enriched.index)

    enriched["Gross Profit"] = (line_total_series - enriched["Total COGS"]).round(2)

    # Margin % = (Gross Profit / Line Total) * 100
    margin_series = (
        (enriched["Gross Profit"] / line_total_series.replace(0, float("nan")) * 100)
        .round(1)
        .fillna(0.0)
    )
    enriched["Profit Margin (%)"] = margin_series

    return enriched
