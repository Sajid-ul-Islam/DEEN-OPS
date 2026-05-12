import math
import io
import re
import copy
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
    if not s or s in ["NAN", "NONE"]:
        return "0"
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
    return s.upper()


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
                        if size_col and size_col in df.columns and pd.notna(row.get(size_col, "")) and str(row.get(size_col, "")).strip():
                            size_val = row.get(size_col, "")
                            norm_sz = normalize_size(size_val)
                        else:
                            _, extracted_size = item_name_to_title_size(row.get(title_col, ""))
                            norm_sz = normalize_size(extracted_size)
                            
                        sku_size_key = f"SKU:{sku_key}_SZ:{norm_sz}"
                        if sku_size_key not in inventory:
                            inventory[sku_size_key] = {loc: 0 for loc in all_locations}
                        inventory[sku_size_key][loc_name] += qty

        except Exception as e:
            warnings.append(f"❌ Error in {loc_name}: {e}")

    return inventory, warnings, enriched_dfs, sku_to_title_size


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
    df = product_df.copy().reset_index(drop=True)
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
                if isinstance(val, (list, dict, set)):
                    val = str(val)
                return normalize_sku(val)
        return ""

    size_col, _, _, _ = identify_columns(df)

    for i, row in df.iterrows():
        # 1. Get Product List SKU and Item Name Key
        pl_sku = get_sku(row)
        raw_item_name = row.get(item_name_col, "")
        if isinstance(raw_item_name, (list, dict, set)):
            raw_item_name = str(raw_item_name)
        title, size = item_name_to_title_size(raw_item_name)
        
        if size_col and size_col in df.columns:
            val = row.get(size_col, "")
            if pd.notna(val) and str(val).strip():
                size = normalize_size(val)

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

    _, qty_to_buy_col, _, _ = identify_columns(df)
    qty_needed = [1] * len(df)
    if qty_to_buy_col and qty_to_buy_col in df.columns:
        def _parse_qty(x):
            if pd.isna(x):
                return 1
            if isinstance(x, str):
                x = x.replace(",", "").strip()
                if x == "":
                    return 1
            try:
                return int(float(x))
            except Exception:
                return 1
        qty_needed = [_parse_qty(x) for x in df[qty_to_buy_col]]

    # 3. Assign individual location columns (Raw original warehouse values)
    for loc in locations:
        vals = []
        for i, source_key in enumerate(stock_sources):
            qty = 0
            if source_key and source_key in inventory:
                qty = inventory[source_key].get(loc, 0)
            vals.append(qty)
        df[loc] = vals

    # 4. Intelligent Dispatch Suggestion & Stock Allocation
    running_inv = copy.deepcopy(inventory)
    
    dispatch_suggestions = [""] * len(df)
    oos_locations_list = [""] * len(df)
    full_order_locs_list = [""] * len(df)
    items_in_order_list = [1] * len(df)
    fulfillment_status = [""] * len(df)

    group_col = get_group_by_column(df)
    temp_group_added = False
    if not group_col:
        df["_temp_group"] = range(len(df))
        group_col = "_temp_group"
        temp_group_added = True

    try:
        for group_val, group_indices in df.groupby(group_col, sort=False).groups.items():
            try:
                num_items = len(group_indices)
                for idx in group_indices:
                    items_in_order_list[idx] = num_items

                def try_allocate(loc_keywords, commit=False):
                    temp_inv = copy.deepcopy(running_inv)
                    success = True
                    for idx in group_indices:
                        source_key = stock_sources[idx]
                        needed = qty_needed[idx]
                        if not source_key or source_key not in temp_inv:
                            success = False
                            break
                        
                        amount_to_find = needed
                        for loc in locations:
                            if any(kw in loc.lower() for kw in loc_keywords):
                                avail = temp_inv[source_key].get(loc, 0)
                                take = min(amount_to_find, avail)
                                temp_inv[source_key][loc] = avail - take
                                amount_to_find -= take
                                if amount_to_find == 0:
                                    break
                                    
                        if amount_to_find > 0:
                            success = False
                            break
                            
                    if success and commit:
                        running_inv.clear()
                        running_inv.update(temp_inv)
                    return success

                full_locs = []
                if try_allocate(["ecom", "mirpur"], commit=False): full_locs.append("Ecom-Mirpur")
                if try_allocate(["wari"], commit=False): full_locs.append("Wari")
                if try_allocate(["cumilla"], commit=False): full_locs.append("Cumilla")
                if try_allocate(["sylhet"], commit=False): full_locs.append("Sylhet")

                full_locs_str = ", ".join(full_locs) if full_locs else "None"
                for idx in group_indices:
                    full_order_locs_list[idx] = full_locs_str

                if try_allocate(["ecom", "mirpur"], commit=True):
                    suggestion = "Ecom-Mirpur"
                elif try_allocate(["wari"], commit=True):
                    suggestion = "Wari"
                elif try_allocate(["cumilla"], commit=True):
                    suggestion = "Cumilla"
                elif try_allocate(["sylhet"], commit=True):
                    suggestion = "Sylhet"
                else:
                    if try_allocate([loc.lower() for loc in locations], commit=True):
                        suggestion = "Multiple / Split"
                    else:
                        suggestion = "OOS / Unfulfillable"

                for idx in group_indices:
                    dispatch_suggestions[idx] = suggestion
                    source_key = stock_sources[idx]
                    needed = qty_needed[idx]

                    if suggestion == "OOS / Unfulfillable":
                        if not source_key:
                            fulfillment_status[idx] = "❌ No Match"
                            oos_locations_list[idx] = "All Locations"
                        else:
                            total_left = sum(running_inv.get(source_key, {}).values())
                            if total_left == 0:
                                fulfillment_status[idx] = "❌ OOS (Stock Exhausted by Prior Orders)"
                            elif total_left < needed:
                                fulfillment_status[idx] = f"⚠️ Partial ({total_left}/{needed} left)"
                            else:
                                fulfillment_status[idx] = "❌ Blocked (Another item in order is OOS)"

                            oos_locs = []
                            for loc in locations:
                                avail = running_inv.get(source_key, {}).get(loc, 0)
                                if avail < needed:
                                    oos_locs.append(loc)
                            if len(oos_locs) == len(locations):
                                oos_locations_list[idx] = "All Locations"
                            elif not oos_locs:
                                oos_locations_list[idx] = "None"
                            else:
                                oos_locations_list[idx] = ", ".join(oos_locs)
                    else:
                        fulfillment_status[idx] = "✅ Available (Allocated)"
                        oos_locations_list[idx] = "None"
            except Exception:
                for idx in group_indices:
                    dispatch_suggestions[idx] = "Error / Unfulfillable"
                    fulfillment_status[idx] = "❌ Processing Error"
                    full_order_locs_list[idx] = "Error"
                    oos_locations_list[idx] = "Error"
    except Exception:
        dispatch_suggestions = ["Error / Unfulfillable"] * len(df)
        fulfillment_status = ["❌ Grouping Error"] * len(df)
        full_order_locs_list = ["Error"] * len(df)
        oos_locations_list = ["Error"] * len(df)

    if temp_group_added:
        df = df.drop(columns=["_temp_group"])
        group_col = None

    df["Full Order Available At"] = full_order_locs_list
    df["Fulfillment"] = fulfillment_status
    df["OOS Locations"] = oos_locations_list
    df["Dispatch Suggestion"] = dispatch_suggestions

    if group_col:
        suffix_map = {
            "Cumilla": " c",
            "Wari": " w",
            "Sylhet": " s"
        }
        def apply_suffix(row):
            orig_val = row[group_col]
            if pd.isna(orig_val):
                return orig_val
            val_str = str(orig_val)
            if isinstance(orig_val, float) and val_str.endswith(".0"):
                val_str = val_str[:-2]
            sugg = row.get("Dispatch Suggestion", "")
            suffix = suffix_map.get(sugg, "")
            return val_str + suffix
            
        df[group_col] = df.apply(apply_suffix, axis=1)

    # Mark unique orders for easy filtering
    if group_col:
        df["Unique Order"] = (~df.duplicated(subset=[group_col])).map({True: "Yes", False: ""})
        df["Items in Order"] = items_in_order_list
    else:
        df["Unique Order"] = "Yes"
        df["Items in Order"] = 1

    # Reorder Match Status to the end
    cols = [c for c in df.columns if c not in ["Match Status", "Unique Order", "Items in Order"]] + ["Items in Order", "Unique Order", "Match Status"]
    df = df[cols]

    return df, len(matched)
