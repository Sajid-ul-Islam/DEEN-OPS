"""Fast customer identity resolution against the full 3-bucket registry.

The registry (resources/customer_registry_full.json) is built offline from all
WooCommerce orders and split into:
  - registered_customers  : customer_id > 0
  - guest_with_email      : guest checkout with a billing email
  - guest_without_email   : guest checkout keyed by phone only

When a NEW order arrives we resolve identity with the priority the business
asked for:
  1. email        (if present)         -> guest/registered bucket match
  2. phone        (multi-format alias) -> guest_without_email / any bucket
  3. name|city    (normalized)         -> loose secondary signal

The function returns the matched record, its bucket, the match method, and the
record's earliest known `first_seen` so callers can decide new vs returning.

This file is the read/lookup layer. Building the JSON is done by
scripts/build_customer_registry.py (run periodically).
"""

from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

from src.config.constants import RESOURCES_DIR
from src.utils.text import normalize_city_name, normalize_phone_number

FULL_REGISTRY_PATH = os.path.join(RESOURCES_DIR, "customer_registry_full.json")

_BUCKETS = ("registered_customers", "guest_with_email", "guest_without_email")


def _norm_text(v: str) -> str:
    if not v:
        return ""
    return " ".join(str(v).strip().lower().split())


def _norm_name(v: str) -> str:
    s = _norm_text(v)
    for ch in ".,-_/()":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _phone_aliases(phone: str) -> list[str]:
    """All normalized forms of a phone number for index lookup.

    Keeps ONE canonical identical key (normalize_phone_number) plus the
    880/+880/leading-zero variants so a new order can be matched regardless
    of which format WooCommerce returns.
    """
    p = normalize_phone_number(phone)
    if not p or "@" in p:
        return []
    out = [p]
    digits = p
    if digits.startswith("0"):
        digits = "88" + digits[1:]  # 017... -> 88017...
        out.append(digits)
        out.append("+" + digits)  # +88017...
        out.append(digits[2:])  # 17...
    return out


_REGISTRY_CACHE = None
_REGISTRY_MTIME = 0


def load_full_registry() -> dict:
    global _REGISTRY_CACHE, _REGISTRY_MTIME
    if not os.path.exists(FULL_REGISTRY_PATH):
        return {}
    try:
        mtime = os.path.getmtime(FULL_REGISTRY_PATH)
        if _REGISTRY_CACHE is not None and mtime == _REGISTRY_MTIME:
            return _REGISTRY_CACHE
        with open(FULL_REGISTRY_PATH, "r", encoding="utf-8") as f:
            _REGISTRY_CACHE = json.load(f)
            _REGISTRY_MTIME = mtime
            return _REGISTRY_CACHE
    except Exception:
        return {}


def update_full_registry_from_df(df: "pd.DataFrame | None") -> int:
    """Incrementally merge a freshly-synced orders DataFrame into the full registry.

    The full 3-bucket registry is built offline (historical orders, incl. the
    registered_customers bucket keyed by WooCommerce customer_id). But the live
    dashboard only pulls a recent window and never re-seeds history, so customers
    whose first order falls inside the live window are missing from the registry
    and get misclassified as 'unknown' (silently counted as new). This function
    closes that gap by merging the incoming live rows into the existing registry,
    keeping each record's earliest ``first_seen``.

    Only the three existing buckets are updated (email / phone / customer_id);
    we never invent name|city keys, since that is only a loose secondary *lookup*
    signal, not a stable identity key.

    Returns the number of records whose ``first_seen`` was updated/added.
    """
    if df is None or df.empty:
        return 0

    from src.processing.data_processing import (  # local import
        safe_coerce_datetime_naive,
    )

    name_col = next(
        (
            c
            for c in ["Full Name (Billing)", "Full Name", "Customer Name", "name"]
            if c in df.columns
        ),
        None,
    )
    city_col = next(
        (
            c
            for c in ["Shipping City", "Billing City", "City", "city"]
            if c in df.columns
        ),
        None,
    )
    date_col = next(
        (c for c in ["Date", "Order Date", "Created Date"] if c in df.columns),
        None,
    )
    if date_col is None:
        date_col = next((c for c in df.columns if "date" in c.lower()), None)
    if not date_col:
        return 0

    reg = load_full_registry()
    if not reg:
        reg = {b: {} for b in _BUCKETS}

    updated = 0
    for _, row in df.iterrows():
        o_dt = safe_coerce_datetime_naive(pd.Series([row.get(date_col)])).iloc[0]
        if pd.isna(o_dt):
            continue
        fs = o_dt.isoformat()

        raw_name = row.get(name_col)
        name = _norm_name(str(raw_name)) if name_col and pd.notnull(raw_name) else ""
        raw_city = row.get(city_col)
        city = (
            normalize_city_name(raw_city) if city_col and pd.notnull(raw_city) else ""
        )

        # Determine bucket + key for THIS row.
        bucket = None
        key = None
        cid = row.get("Customer ID")
        if cid is not None and str(cid).strip() not in ("", "0", "nan", "None"):
            bucket, key = "registered_customers", str(int(float(cid)))
        else:
            email = _norm_text(row.get("Billing Email") or row.get("Email") or "")
            if email and "@" in email:
                bucket, key = "guest_with_email", email
            else:
                phone = row.get("Phone (Billing)") or row.get("Phone") or ""
                p = normalize_phone_number(phone)
                if p:
                    bucket, key = "guest_without_email", p

        if not bucket or not key:
            continue

        rec = reg.setdefault(bucket, {}).get(key)
        if rec is None:
            reg.setdefault(bucket, {})[key] = {
                "name": name,
                "city": city,
                "first_seen": fs,
            }
            updated += 1
        else:
            if fs < rec.get("first_seen", fs):
                rec["first_seen"] = fs
                updated += 1
            # Keep name/city fresh if previously missing.
            if not rec.get("name") and name:
                rec["name"] = name
            if not rec.get("city") and city:
                rec["city"] = city

    if updated > 0:
        try:
            os.makedirs(RESOURCES_DIR, exist_ok=True)
            reg.pop("_name_city_index", None)
            with open(FULL_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=2, ensure_ascii=False)
            global _REGISTRY_CACHE, _REGISTRY_MTIME
            _REGISTRY_CACHE = reg
            _REGISTRY_MTIME = os.path.getmtime(FULL_REGISTRY_PATH)
        except Exception:
            return 0
    return updated


