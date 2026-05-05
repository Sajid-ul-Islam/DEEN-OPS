import math
import io
import re
import streamlit as st
from functools import lru_cache
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

import pandas as pd
from fuzzywuzzy import process


@lru_cache(maxsize=4096)
def normalize_key(val) -> str:
    """Normalize values from Excel/CSV so keys match reliably (e.g., 123.0 -> '123')."""
    if pd.isna(val):
        return ""
    if isinstance(val, (int,)):
        return str(int(val))
    if isinstance(val, (float,)):
        if math.isfinite(val) and float(val).is_integer():
            return str(int(val))
        return str(val).strip()
    s = str(val).strip()
    if s.endswith(".0") and s[:-2].replace(".", "", 1).isdigit():
        s = s[:-2]
    return s


@lru_cache(maxsize=4096)
def normalize_sku(val) -> str:
    """Corrects typos and extra spaces in SKUs for strict but flexible matching."""
    s = normalize_key(val)
    # Remove all spaces and special characters for 'hard' matching, but keep it roughly same
    s = re.sub(r"[^a-zA-Z0-9]", "", s).upper()
    return s


@lru_cache(maxsize=4096)
def normalize_size(val) -> str:
    if pd.isna(val) or val == "":
        return "NO_SIZE"
    s = str(val).strip()
    if not s:
        return "NO_SIZE"
    if s.endswith(".0"):
        s = s[:-2]
    # Normalize common "no size" variants (case-insensitive)
    s_cf = s.casefold()
    if s_cf in {"no_size", "no size", "nosize", "no-size"}:
        return "NO_SIZE"
    return s


@lru_cache(maxsize=4096)
def item_name_to_title_size(item_name: str) -> Tuple[str, str]:
    """
    Convert product list 'Item Name' into (title, size).
    Expected common format: "Title - Size" (split on last ' - ').
    If size can't be parsed, returns ("<item_name>", "NO_SIZE").
    """
    if item_name is None or (isinstance(item_name, float) and math.isnan(item_name)):
        return "", "NO_SIZE"
    s = normalize_key(item_name)
    if not s:
        return "", "NO_SIZE"

    if " - " in s:
        left, right = s.rsplit(" - ", 1)
        title = left.strip()
        size = normalize_size(right.strip())
        if title and size and size != "NO_SIZE":
            return title, size

    return s.strip(), "NO_SIZE"


@lru_cache(maxsize=4096)
def build_title_size_key(title: str, size: str) -> str:
    title_norm = normalize_key(title).strip()
    size_norm = normalize_size(size)
    if not title_norm:
        return ""
    if size_norm and size_norm != "NO_SIZE":
        return f"{title_norm} - {size_norm}".casefold()
    return title_norm.casefold()


