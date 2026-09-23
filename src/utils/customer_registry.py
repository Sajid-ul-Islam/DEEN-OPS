"""Persistent customer lifetime history registry.

Maps customer phone numbers and emails to their earliest known order date.
Identifies returning customers even when their previous order was years ago.
"""

from __future__ import annotations

import json
import os

import pandas as pd

from src.config.constants import RESOURCES_DIR
from src.processing.column_detection import (
    CITY_COL_CANDIDATES,
    DATE_COL_CANDIDATES,
    EMAIL_COL_CANDIDATES,
    NAME_COL_CANDIDATES,
    ORDER_ID_COL_CANDIDATES,
    PHONE_COL_CANDIDATES,
    pick_column,
)
from src.processing.completed_analytics import (
    has_blank_address,
    has_blank_phone,
    is_walkin_customer,
)
from src.processing.data_processing import safe_coerce_datetime_naive
from src.utils.customer_registry_full import classify_customer  # noqa: F401,E402
from src.utils.logging import log_system_event
from src.utils.text import normalize_phone_number

CUSTOMER_REGISTRY_PATH = os.path.join(RESOURCES_DIR, "customer_registry.json")


def normalize_phone_key(cust_id: str | None) -> str:
    """Normalize phone numbers or email keys to a standard format.

    Unifies 017..., 17..., 88017..., +88017... to standard 11-digit 017... format.
    """
    if not cust_id or pd.isna(cust_id):
        return ""
    return normalize_phone_number(cust_id)


