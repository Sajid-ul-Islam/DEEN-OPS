import math
import re
import copy
from functools import lru_cache
from typing import Dict, Tuple, Optional

import pandas as pd
from rapidfuzz import process


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
        raw_size = right.strip()
        size = normalize_size(raw_size)
        if title and size and size != "NO_SIZE":
            return title, raw_size

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
        elif "name" == c_lower and title_col is None:
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

            # Remove duplicate rows based on SKU and Size matching
            if sku_col and sku_col in df.columns:
                seen_combinations = set()
                rows_to_keep = []
                for idx, row in df.iterrows():
                    sku_val = str(row[sku_col]).strip()
                    norm_sku = normalize_sku(sku_val)
                    
                    size_val = "NO_SIZE"
                    if size_col and size_col in df.columns:
                        size_val = normalize_size(row[size_col])
                    
                    if norm_sku and norm_sku != "0":
                        combo = (norm_sku, size_val)
                        if combo in seen_combinations:
                            # It's a duplicate! Flag it and skip keeping it.
                            warnings.append(
                                f"⚠️ {loc_name}: Duplicate row found and removed for SKU '{sku_val}' and Size '{size_val}'."
                            )
                            continue
                        seen_combinations.add(combo)
                    rows_to_keep.append(idx)
                
                df = df.loc[rows_to_keep]

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
                    if sku_key and sku_key != "0":
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


def sku_has_size_variations(sku_key: str, inventory: dict) -> bool:
    """Check if the inventory maps contain any size-specific keys for this SKU."""
    prefix = f"sku:{sku_key.casefold()}_sz:"
    for key in inventory:
        if str(key).casefold().startswith(prefix):
            sz = str(key)[len(prefix):]
            if sz.upper() != "NO_SIZE":
                return True
    return False


# ── Location priority helpers ────────────────


def _build_location_config(locations, priority_locations):
    """Build location keyword mapping and ordered dispatch labels.
    
    Returns (location_keywords: dict, ordered_labels: list).
    """
    loc_kw = {
        "Ecom-Mirpur": ["ecom", "mirpur"],
        "Wari": ["wari"],
        "Cumilla": ["cumilla"],
        "Sylhet": ["sylhet"],
    }
    for loc in locations:
        if loc not in loc_kw:
            loc_kw[loc] = [loc.lower()]

    if priority_locations:
        ordered = list(priority_locations)
        for loc in locations:
            label = loc if loc not in ["Ecom", "Mirpur"] else "Ecom-Mirpur"
            if label not in ordered:
                ordered.append(label)
    else:
        ordered = ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet"]
        for loc in locations:
            if loc not in ["Ecom", "Mirpur"] and loc not in ordered:
                ordered.append(loc)
    return loc_kw, ordered


def _parse_row_sku(row, sku_col):
    """Safely extract and normalize SKU from a row."""
    if not sku_col or sku_col not in row.index:
        return ""
    val = row.get(sku_col, "")
    if isinstance(val, (list, dict, set)):
        val = str(val)
    return normalize_sku(val)


def _parse_qty_needed(df):
    """Extract quantity needed per row from the quantity column."""
    _, qty_col, _, _ = identify_columns(df)
    if not qty_col or qty_col not in df.columns:
        return [1] * len(df)

    def _parse(x):
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
    return [_parse(x) for x in df[qty_col]]