def identify_columns(
    df: pd.DataFrame,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Auto-identify relevant columns based on headers (size, qty, title/item name, sku)."""
    cols = [str(c) for c in df.columns]
    cols_map = {c.lower().strip(): c for c in cols}

    size_col = None
    qty_col = None
    title_col = None
    sku_col = None

    for c_lower, c_orig in cols_map.items():
        if "size" in c_lower and size_col is None:
            size_col = c_orig
        if (
            ("quantity" in c_lower) or ("qty" in c_lower) or ("stock" in c_lower)
        ) and qty_col is None:
            qty_col = c_orig
        # Prefer explicit "item name" over generic "title"
        if ("item name" in c_lower or "product name" in c_lower or "product" == c_lower) and title_col is None:
            title_col = c_orig
        elif "title" in c_lower and title_col is None:
            title_col = c_orig
        if "sku" in c_lower and sku_col is None:
            sku_col = c_orig

    if not qty_col and "Quantity" in df.columns:
        qty_col = "Quantity"

    return size_col, qty_col, title_col, sku_col


def get_group_by_column(df: pd.DataFrame) -> Optional[str]:
    """
    Find a column suitable for grouping rows (e.g. same order or same phone together).
    Prefers exact 'Order Number', then other order-like names, then Phone.
    """
    cols = [str(c) for c in df.columns]
    cols_lower = {c: c.lower().strip() for c in cols}
    # Exact match first: "Order Number"
    for c_orig, c_lower in cols_lower.items():
        if c_lower == "order number":
            return c_orig
    for name in (
        "order number",
        "order no",
        "order no.",
        "order #",
        "order id",
        "order",
    ):
        for c_lower, c_orig in cols_lower.items():
            if name in c_lower:
                return c_orig
    for name in ("phone", "phone number", "mobile", "contact"):
        for c_lower, c_orig in cols_lower.items():
            if name in c_lower:
                return c_orig
    return None


def add_title_size_column(
    df: pd.DataFrame, title_col: str, size_col: Optional[str]
) -> pd.DataFrame:
    """Add a 'Title - Size' column to an inventory dataframe."""

    def _joined(r):
        title = normalize_key(r.get(title_col, ""))
        size = "NO_SIZE"
        if size_col and size_col in df.columns:
            size = normalize_size(r.get(size_col, ""))
        if title and size and size != "NO_SIZE":
            return f"{title} - {size}"
        return title

    df = df.copy()
    df["Title - Size"] = df.apply(_joined, axis=1)
    return df


def _read_uploaded(file_obj) -> pd.DataFrame:
    if isinstance(file_obj, pd.DataFrame):
        return file_obj
    file_obj.seek(0)
    if getattr(file_obj, "name", "").endswith(".csv"):
        return pd.read_csv(file_obj)
    return pd.read_excel(file_obj)


def load_inventory_from_uploads(uploaded_files: Dict[str, object]):
    """
    Build inventory mapping from uploaded inventory files.
    Matching is based only on 'Title - Size' (computed from Title + Size).
    """
    inventory: Dict[str, Dict[str, int]] = {}
    sku_to_title_size: Dict[str, str] = (
        {}
    )  # sku_key -> Title-Size key (for SKU match validation)
    all_locations = list(uploaded_files.keys())
    warnings = []
    enriched_dfs: Dict[str, pd.DataFrame] = {}

    for loc_name, file_obj in uploaded_files.items():
        if file_obj is None:
            continue
        try:
            df = _read_uploaded(file_obj)
            size_col, qty_col, title_col, sku_col = identify_columns(df)

            if not title_col:
                warnings.append(
                    f"⚠️ {loc_name}: Missing 'Title/Item Name' column. Skipped."
                )
                continue

            if not qty_col:
                warnings.append(
                    f"⚠️ {loc_name}: Missing 'Quantity' column. Assuming 0 stock."
                )

            df = add_title_size_column(df, title_col=title_col, size_col=size_col)
            enriched_dfs[loc_name] = df

            for _, row in df.iterrows():
                qty = 0
                if qty_col and qty_col in df.columns:
                    try:
                        val = row[qty_col]
                        if pd.notna(val):
                            if isinstance(val, str):
                                val = val.replace(",", "").strip()
                                if val == "":
                                    val = 0
                            qty = int(float(val))
                    except Exception:
                        qty = 0

                joined = normalize_key(row.get("Title - Size", ""))
                key = joined.casefold() if joined else ""
                if key:
                    if key not in inventory:
                        inventory[key] = {loc: 0 for loc in all_locations}
                    inventory[key][loc_name] += qty

                # Also index by SKU and SKU + Size
                if sku_col and sku_col in df.columns:
                    sku_val = row.get(sku_col, "")
                    sku_key = normalize_sku(sku_val)
                    if sku_key:
                        # Fallback pure SKU key (aggregates all sizes for this SKU)
                        if sku_key not in inventory:
                            inventory[sku_key] = {loc: 0 for loc in all_locations}
                        inventory[sku_key][loc_name] += qty
                        sku_to_title_size[sku_key] = (
                            key  # SKU -> Title-Size key for this row
                        )
                        
                        # Master SKU + Size Key
                        size_val = row.get(size_col, "") if size_col and size_col in df.columns else "NO_SIZE"
                        norm_sz = normalize_size(size_val)
                        sku_size_key = f"SKU:{sku_key}_SZ:{norm_sz}"
                        if sku_size_key not in inventory:
                            inventory[sku_size_key] = {loc: 0 for loc in all_locations}
                        inventory[sku_size_key][loc_name] += qty

        except Exception as e:
            warnings.append(f"❌ Error in {loc_name}: {e}")

    return inventory, warnings, enriched_dfs, sku_to_title_size


@st.cache_data(show_spinner="Intelligent Inventory Matching in progress...")
def add_stock_columns_from_inventory(
    product_df: pd.DataFrame,
    item_name_col: str,
    inventory: Dict[str, Dict[str, int]],
    locations: list[str],
    sku_col: Optional[str] = None,
    sku_to_title_size: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, int]:
    """
    Add one column per location to product_df by matching Item Name -> Title - Size,
    or by SKU when available. When matching by SKU, item name must equal that SKU's Title-Size.
    Returns (output_df, matched_row_count).
    """
    df = product_df.copy()
    matched = set()
    sku_to_inv_key = sku_to_title_size or {}

    # Pre-calculate match status and stock keys for each row
    match_statuses = []
    stock_sources = []  # list of inventory keys to pull stock from

    # Helper to safe-get SKU from row
    def get_sku(r):
        if sku_col and sku_col in df.columns:
            val = r.get(sku_col, "")
            if val:
                return normalize_sku(val)
        return ""

    for i, row in df.iterrows():
        # 1. Get Product List SKU and Item Name Key
        pl_sku = get_sku(row)
        title, size = item_name_to_title_size(row.get(item_name_col, ""))
        pl_key = build_title_size_key(title, size)

        inv_key = None
        status = "No Match"

        # 2. MATCHING LOGIC
        sku_size_key = f"SKU:{pl_sku}_SZ:{size}" if pl_sku else ""
        is_embroidered_panjabi = pl_key and "embroidered cotton panjabi" in pl_key

        if is_embroidered_panjabi:
            if pl_sku and sku_size_key in inventory:
                inv_key = sku_size_key
                status = "Perfect Match (SKU + Size - Strict mode)"
            elif pl_sku and pl_sku in sku_to_inv_key:
                inv_key = pl_sku
                status = "SKU Match (Strict mode - Size mismatch)"
            else:
                status = "No Match (Strict SKU required for Embroidered Cotton Panjabi)"
        else:
            # Priority 1: Master SKU + Size Match
            if pl_sku and sku_size_key in inventory:
                inv_key = sku_size_key
                status = "Master SKU + Size Match"

            # Priority 2: Exact Name Match
            elif pl_key and pl_key in inventory:
                inv_key = pl_key
                status = "Exact Name Match"
                if pl_sku:
                    if pl_sku in sku_to_inv_key:
                        status = (
                            "Perfect Match (Name + SKU)"
                            if sku_to_inv_key[pl_sku] == pl_key
                            else f"Name Match (SKU mismatch)"
                        )
                    else:
                        status = "Name Match (SKU not in Inv)"

            # Priority 3: Strict Normalized SKU Match (Ignoring Size)
            elif pl_sku and pl_sku in sku_to_inv_key:
                inv_key = pl_sku
                status = f"SKU Match (Size/Name mismatch -> {sku_to_inv_key[pl_sku]})"

            # Priority 4: Fuzzy Name Match (Correction for typos)
            elif pl_key:
                # We only fuzzy match against pure Title-Size keys
                name_keys = [k for k in inventory.keys() if not k.startswith("SKU:") and k not in sku_to_inv_key]
                if name_keys:
                    match_result = process.extractOne(pl_key, name_keys)
                    if match_result:
                        best_match, score = match_result
                        if score >= 85:  # Require high confidence for auto-match
                            inv_key = best_match
                            status = f"Fuzzy Match ({score}%) -> {best_match}"
                        else:
                            status = f"No Match (Closest: {best_match} @ {score}%)"
                    else:
                        status = "No Match"
                else:
                    status = "No Match"
            else:
                status = "No Match"

        match_statuses.append(status)
        stock_sources.append(inv_key)
        if inv_key:
            matched.add(i)

    # Assign Status Column
    df["Match Status"] = match_statuses

    # 3. Assign Stock Columns & Calculate Fulfillment Summary
    stock_summary = []

    # Try to find a quantity column in the product list (how many did the user order?)
    _, qty_to_buy_col, _, _ = identify_columns(df)

    for i, source_key in enumerate(stock_sources):
        total_avail = 0
        if source_key and source_key in inventory:
            total_avail = sum(inventory[source_key].values())

        # Determine Status
        requested_qty = 1  # Default
        if qty_to_buy_col and qty_to_buy_col in df.columns:
            try:
                val = df.iloc[i][qty_to_buy_col]
                requested_qty = int(float(val)) if pd.notna(val) else 1
            except:
                requested_qty = 1

        if not source_key:
            stock_summary.append("❌ No Match")
        elif total_avail == 0:
            stock_summary.append("❌ OOS")
        elif total_avail >= requested_qty:
            stock_summary.append("✅ Available")
        else:
            stock_summary.append(f"⚠️ Partial ({total_avail}/{requested_qty})")

    df["Fulfillment"] = stock_summary

    # 4. Assign individual location columns
    for loc in locations:
        vals = []
        for i, source_key in enumerate(stock_sources):
            qty = 0
            if source_key and source_key in inventory:
                qty = inventory[source_key].get(loc, 0)
            vals.append(qty)
        df[loc] = vals

    # 5. Intelligent Dispatch Suggestion
    dispatch_suggestions = ["N/A"] * len(df)
    group_col = get_group_by_column(df)

    if group_col:
        # Create a helper for quantities
        qty_needed = [1] * len(df)
        if qty_to_buy_col and qty_to_buy_col in df.columns:
            qty_needed = [
                int(float(x)) if pd.notna(x) else 1 for x in df[qty_to_buy_col]
            ]

        # Group data to optimize per order
        for _, group_indices in df.groupby(group_col).groups.items():
            # For this order, find the best location(s)
            remaining_indices = list(group_indices)

            # 1. Try to find a SINGLE location that can fulfill ALL items in the order
            best_single_loc = None
            for loc in locations:
                all_match = True
                for idx in group_indices:
                    source_key = stock_sources[idx]
                    needed = qty_needed[idx]
                    avail = (
                        inventory.get(source_key, {}).get(loc, 0) if source_key else 0
                    )
                    if avail < needed:
                        all_match = False
                        break
                if all_match:
                    best_single_loc = loc
                    break  # Prioritize Ecom -> Mirpur -> ... as defined in 'locations'

            if best_single_loc:
                for idx in group_indices:
                    dispatch_suggestions[idx] = best_single_loc
            else:
                # 2. Multi-parcel minimization: Find loc with MOST fulfillment, then repeat
                while remaining_indices:
                    best_loc = None
                    max_covered = -1
                    covered_indices = []

                    for loc in locations:
                        current_covered = []
                        for idx in remaining_indices:
                            source_key = stock_sources[idx]
                            needed = qty_needed[idx]
                            avail = (
                                inventory.get(source_key, {}).get(loc, 0)
                                if source_key
                                else 0
                            )
                            if avail >= needed:
                                current_covered.append(idx)

                        if len(current_covered) > max_covered:
                            max_covered = len(current_covered)
                            best_loc = loc
                            covered_indices = current_covered

                    if best_loc and covered_indices:
                        for idx in covered_indices:
                            dispatch_suggestions[idx] = best_loc
                        remaining_indices = [
                            i for i in remaining_indices if i not in covered_indices
                        ]
                    else:
                        # OOS items remaining
                        for idx in remaining_indices:
                            dispatch_suggestions[idx] = "OOS / No Match"
                        break

    df["Dispatch Suggestion"] = dispatch_suggestions

    # Reorder Match Status to the end
    cols = [c for c in df.columns if c != "Match Status"] + ["Match Status"]
    df = df[cols]

    return df, len(matched)