def load_customer_registry() -> dict[str, str]:
    """Load the customer registry mapping (customer_key -> ISO earliest_date_str)."""
    try:
        from src.utils.customer_db import get_phone_registry_dict

        db_map = get_phone_registry_dict()
        if db_map:
            return db_map
    except Exception:
        pass

    if os.path.exists(CUSTOMER_REGISTRY_PATH):
        try:
            with open(CUSTOMER_REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_system_event(
                "CUSTOMER_REGISTRY_LOAD_ERROR", f"Failed to load registry: {e}"
            )
    return {}


def get_customer_first_order_date(
    cust_id: str | None, registry: dict[str, str] | None = None
) -> pd.Timestamp | None:
    """Lookup earliest known order date across all normalized key variations."""
    if not cust_id or pd.isna(cust_id):
        return None

    if registry is None:
        registry = load_customer_registry()

    raw_key = str(cust_id).strip().lower()
    clean_key = normalize_phone_key(cust_id)

    possible_keys = [clean_key, raw_key]
    if clean_key.startswith("0"):
        possible_keys.append(clean_key[1:])
    else:
        possible_keys.append("0" + clean_key)

    earliest_dt = None
    for k in possible_keys:
        if k and k in registry:
            dt_val = pd.to_datetime(registry[k], errors="coerce")
            if pd.notna(dt_val):
                if dt_val.tzinfo is not None:
                    dt_val = dt_val.tz_localize(None)
                if earliest_dt is None or dt_val < earliest_dt:
                    earliest_dt = dt_val

    return earliest_dt


def update_customer_registry(
    df: pd.DataFrame, wc_raw_mapping: dict | None = None
) -> int:
    """Update persistent customer registry from a DataFrame.

    Scans phone & email columns and updates earliest order dates using normalized keys.
    Returns count of new/updated customer records.
    """
    if df is None or df.empty:
        return 0

    registry = load_customer_registry()
    updated_cnt = 0

    try:
        mapping = wc_raw_mapping or {}
        date_col = "Date" if "Date" in df.columns else mapping.get("date", "Order Date")
        if date_col not in df.columns:
            date_col = pick_column(df, DATE_COL_CANDIDATES)

        if not date_col:
            return 0

        phone_col = pick_column(df, PHONE_COL_CANDIDATES)
        email_col = pick_column(df, EMAIL_COL_CANDIDATES)
        cust_col = phone_col or email_col

        if not cust_col:
            return 0

        t_df = df.copy()
        name_col = pick_column(df, NAME_COL_CANDIDATES)
        if name_col and name_col in t_df.columns:
            t_df = t_df[~t_df[name_col].apply(is_walkin_customer)]
        t_df = t_df[~t_df.apply(has_blank_phone, axis=1)]
        t_df["_dt"] = safe_coerce_datetime_naive(t_df[date_col])
        t_df["_norm_cust"] = t_df[cust_col].apply(normalize_phone_key)
        t_df = t_df.dropna(subset=["_dt"])
        t_df = t_df[t_df["_norm_cust"] != ""]

        if t_df.empty:
            return 0

        grouped = t_df.groupby("_norm_cust")["_dt"].min()

        for cust_key, min_dt in grouped.items():
            if not cust_key:
                continue

            dt_str = min_dt.isoformat()
            existing_dt = get_customer_first_order_date(cust_key, registry)

            if existing_dt is None or min_dt < existing_dt:
                registry[cust_key] = dt_str
                if cust_key.startswith("0"):
                    registry[cust_key[1:]] = dt_str
                updated_cnt += 1
                try:
                    from src.utils.customer_db import upsert_customer

                    upsert_customer(phone=cust_key, first_seen=dt_str)
                except Exception:
                    pass

        if updated_cnt > 0:
            os.makedirs(RESOURCES_DIR, exist_ok=True)
            with open(CUSTOMER_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)

    except Exception as e:
        log_system_event(
            "CUSTOMER_REGISTRY_UPDATE_ERROR", f"Failed to update registry: {e}"
        )

    return updated_cnt


def compute_new_vs_returning_counts(
    m_df: pd.DataFrame | None,
    full_df: pd.DataFrame | None = None,
    wc_raw_mapping: dict | None = None,
) -> tuple[int, int]:
    """Compute (new_customer_count, returning_customer_count).

    Primary source is the full 3-bucket customer registry
    (resources/customer_registry_full.json) which resolves identity by
    EMAIL -> PHONE (multi-format) -> NAME|CITY, so a returning customer is
    detected even when their earlier order was keyed differently. The legacy
    flat registry is used only as a fallback when the full registry is missing
    or a customer is not found there.
    """
    if m_df is None or m_df.empty:
        return 0, 0

    if full_df is None or full_df.empty:
        full_df = m_df

    # Keep the full 3-bucket registry current: merge the incoming live orders so
    # customers whose first order falls in the live window are not misclassified
    # as 'unknown' (and silently counted as new). This is incremental — it only
    # lowers first_seen, never erases history from the offline build.
    try:
        from src.utils.customer_registry_full import update_full_registry_from_df

        update_full_registry_from_df(full_df)
    except Exception:
        pass

    wc_raw_mapping = wc_raw_mapping or {}
    new_cnt, ret_cnt = 0, 0

    # ---- Primary path: full 3-bucket registry (email priority) ----
    full_reg = load_full_registry_safe()
    if full_reg is not None:
        email_col = pick_column(m_df, EMAIL_COL_CANDIDATES)
        phone_col = pick_column(m_df, PHONE_COL_CANDIDATES)
        name_col = pick_column(m_df, NAME_COL_CANDIDATES)
        city_col = pick_column(m_df, CITY_COL_CANDIDATES)
        date_col = (
            "Date"
            if "Date" in m_df.columns
            else wc_raw_mapping.get("date", "Order Date")
        )
        if date_col not in m_df.columns:
            date_col = pick_column(m_df, DATE_COL_CANDIDATES, m_df.columns[0])

        order_id_col = wc_raw_mapping.get("order_id", "Order ID")
        if order_id_col not in m_df.columns:
            order_id_col = pick_column(m_df, ORDER_ID_COL_CANDIDATES, m_df.columns[0])

        # Legacy structures, used as a fallback for customers the full
        # registry does not recognize (e.g. repeat-within-session phone only).
        legacy = _build_legacy_structures(m_df, full_df, wc_raw_mapping, date_col)

        seen = set()
        for _, urow in m_df.iterrows():
            oid = urow.get(order_id_col)
            if oid in seen:
                continue
            seen.add(oid)

            # Skip anonymous walk-in outlet customers, blank phone numbers, or orders with no address
            c_name = str(urow.get(name_col) or "") if name_col else ""
            if (
                is_walkin_customer(c_name)
                or has_blank_phone(urow)
                or has_blank_address(urow)
            ):
                continue

            billing = {}
            if email_col:
                billing["email"] = urow.get(email_col)
            if phone_col:
                billing["phone"] = urow.get(phone_col)
            if name_col:
                full_name = str(urow.get(name_col) or "")
                parts = full_name.split(None, 1)
                billing["first_name"] = parts[0] if parts else ""
                billing["last_name"] = parts[1] if len(parts) > 1 else ""
            if city_col:
                billing["city"] = urow.get(city_col)

            o_dt_raw = urow.get(date_col)
            try:
                o_dt = safe_coerce_datetime_naive(pd.Series([o_dt_raw])).iloc[0]
            except Exception:
                o_dt = None

            if o_dt is None:
                new_cnt += 1
                continue

            cls = classify_customer(billing, o_dt, full_reg)
            if cls == "returning":
                ret_cnt += 1
            elif cls == "new":
                new_cnt += 1
            else:
                # Unknown to the full registry -> fall back to legacy
                # (session flat-registry) decision for this customer.
                if _legacy_is_returning(urow, legacy):
                    ret_cnt += 1
                else:
                    new_cnt += 1
        return new_cnt, ret_cnt

    # ---- Fallback: legacy flat registry ----
    return _legacy_compute(m_df, full_df, wc_raw_mapping)


def _build_legacy_structures(
    m_df: pd.DataFrame,
    full_df: pd.DataFrame,
    wc_raw_mapping: dict,
    date_col: str,
) -> dict:
    """Build the legacy flat-registry lookups used as a per-row fallback.

    Returns a dict with: cust_col, first_order_map, lifetime_registry,
    dt_col, order_id_col.
    """
    update_customer_registry(full_df, wc_raw_mapping)
    lifetime_registry = load_customer_registry()

    phone_col = pick_column(m_df, PHONE_COL_CANDIDATES)
    email_col = pick_column(m_df, EMAIL_COL_CANDIDATES)
    cust_col = phone_col or email_col

    full_dt_col = (
        "Date"
        if "Date" in full_df.columns
        else wc_raw_mapping.get("date", "Order Date")
    )
    if full_dt_col not in full_df.columns:
        full_dt_col = pick_column(full_df, DATE_COL_CANDIDATES, full_df.columns[0])

    f_df = full_df.copy()
    full_name_col = pick_column(full_df, NAME_COL_CANDIDATES)
    if full_name_col and full_name_col in f_df.columns:
        f_df = f_df[~f_df[full_name_col].apply(is_walkin_customer)]
    f_df = f_df[~f_df.apply(has_blank_phone, axis=1)]
    f_df = f_df[~f_df.apply(has_blank_address, axis=1)]
    f_df["_dt"] = safe_coerce_datetime_naive(f_df[full_dt_col])
    f_df["_norm_cust"] = (
        f_df[cust_col].apply(normalize_phone_key)
        if cust_col
        else pd.Series([], dtype=str)
    )
    f_df = f_df.dropna(subset=["_dt"])
    f_df = f_df[f_df["_norm_cust"] != ""] if cust_col else f_df
    first_order_map = (
        f_df.groupby("_norm_cust")["_dt"].min().to_dict() if cust_col else {}
    )

    order_id_col = wc_raw_mapping.get("order_id", "Order ID")
    if order_id_col not in m_df.columns:
        order_id_col = pick_column(m_df, ["Order ID", "Order Number"], m_df.columns[0])

    return {
        "cust_col": cust_col,
        "first_order_map": first_order_map,
        "lifetime_registry": lifetime_registry,
        "dt_col": date_col,
        "order_id_col": order_id_col,
    }


def _legacy_is_returning(urow: pd.Series, legacy: dict) -> bool:
    """Legacy flat-registry decision for a single row (true if returning)."""
    cust_col = legacy.get("cust_col")
    if not cust_col:
        return False
    c_id = normalize_phone_key(urow.get(cust_col))
    o_dt = urow.get(legacy["dt_col"])
    try:
        o_dt = safe_coerce_datetime_naive(pd.Series([o_dt])).iloc[0]
    except Exception:
        return False
    if not c_id or pd.isna(o_dt):
        return False
    first_dt = legacy["first_order_map"].get(c_id, o_dt)
    reg_dt = get_customer_first_order_date(c_id, legacy["lifetime_registry"])
    if reg_dt and (pd.isna(first_dt) or reg_dt < first_dt):
        first_dt = reg_dt
    return bool(pd.notna(first_dt) and first_dt < o_dt)


def _legacy_compute(
    m_df: pd.DataFrame,
    full_df: pd.DataFrame,
    wc_raw_mapping: dict,
) -> tuple[int, int]:
    """Original flat-registry new/returning computation (kept as fallback)."""
    try:
        date_col = (
            "Date"
            if "Date" in m_df.columns
            else wc_raw_mapping.get("date", "Order Date")
        )
        if date_col not in m_df.columns:
            date_col = pick_column(m_df, DATE_COL_CANDIDATES, m_df.columns[0])
        legacy = _build_legacy_structures(m_df, full_df, wc_raw_mapping, date_col)
        if not legacy["cust_col"]:
            return 0, 0
        order_id_col = legacy["order_id_col"]
        name_col = pick_column(m_df, NAME_COL_CANDIDATES)
        seen = set()
        new_cnt, ret_cnt = 0, 0
        for _, urow in m_df.iterrows():
            oid = urow.get(order_id_col)
            if oid in seen:
                continue
            seen.add(oid)
            c_name = str(urow.get(name_col) or "") if name_col else ""
            if (
                is_walkin_customer(c_name)
                or has_blank_phone(urow)
                or has_blank_address(urow)
            ):
                continue
            if _legacy_is_returning(urow, legacy):
                ret_cnt += 1
            else:
                new_cnt += 1
        return new_cnt, ret_cnt
    except Exception as e:
        log_system_event(
            "COMPUTE_CUSTOMER_MIX_ERROR", f"Failed to compute customer mix: {e}"
        )
        return 0, 0


def load_full_registry_safe() -> dict | None:
    """Load the full 3-bucket registry; return None if it does not exist."""
    try:
        from src.utils.customer_registry_full import load_full_registry

        reg = load_full_registry()
        return reg if reg else None
    except Exception:
        return None