def _match_row_to_inventory(
    sku, raw_item_name, size_col_val, inventory, sku_to_inv_key
):
    """Determine the best inventory key and match status for a product row.

    Uses a priority system: SKU+Size → Exact Name → SKU-only → Fuzzy Name.
    Returns (inv_key, status).
    """
    raw_item_name = str(raw_item_name) if isinstance(raw_item_name, (list, dict, set)) else raw_item_name
    title, size = item_name_to_title_size(raw_item_name)

    if size_col_val is not None and pd.notna(size_col_val) and str(size_col_val).strip():
        size = normalize_size(size_col_val)

    pl_key = build_title_size_key(title, size)
    sku_size_key = f"SKU:{sku}_SZ:{size}" if (sku and sku != "0") else ""
    is_embroidered = bool(pl_key and "embroidered cotton panjabi" in pl_key)

    if is_embroidered:
        if sku_size_key and sku_size_key in inventory:
            return sku_size_key, "Perfect Match (SKU + Size - Strict mode)"
        if sku and sku != "0" and sku in sku_to_inv_key:
            return sku, "SKU Match (Strict mode - Size mismatch)"
        return None, "No Match (Strict SKU required for Embroidered Cotton Panjabi)"

    # Priority 1: Master SKU + Size
    if sku_size_key and sku_size_key in inventory:
        return sku_size_key, "Master SKU + Size Match"

    # Priority 2: Exact Name Match
    if pl_key and pl_key in inventory:
        if sku and sku != "0" and sku in sku_to_inv_key:
            status = (
                "Perfect Match (Name + SKU)"
                if sku_to_inv_key[sku] == pl_key
                else "Name Match (SKU mismatch)"
            )
        else:
            status = "Name Match (SKU not in Inv)"
        return pl_key, status

    # Priority 3: SKU-only match (no size variations for this SKU)
    if sku and sku != "0" and sku in sku_to_inv_key and not (size != "NO_SIZE" and sku_has_size_variations(sku, inventory)):
        return sku, f"SKU Match (Size/Name mismatch -> {sku_to_inv_key[sku]})"

    # Priority 4: Fuzzy name match
    if pl_key:
        name_keys = [k for k in inventory if not k.startswith("SKU:") and k not in sku_to_inv_key]
        same_size_keys = [
            k for k in name_keys
            if normalize_size(item_name_to_title_size(k)[1]) == normalize_size(size)
        ]
        if same_size_keys:
            match_result = process.extractOne(pl_key, same_size_keys)
            if match_result:
                best_match, score, _ = match_result
                if score >= 85:
                    return best_match, f"Fuzzy Match ({score}%) -> {best_match}"
                return None, f"No Match (Closest: {best_match} @ {score}%)"
    return None, "No Match"


def _assign_location_columns(df, locations, stock_sources, inventory):
    """Add one column per location with raw stock counts."""
    df = df.copy()
    for loc in locations:
        vals = [
            inventory[source_key].get(loc, 0)
            if source_key and source_key in inventory
            else 0
            for source_key in stock_sources
        ]
        df[loc] = vals
    return df


# ── Allocation helpers ────────────────────────


def _get_order_address(df, group_indices):
    """Extract the delivery address from the first row of a group."""
    parts = []
    for addr_col in ["Shipping City", "Shipping Address 1", "Shipping Address", "Address", "City"]:
        if addr_col in df.columns:
            first_idx = group_indices[0]
            val = df.loc[first_idx, addr_col]
            if pd.notna(val):
                parts.append(str(val).lower())
    return " ".join(parts)


def _reorder_labels_by_address(ordered_labels, order_address, loc_kw):
    """Promote the location matching the delivery address to front of the priority list."""
    if not order_address.strip():
        return ordered_labels
    labels = list(ordered_labels)
    for label in labels:
        if label == "Ecom-Mirpur":
            continue
        kws = loc_kw.get(label, [label.lower()])
        if any(kw in order_address for kw in kws):
            labels.remove(label)
            labels.insert(0, label)
            break
    return labels


def _try_allocate_for_group(
    running_inv, stock_sources, qty_needed, group_indices, locations, loc_keywords, commit=False
):
    """Attempt to allocate stock for all items in an order group from locations matching keywords.
    
    If commit=True, the running_inv is permanently updated.
    Returns True if all items could be fully allocated.
    """
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