def _get_name_city_index(registry: dict) -> dict[str, dict]:
    """Lazy-build and cache an O(1) index of normalized name|city -> earliest record."""
    if "_name_city_index" in registry:
        return registry["_name_city_index"]

    idx: dict[str, dict] = {}
    for bucket in _BUCKETS:
        for key, rec in (registry.get(bucket) or {}).items():
            if not isinstance(rec, dict):
                continue
            rn = _norm_name(rec.get("name", ""))
            rc = _norm_text(rec.get("city", ""))
            if rn and rc:
                nc = f"{rn}|{rc}"
                entry = {
                    "bucket": bucket,
                    "key": key,
                    "record": rec,
                    "method": "name_city",
                }
                existing = idx.get(nc)
                if existing is None:
                    idx[nc] = entry
                else:
                    fs_new = rec.get("first_seen", "")
                    fs_old = existing["record"].get("first_seen", "")
                    if fs_new and (not fs_old or fs_new < fs_old):
                        idx[nc] = entry

    registry["_name_city_index"] = idx
    return idx


def _lookup_in_bucket(reg: dict, bucket: str, key: str) -> Optional[dict]:
    b = reg.get(bucket) or {}
    rec = b.get(key)
    if rec is None:
        return None
    return {"bucket": bucket, "key": key, "record": rec}


def find_customer(
    billing: dict,
    registry: Optional[dict] = None,
) -> Optional[dict]:
    """Resolve a customer from a WooCommerce `billing` dict.

    Returns dict with keys: bucket, key, record, method, first_seen, last_seen,
    or None if no identity could be matched.
    """
    if registry is None:
        registry = load_full_registry()
    if not registry:
        return None

    email = _norm_text(billing.get("email"))
    phone = billing.get("phone")
    first_name = _norm_name(billing.get("first_name", ""))
    last_name = _norm_name(billing.get("last_name", ""))
    name = f"{first_name} {last_name}".strip()
    city = normalize_city_name(billing.get("city") or "")

    # 1) EMAIL priority (registered or guest-with-email bucket)
    if email and "@" in email:
        for bucket in ("registered_customers", "guest_with_email"):
            rec = _lookup_in_bucket(registry, bucket, email)
            if rec:
                rec["method"] = "email"
                return rec

    # 2) PHONE (multi-format alias) across all buckets
    for alias in _phone_aliases(phone):
        for bucket in _BUCKETS:
            rec = _lookup_in_bucket(registry, bucket, alias)
            if rec:
                rec["method"] = "phone"
                return rec

    # 3) NAME|CITY loose secondary signal (O(1) indexed lookup)
    if name and city:
        nc = f"{name}|{_norm_text(city)}"
        nc_idx = _get_name_city_index(registry)
        match = nc_idx.get(nc)
        if match:
            return dict(match)

    return None


def is_returning(billing: dict, order_date, registry: Optional[dict] = None) -> bool:
    """True if this customer has a known order strictly before `order_date`."""
    cls = classify_customer(billing, order_date, registry)
    return cls == "returning"


def classify_customer(
    billing: dict,
    order_date,
    registry: Optional[dict] = None,
) -> str:
    """Return 'returning', 'new', or 'unknown' for a customer at `order_date`.

    - 'returning' : matched a known identity whose first_seen < order_date
    - 'new'       : matched a known identity whose first_seen >= order_date
                     (this IS their first recorded order)
    - 'unknown'   : no identity matched in the registry at all
    """
    match = find_customer(billing, registry)
    if not match:
        return "unknown"
    fs = match["record"].get("first_seen")
    if not fs:
        return "unknown"
    try:
        first_dt = pd.to_datetime(fs, errors="coerce")
        o_dt = pd.to_datetime(order_date, errors="coerce")
    except Exception:
        return "unknown"
    if pd.isna(first_dt) or pd.isna(o_dt):
        return "unknown"
    if first_dt.tzinfo is not None:
        first_dt = first_dt.tz_localize(None)
    if o_dt.tzinfo is not None:
        o_dt = o_dt.tz_localize(None)
    return "returning" if first_dt < o_dt else "new"
