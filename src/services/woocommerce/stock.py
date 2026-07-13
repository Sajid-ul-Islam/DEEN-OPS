import streamlit as st
import pandas as pd
from datetime import datetime
import json
from requests.auth import HTTPBasicAuth
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config.settings import get_woocommerce_config
from src.processing.categorization import get_category_for_sales
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event
from src.utils.snapshots import save_stock_snapshot


@st.cache_data(ttl=3600)
def _get_category(name):
    return get_category_for_sales(name)


@st.cache_data(ttl=600)
def fetch_woocommerce_stock(filter_skus=None, filter_titles=None):
    """Fetches real-time stock levels for published items using Expert Rules."""
    wc_info = get_woocommerce_config(required=False)
    wc_url = wc_info.get("store_url")
    wc_key = wc_info.get("consumer_key")
    wc_secret = wc_info.get("consumer_secret")

    if not wc_url or not wc_key or not wc_secret:
        st.error("WooCommerce credentials missing.")
        return None

    auth = HTTPBasicAuth(wc_key, wc_secret)
    base_endpoint = f"{wc_url.rstrip('/')}/wp-json/wc/v3/products"
    stock_data = []

    def fetch_variations(p_id, p_name):
        try:
            v_r = request_with_backoff(
                "GET",
                f"{base_endpoint}/{p_id}/variations",
                params={"per_page": 100, "status": "publish"},
                auth=auth,
                timeout=15,
            )
            if v_r.status_code == 200:
                results = []
                data = json.loads(v_r.text.lstrip('\ufeff'))
                for v in data:
                    if v.get("status", "publish") != "publish":
                        continue
                    size_val = v.get('attributes',[{}])[0].get('option','N/A')
                    full_name = f"{p_name} - {size_val}"
                    results.append({
                        "Category": _get_category(p_name),
                        "Product": full_name,
                        "Size": size_val,
                        "SKU": v.get("sku") or f"P{p_id}-V{v.get('id')}",
                        "Stock": v.get("stock_quantity") if v.get("manage_stock") else 0,
                        "Price": v.get("price", "0"),
                        "Status": v.get("stock_status", "unknown").title()
                    })
                return results
        except Exception as e:
            print(f"Error fetching variations for Product ID {p_id}: {e}")
            pass
        return []

    try:
        page = 1
        all_products = []
        with st.spinner("Fetching published inventory..."):
            while True:
                r = request_with_backoff(
                    "GET",
                    base_endpoint,
                    params={
                        "per_page": 100,
                        "page": page,
                        "status": "publish"
                    },
                    auth=auth,
                    timeout=25
                )
                r.raise_for_status()
                products = json.loads(r.text.lstrip('\ufeff'))
                if not products: break
                all_products.extend(products)
                if len(products) < 100: break
                page += 1

        # Identify variable products for parallel processing
        variable_tasks = []
        for p in all_products:
            p_id, p_name = p.get("id"), p.get("name")
            p_type = p.get("type", "simple")

            if p_type == "variable":
                # Apply filter logic if provided
                if filter_skus or filter_titles:
                    p_sku_norm = (p.get("sku") or "").strip().lower()
                    p_name_norm = p.get("name", "").strip().lower()
                    is_relevant = False
                    if filter_skus and (p_sku_norm in filter_skus): is_relevant = True
                    if filter_titles and (p_name_norm in filter_titles): is_relevant = True
                    if not is_relevant and filter_skus and p_sku_norm:
                        for ts in filter_skus:
                            if ts.lower().startswith(p_sku_norm):
                                is_relevant = True
                                break
                    if not is_relevant: continue
                variable_tasks.append((p_id, p_name))
            else:
                stock_data.append({
                    "Category": _get_category(p_name),
                    "Product": p_name,
                    "SKU": p.get("sku") or f"P{p_id}",
                    "Stock": p.get("stock_quantity") if p.get("manage_stock") else 0,
                    "Price": p.get("price", "0"),
                    "Status": p.get("stock_status", "unknown").title()
                })

        # Concurrent Variation Fetching
        if variable_tasks:
            from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
            import threading
            ctx = get_script_run_ctx()
            
            def wrapped_fetch(tid, tname):
                if ctx:
                    add_script_run_ctx(threading.current_thread(), ctx)
                return fetch_variations(tid, tname)

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(wrapped_fetch, tid, tname): (tid, tname) for tid, tname in variable_tasks}
                for future in as_completed(futures):
                    res = future.result()
                    if res:
                        stock_data.extend(res)

        df = pd.DataFrame(stock_data)
        if not df.empty:
            df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").fillna(0).astype(float)
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0).astype(float)
            save_stock_snapshot(df)
        return df

    except Exception as e:
        log_system_event("STOCK_SYNC_ERROR", str(e))
        st.error(f"Stock fetch failed: {e}")
        return None