def _find_suggested_alternatives(title_str, source_key, running_inv):
    """Search for alternative stock items with similar names."""
    alt_list = []
    if not title_str:
        return "No alternative found"
    title_norm = normalize_key(title_str).casefold()
    for k, locs in running_inv.items():
        if str(k).startswith("sku:"):
            continue
        if title_norm in str(k) and k != source_key:
            if sum(locs.values()) > 0:
                alt_list.append(str(k).title())
                if len(alt_list) >= 2:
                    break
    return " | ".join(alt_list) if alt_list else "No alternative found"


def _compute_oos_locations(source_key, needed, locations, running_inv):
    """Determine which locations are out of stock for a given level of need."""
    oos_locs = []
    for loc in locations:
        avail = running_inv.get(source_key, {}).get(loc, 0)
        if avail < needed:
            oos_locs.append(loc)
    if len(oos_locs) == len(locations):
        return "All Locations"
    if not oos_locs:
        return "None"
    return ", ".join(oos_locs)


def _compute_fulfillment_for_oos(idx, suggestion, source_key, needed, running_inv, df, item_name_col, locations):
    """Compute fulfillment status, OOS locations, and alternatives for an OOS item."""
    alt = _find_suggested_alternatives(
        str(item_name_to_title_size(str(df.loc[idx, item_name_col]) if item_name_col in df.columns else "")[0]),
        source_key, running_inv
    )

    if not source_key:
        return "❌ No Match", "All Locations", alt

    total_left = sum(running_inv.get(source_key, {}).values())
    if total_left == 0:
        f_status = "❌ OOS (Stock Exhausted by Prior Orders)"
    elif total_left < needed:
        f_status = f"⚠️ Partial ({total_left}/{needed} left)"
    else:
        f_status = "❌ Blocked (Another item in order is OOS)"

    return f_status, _compute_oos_locations(source_key, needed, locations, running_inv), alt


def _apply_dispatch_suffixes(df, group_col):
    """Append dispatch location suffixes to order ID columns."""
    suffix_map = {"Cumilla": " c", "Wari": " w", "Sylhet": " s"}

    def _apply(row):
        orig_val = row[group_col]
        if pd.isna(orig_val):
            return orig_val
        val_str = str(orig_val)
        if isinstance(orig_val, float) and val_str.endswith(".0"):
            val_str = val_str[:-2]
        suffix = suffix_map.get(row.get("Dispatch Suggestion", ""), "")
        return val_str + suffix

    df[group_col] = df.apply(_apply, axis=1)
    return df


# ── Main function ────────────────────────────


def add_stock_columns_from_inventory(
    product_df: pd.DataFrame,
    item_name_col: str,
    inventory: Dict[str, Dict[str, int]],
    locations: list[str],
    sku_col: Optional[str] = None,
    sku_to_title_size: Optional[Dict[str, str]] = None,
    priority_locations: Optional[list[str]] = None,
) -> Tuple[pd.DataFrame, int]:
    """Add one column per location to product_df by matching Item Name → Title - Size,
    or by SKU when available.

    priority_locations: ordered list of outlet names to try first when suggesting dispatch.
    Defaults to ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet"] if not provided.
    Returns (output_df, matched_row_count).
    """
    loc_kw, ordered_labels = _build_location_config(locations, priority_locations)
    sku_to_inv_key = sku_to_title_size or {}
    df = product_df.copy().reset_index(drop=True)
    size_col, _, _, _ = identify_columns(df)

    # ── Step 1: Match each row to an inventory key ──
    match_statuses = []
    stock_sources = []
    matched = set()

    for i, row in df.iterrows():
        pl_sku = _parse_row_sku(row, sku_col)
        size_col_val = row.get(size_col) if size_col and size_col in df.columns else None
        inv_key, status = _match_row_to_inventory(
            pl_sku, row.get(item_name_col, ""), size_col_val, inventory, sku_to_inv_key
        )
        match_statuses.append(status)
        stock_sources.append(inv_key)
        if inv_key:
            matched.add(i)

    df["Match Status"] = match_statuses
    qty_needed = _parse_qty_needed(df)

    # ── Step 2: Assign raw location columns ──
    df = _assign_location_columns(df, locations, stock_sources, inventory)

    # ── Step 3: Intelligent dispatch suggestion & allocation ──
    running_inv = copy.deepcopy(inventory)
    n = len(df)

    dispatch_suggestions = [""] * n
    oos_locations_list = [""] * n
    full_order_locs_list = [""] * n
    items_in_order_list = [1] * n
    fulfillment_status = [""] * n
    suggested_alternatives = [""] * n
    split_courier_warning = [""] * n

    group_col = get_group_by_column(df)
    temp_group_added = False
    if not group_col:
        df["_temp_group"] = range(n)
        group_col = "_temp_group"
        temp_group_added = True

    try:
        for _group_val, group_indices in df.groupby(group_col, sort=False).groups.items():
            try:
                num_items = len(group_indices)
                for idx in group_indices:
                    items_in_order_list[idx] = num_items

                order_address = _get_order_address(df, group_indices)
                current_labels = _reorder_labels_by_address(ordered_labels, order_address, loc_kw)

                # Find all locations that can fulfill this order
                full_locs = []
                for label in current_labels:
                    kws = loc_kw.get(label, [label.lower()])
                    if _try_allocate_for_group(running_inv, stock_sources, qty_needed, group_indices, locations, kws, commit=False):
                        full_locs.append(label)

                full_locs_str = ", ".join(full_locs) if full_locs else "None"
                for idx in group_indices:
                    full_order_locs_list[idx] = full_locs_str

                # Best single-location suggestion
                suggestion = None
                for label in current_labels:
                    kws = loc_kw.get(label, [label.lower()])
                    if _try_allocate_for_group(running_inv, stock_sources, qty_needed, group_indices, locations, kws, commit=True):
                        suggestion = label
                        break

                if suggestion is None:
                    if _try_allocate_for_group(running_inv, stock_sources, qty_needed, group_indices, locations, [loc.lower() for loc in locations], commit=True):
                        suggestion = "Multiple / Split"
                    else:
                        suggestion = "OOS / Unfulfillable"

                # Populate per-row status columns
                for idx in group_indices:
                    dispatch_suggestions[idx] = suggestion
                    source_key = stock_sources[idx]
                    needed = qty_needed[idx]

                    if suggestion == "Multiple / Split":
                        split_courier_warning[idx] = "⚠️ Est. ৳60+ Extra Cost"

                    if suggestion == "OOS / Unfulfillable":
                        f_status, oos_locs, alt = _compute_fulfillment_for_oos(
                            idx, suggestion, source_key, needed, running_inv, df, item_name_col, locations
                        )
                        fulfillment_status[idx] = f_status
                        oos_locations_list[idx] = oos_locs
                        suggested_alternatives[idx] = alt
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
        dispatch_suggestions = ["Error / Unfulfillable"] * n
        fulfillment_status = ["❌ Grouping Error"] * n
        full_order_locs_list = ["Error"] * n
        oos_locations_list = ["Error"] * n

    if temp_group_added:
        df = df.drop(columns=["_temp_group"])
        group_col = None

    df["Full Order Available At"] = full_order_locs_list
    df["Fulfillment"] = fulfillment_status
    df["OOS Locations"] = oos_locations_list
    df["Dispatch Suggestion"] = dispatch_suggestions
    df["Suggested Alternative"] = suggested_alternatives
    df["Split Courier Warning"] = split_courier_warning

    if group_col:
        df = _apply_dispatch_suffixes(df, group_col)
        df["Unique Order"] = (~df.duplicated(subset=[group_col])).map({True: "Yes", False: ""})
        df["Items in Order"] = items_in_order_list
    else:
        df["Unique Order"] = "Yes"
        df["Items in Order"] = 1

    cols = [c for c in df.columns if c not in ["Match Status", "Unique Order", "Items in Order"]] + ["Items in Order", "Unique Order", "Match Status"]
    df = df[cols]

    return df, len(matched)
