"""SIP (Stock & Inventory Plugin) Item-Wise Outlet Processor.

Parses multi-outlet routing information stored as JSON in the SIP column
of order exports (e.g., WooCommerce exports) and maps each line item within
an order to its specific dispatch outlet.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from src.config.constants import bd_today
from src.utils.product import get_size_from_name

PATHAO_COLUMNS: List[str] = [
    "ItemType",
    "StoreName",
    "MerchantOrderId",
    "RecipientName(*)",
    "RecipientPhone(*)",
    "RecipientAddress(*)",
    "RecipientCity(*)",
    "RecipientZone(*)",
    "RecipientArea",
    "AmountToCollect(*)",
    "ItemQuantity",
    "ItemWeight",
    "ItemDesc",
    "SpecialInstruction",
    "WarehouseOutlet",
]

# Canonical display names for known outlet slugs
OUTLET_CANONICAL_NAMES: Dict[str, str] = {
    "warehouse": "Warehouse",
    "wh": "Warehouse",
    "ecom": "Warehouse",
    "mirpur-12": "Mirpur",
    "mirpur 12": "Mirpur",
    "mirpur": "Mirpur",
    "cumilla": "Cumilla",
    "comilla": "Cumilla",
    "wari": "Wari",
    "sylhet": "Sylhet",
    "uttara": "Uttara",
    "chittagong": "Chittagong",
}

# ── Semantic column auto-mapping ────────────────────────────────────────────
# Logical role -> candidate column names, ordered by match priority. Used by
# auto_map_columns() to pre-fill the SIP mapper's column-selection UI so the
# user only needs to adjust a wrong guess, not map everything by hand.
SIP_COLUMN_CANDIDATES: Dict[str, List[str]] = {
    "order": [
        "Order Number",
        "Order ID",
        "Order #",
        "order_id",
        "Order_ID",
        "Invoice Number",
        "ID",
        "order_number",
    ],
    "sip": [
        "SIP",
        "sip",
        "SIP Stock",
        "Outlet SIP",
        "Outlet Stock",
        "SIP Outlet",
        "Routing",
        "Outlet Routing",
    ],
    "item": [
        "Item Name",
        "Product Name",
        "Product",
        "Item",
        "Title",
        "item_name",
        "product_name",
        "description",
        "name",
    ],
    "sku": [
        "SKU",
        "Item SKU",
        "Product SKU",
        "SKU Code",
        "sku",
        "Item_SKU",
        "Product_SKU",
        "Barcode",
    ],
    "qty": [
        "Quantity",
        "Qty",
        "Item Quantity",
        "Total Quantity",
        "quantity",
        "qty",
        "Units",
        "Count",
    ],
    "name": [
        "Full Name (Shipping)",
        "Full Name (Billing)",
        "Shipping Name",
        "Customer Name",
        "Full Name",
        "Name",
        "name",
    ],
    "phone": [
        "Phone (Shipping)",
        "Phone (Billing)",
        "Shipping Phone",
        "Billing Phone",
        "Phone",
        "Mobile",
        "phone",
    ],
    "address": [
        "Address 1&2 (Shipping)",
        "Shipping Address 1",
        "Address 1",
        "Shipping Address",
        "Billing Address 1",
        "Address",
        "address",
    ],
    "city": [
        "City (Shipping)",
        "Shipping City",
        "Billing City",
        "City",
        "city",
        "District",
    ],
    "cost": [
        "Item Cost",
        "Item Price",
        "Unit Price",
        "Price",
        "item_cost",
        "cost",
        "rate",
    ],
}


def _norm_header(s: Any) -> str:
    """Alphanumeric-only lowercase key for tolerant header comparison."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def auto_map_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Detect the best column for each logical role in the SIP mapper.

    Strategy per role: exact header match, then normalized alphanumeric match
    (ignoring case/spaces/underscores/hyphens), then substring containment.
    Returns a dict mapping every role in SIP_COLUMN_CANDIDATES to the detected
    column name, or None when nothing plausible exists in the DataFrame.
    """
    detected: Dict[str, Optional[str]] = {}
    if df is None or len(df.columns) == 0:
        return {role: None for role in SIP_COLUMN_CANDIDATES}

    cols = list(df.columns)
    exact_map = {str(c).strip().lower(): c for c in cols}
    norm_map: Dict[str, str] = {}
    for c in cols:
        norm_map.setdefault(_norm_header(c), c)

    used: set = set()  # one physical column cannot serve two roles
    for role, candidates in SIP_COLUMN_CANDIDATES.items():
        found: Optional[str] = None
        # 1. Exact (case/whitespace-insensitive)
        for cand in candidates:
            col = exact_map.get(str(cand).strip().lower())
            if col is not None and col not in used:
                found = col
                break
        # 2. Normalized alphanumeric match
        if found is None:
            for cand in candidates:
                col = norm_map.get(_norm_header(cand))
                if col is not None and col not in used:
                    found = col
                    break
        # 3. Substring containment (candidate in header or header in candidate)
        if found is None:
            for cand in candidates:
                c_norm = _norm_header(cand)
                if len(c_norm) < 3:
                    continue
                for col in cols:
                    if col in used:
                        continue
                    h_norm = _norm_header(col)
                    if c_norm in h_norm or (len(h_norm) >= 3 and h_norm in c_norm):
                        found = col
                        break
                if found is not None:
                    break
        if found is not None:
            used.add(found)
        detected[role] = found
    return detected


def normalize_outlet_name(slug: Any, canonical: bool = True) -> str:
    """Normalize an outlet slug into a clean display title.

    Args:
        slug: The raw outlet slug or name (e.g., 'mirpur-12', 'warehouse').
        canonical: If True, maps to standard brand names (e.g. 'Mirpur').
                   If False, formats the raw slug into title case (e.g. 'Mirpur-12').

    Returns:
        Formatted outlet name string.
    """
    if slug is None or pd.isna(slug):
        return "Warehouse"

    s = str(slug).strip()
    if not s:
        return "Warehouse"

    s_lower = s.lower()
    if canonical and s_lower in OUTLET_CANONICAL_NAMES:
        return OUTLET_CANONICAL_NAMES[s_lower]

    # Clean formatting for custom or unlisted outlets
    cleaned = s.replace("_", " ").strip()
    if canonical:
        cleaned = cleaned.replace("-", " ")
    return cleaned.title()


def parse_sip_field(val: Any) -> List[Dict[str, Any]]:
    """Safely parse the SIP column value into a list of item dictionaries.

    Handles valid JSON strings, already-parsed lists/dicts, None/NaN, and
    raw text fallback values.

    Args:
        val: The raw cell value from the SIP column.

    Returns:
        A list of dictionaries representing item outlet routing.
    """
    if val is None or pd.isna(val):
        return []

    if isinstance(val, list):
        return [item for item in val if isinstance(item, dict)]

    if isinstance(val, dict):
        return [val]

    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null", "[]"):
        return []

    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        # Graceful fallback: If it is a plain text outlet name like "warehouse" or "mirpur"
        return [{"outlet_slug": s}]

    return []


def process_order_item_outlets(
    df: pd.DataFrame,
    order_col: str = "Order Number",
    sip_col: str = "SIP",
    target_col: str = "Item Outlet",
    canonical: bool = True,
    default_outlet: str = "Warehouse",
) -> pd.DataFrame:
    """Extract item-wise outlet assignments and append as a new column.

    For each unique order:
    - If the order has 1 item, the outlet is extracted from the single SIP entry.
    - If the order has multiple items, the 1st row matches index 0 in the SIP JSON array,
      the 2nd row matches index 1, and so on.
    - Inserts target_col immediately adjacent to sip_col for clear comparison.

    Args:
        df: Input DataFrame containing order line items.
        order_col: Column name identifying the order.
        sip_col: Column name containing the SIP JSON routing data.
        target_col: New column name to create.
        canonical: Whether to canonicalize outlet names (e.g. 'mirpur-12' -> 'Mirpur').
        default_outlet: Fallback outlet name when SIP is missing.

    Returns:
        DataFrame copy with target_col added and placed next to sip_col.
    """
    if df.empty:
        df_empty = df.copy()
        df_empty[target_col] = []
        return df_empty

    df_out = df.copy()

    # If required columns do not exist, populate default and return
    if order_col not in df_out.columns or sip_col not in df_out.columns:
        df_out[target_col] = default_outlet
        return df_out

    item_outlets: List[str] = []

    # Process grouped by order_col preserving existing row order
    for _, group in df_out.groupby(order_col, sort=False):
        # Find first non-empty SIP value in the group
        sip_val: Optional[Any] = None
        for val in group[sip_col]:
            if pd.notna(val) and str(val).strip():
                sip_val = val
                break

        parsed_items = parse_sip_field(sip_val)
        num_rows = len(group)

        for idx in range(num_rows):
            if idx < len(parsed_items):
                item_data = parsed_items[idx]
                slug = (
                    item_data.get("outlet_slug")
                    or item_data.get("outlet_name")
                    or item_data.get("name")
                )
                item_outlets.append(normalize_outlet_name(slug, canonical=canonical))
            else:
                # If more rows than JSON entries, fallback to last known outlet or default
                if parsed_items:
                    last_slug = parsed_items[-1].get("outlet_slug") or parsed_items[
                        -1
                    ].get("outlet_name")
                    item_outlets.append(
                        normalize_outlet_name(last_slug, canonical=canonical)
                    )
                else:
                    item_outlets.append(default_outlet)

    df_out[target_col] = item_outlets

    # Reorder columns so target_col sits immediately next to sip_col
    cols = df_out.columns.tolist()
    if sip_col in cols and target_col in cols:
        cols.remove(target_col)
        sip_idx = cols.index(sip_col)
        cols.insert(sip_idx + 1, target_col)
        df_out = df_out[cols]

    return df_out


def compute_sip_stats(
    df: pd.DataFrame,
    order_col: str = "Order Number",
    outlet_col: str = "Item Outlet",
) -> Dict[str, Any]:
    """Compute summary statistics regarding outlet allocations and split orders.

    Args:
        df: DataFrame processed by process_order_item_outlets.
        order_col: Order identification column name.
        outlet_col: Target outlet column name.

    Returns:
        Dictionary containing metric counts and split order breakdown.
    """
    total_items = len(df)
    if total_items == 0 or order_col not in df.columns or outlet_col not in df.columns:
        return {
            "total_items": 0,
            "total_orders": 0,
            "multi_item_orders": 0,
            "split_orders_count": 0,
            "split_orders": [],
            "outlet_counts": {},
        }

    total_orders = df[order_col].nunique()
    outlet_counts = df[outlet_col].value_counts().to_dict()

    multi_item_orders = 0
    split_orders = []

    for order_id, group in df.groupby(order_col, sort=False):
        num_items = len(group)
        if num_items > 1:
            multi_item_orders += 1

        unique_outlets = group[outlet_col].dropna().unique().tolist()
        if len(unique_outlets) > 1:
            split_orders.append(
                {
                    "order_id": order_id,
                    "item_count": num_items,
                    "outlets": unique_outlets,
                    "summary": " + ".join(unique_outlets),
                }
            )

    return {
        "total_items": total_items,
        "total_orders": total_orders,
        "multi_item_orders": multi_item_orders,
        "split_orders_count": len(split_orders),
        "split_orders": split_orders,
        "outlet_counts": outlet_counts,
    }


def generate_outlet_product_listing(
    df: pd.DataFrame,
    outlet: str = "Warehouse",
    item_col: str = "Item Name",
    qty_col: str = "Quantity",
    sku_col: Optional[str] = "SKU",
    outlet_col: str = "Item Outlet",
) -> pd.DataFrame:
    """Generate aggregated product picking list filtered by a specific outlet (default: Warehouse).

    Filters rows matching the given outlet (case-insensitive, or all if outlet=='All'),
    coerces quantity to numeric, groups by Item Name and SKU, and sorts alphabetically.

    Args:
        df: DataFrame containing line items with the outlet_col present.
        outlet: Name of the outlet to filter for (e.g. 'Warehouse'). Use 'All' for all outlets.
        item_col: Column name containing the item or product name.
        qty_col: Column name containing item quantity.
        sku_col: Optional column name for SKU code.
        outlet_col: Column name containing the assigned outlet.

    Returns:
        Aggregated DataFrame with Item Name, SKU (if present), and total Quantity.
    """
    if df.empty or item_col not in df.columns:
        return pd.DataFrame()

    filtered_df = df.copy()
    if outlet_col in filtered_df.columns and outlet and outlet.lower() != "all":
        outlet_mask = (
            filtered_df[outlet_col].astype(str).str.strip().str.lower()
            == outlet.strip().lower()
        )
        filtered_df = filtered_df[outlet_mask]

    if filtered_df.empty:
        return pd.DataFrame()

    # Quantity column is optional; when missing, treat every line as 1 unit.
    has_qty = qty_col in filtered_df.columns
    if has_qty:
        filtered_df[qty_col] = pd.to_numeric(
            filtered_df[qty_col].astype(str).str.replace(r"[^\d.-]", "", regex=True),
            errors="coerce",
        ).fillna(1)
    else:
        qty_col = "__qty_placeholder__"
        filtered_df[qty_col] = 1

    group_cols = [item_col]
    use_sku = bool(sku_col and sku_col != "None" and sku_col in filtered_df.columns)
    if use_sku:
        group_cols.append(sku_col)

    aggregated = (
        filtered_df.groupby(group_cols, as_index=False)[qty_col]
        .sum()
        .reset_index(drop=True)
    )

    # Sort alphabetically item-wise, then SKU-wise
    sort_cols = [item_col]
    if use_sku:
        sort_cols.append(sku_col)

    aggregated = aggregated.sort_values(
        by=sort_cols,
        ascending=True,
        key=lambda col: col.astype(str).str.lower(),
        na_position="last",
    ).reset_index(drop=True)

    return aggregated


def get_fulfillment_group(outlet_name: Any) -> Tuple[str, str, str]:
    """Map an outlet name to its dispatch group, order ID suffix, and warehouse label.

    Warehouse and Mirpur are treated as ONE group (dispatched together from Mirpur)
    and retain the default Order ID with no suffix.

    Returns:
        Tuple of (group_name, suffix, warehouse_outlet_label).
    """
    out = str(outlet_name).strip().lower()
    if (
        out
        in (
            "warehouse",
            "mirpur",
            "mirpur-12",
            "mirpur 12",
            "ecom",
            "wh",
            "default",
        )
        or "ecom-mirpur" in out
        or "ecom mirpur" in out
    ):
        return "Warehouse", "", "Warehouse"
    elif "cumilla" in out or "comilla" in out:
        return "Cumilla", " c", "Cumilla Outlet"
    elif "sylhet" in out:
        return "Sylhet", " s", "Sylhet Outlet"
    elif "wari" in out:
        return "Wari", " w", "Wari Outlet"
    else:
        clean = out.replace("-", " ").title()
        initial = clean[0].lower() if clean else "o"
        return clean, f" {initial}", f"{clean} Outlet"


def is_inside_dhaka(city: Any, address: Any, order_total_diff: float = 0.0) -> bool:
    """Determine whether an order destination is inside or outside Dhaka.

    Checks known delivery charge differences first (50 vs 90), then falls back
    to geographic keyword matching.
    """
    if order_total_diff == 50 or order_total_diff == 50.0:
        return True
    if order_total_diff == 90 or order_total_diff == 90.0:
        return False

    combined = (str(city) + " " + str(address)).lower()
    dhaka_keywords = [
        "dhaka",
        "savar",
        "ashulia",
        "keraniganj",
        "gazipur",
        "palash",
        "bhairob",
        "tongi",
        "narayanganj",
        "demra",
        "dhamrai",
    ]
    return any(k in combined for k in dhaka_keywords)


def _ensure_space_after_dots(text: str) -> str:
    """Insert a missing space after '.' when it sits between two letters.

    'Md.Kefayoth' -> 'Md. Kefayoth' and 'Rh.Dorga' -> 'Rh. Dorga'. Unicode
    aware, so it also applies to Bangla including combining vowel signs
    ('কি.খা' -> 'কি. খা'). Dots adjacent to digits (decimals like '3.5' or
    Bangla '১.৫') and separator runs ('...') are left untouched.
    """
    return re.sub(r"(?<=[^\s.,;|\u0964\d])\.(?=[^\s.,;|\u0964\d])", ". ", text)


def normalize_recipient_name(raw_name: Any) -> str:
    """Normalize a recipient name for Pathao consignments.

    Strips whitespace, drops NaN/placeholder junk values, collapses runs of
    whitespace, inserts a missing space after '.' between letters
    ('Md.Kefayoth' -> 'Md. Kefayoth'), title-cases so courier labels are
    consistent (e.g. '  mD. rAKIB   hassan ' -> 'Md. Rakib Hassan'), and
    removes duplicated or redundant words so 'Sakib SAKIB' -> 'Sakib' and
    'Md. Rakib Md. Rakib' -> 'Md. Rakib'. Bangla names pass through safely:
    title-casing is a no-op on Bangla (uncased) script and duplicate words in
    Bangla are filtered the same way. Returns '' when nothing usable remains.
    """
    if raw_name is None:
        return ""
    try:
        if pd.isna(raw_name):
            return ""
    except (TypeError, ValueError):
        pass
    name = " ".join(str(raw_name).split())
    if not name or name.lower() in ("nan", "none", "null", "n/a", "-"):
        return ""
    name = _ensure_space_after_dots(name)
    name = name.title()
    # Drop repeated (duplicate/redundant) words while preserving order
    deduped: List[str] = []
    for word in name.split():
        if word not in deduped:
            deduped.append(word)
    return " ".join(deduped)


def normalize_recipient_address(raw_address: Any) -> str:
    """Normalize a recipient address for Pathao consignments.

    Collapses all whitespace runs to single spaces, converts every separator
    (comma/semicolon/pipe and the Bangla danda '\u0964') into a single ', ' so
    the address reads as clean comma-separated parts (e.g. 'Road Name, City
    Name, District Name'), inserts a missing space after '.' between letters,
    strips leading/trailing separators, and title-cases for courier
    readability. Bangla addresses pass through safely (title-casing is a
    no-op on the uncased Bangla script). Returns '' when nothing usable
    remains.
    """
    if raw_address is None:
        return ""
    try:
        if pd.isna(raw_address):
            return ""
    except (TypeError, ValueError):
        pass
    addr = " ".join(str(raw_address).split())
    if not addr or addr.lower() in ("nan", "none", "null", "n/a", "-"):
        return ""
    addr = _ensure_space_after_dots(addr)
    # Each run of separators (comma/semicolon/pipe/Bangla danda, whitespace
    # between them allowed) becomes a single ', '
    addr = re.sub(r"\s*[,;|\u0964]+(?:\s*[,;|\u0964]+)*", ", ", addr)
    addr = re.sub(r"\s*,\s*$", "", addr)  # trailing separator
    addr = re.sub(r"^\s*,\s*", "", addr)  # leading separator
    addr = " ".join(addr.split())
    return addr.title()


def normalize_phone_number(raw_phone: Any) -> str:
    """Extract and format standard 11-digit Bangladesh phone number."""
    if raw_phone is None or pd.isna(raw_phone):
        return ""
    digits = re.sub(r"\D", "", str(raw_phone).replace(".0", ""))
    if len(digits) == 10 and digits.startswith("1"):
        return "0" + digits
    if len(digits) == 13 and digits.startswith("880"):
        return digits[2:]
    return digits


def generate_pathao_bulk_consignments(
    df: pd.DataFrame,
    store_name: str = "DEEN",
    inside_dhaka_fee: int = 50,
    outside_dhaka_fee: int = 90,
    default_weight: str = "0.5",
    order_col: str = "Order Number",
    sip_col: str = "SIP",
    target_col: str = "Item Outlet",
    sku_col: Optional[str] = "SKU",
) -> pd.DataFrame:
    """Generate Pathao Bulk Upload format from orders with SIP item-wise outlets.

    Handles split-outlet orders by creating multiple consignments:
    - Items from Warehouse and Mirpur are dispatched together with no suffix.
    - Items from Cumilla receive suffix ' c'.
    - Items from Sylhet receive suffix ' s'.
    - Items from Wari receive suffix ' w'.
    - The first dispatch includes the delivery fee (50 inside Dhaka, 90 outside Dhaka).
    - Subsequent dispatches for the same order only include their respective item costs.

    Recipient names are normalized with duplicate/redundant words removed,
    addresses are normalized into comma-separated parts, and each ItemDesc
    entry follows the 'Item Name x{qty} - SKU;' style (duplicate line items
    merged, joined by '; ' when a SKU column is available). Consignments with
    more than 2 distinct items get an '(n items)' suffix.
    """
    if df.empty:
        return pd.DataFrame(columns=PATHAO_COLUMNS)

    # Ensure outlet assignment is present
    if target_col not in df.columns:
        processed_df = process_order_item_outlets(
            df=df,
            order_col=order_col,
            sip_col=sip_col,
            target_col=target_col,
        )
    else:
        processed_df = df.copy()

    actual_order_col = (
        order_col if order_col in processed_df.columns else processed_df.columns[0]
    )
    consignments: List[Dict[str, Any]] = []

    # Detect address and city columns
    name_col = (
        "Full Name (Shipping)"
        if "Full Name (Shipping)" in processed_df.columns
        else "Name"
    )
    phone_col = (
        "Phone (Shipping)" if "Phone (Shipping)" in processed_df.columns else "Phone"
    )
    addr_col = (
        "Address 1&2 (Shipping)"
        if "Address 1&2 (Shipping)" in processed_df.columns
        else "Address"
    )
    city_col = (
        "City (Shipping)" if "City (Shipping)" in processed_df.columns else "City"
    )
    cost_col = "Item Cost" if "Item Cost" in processed_df.columns else None
    qty_col = "Quantity" if "Quantity" in processed_df.columns else None
    item_col = (
        "Item Name" if "Item Name" in processed_df.columns else processed_df.columns[1]
    )

    for order_id, order_group in processed_df.groupby(actual_order_col, sort=False):
        first_row = order_group.iloc[0]

        recipient_name = (
            normalize_recipient_name(first_row.get(name_col, ""))
            if name_col in first_row
            else ""
        )
        recipient_phone = normalize_phone_number(first_row.get(phone_col, ""))
        address_val = (
            normalize_recipient_address(first_row.get(addr_col, ""))
            if addr_col in first_row
            else ""
        )
        city_val = (
            str(first_row.get(city_col, "")).strip() if city_col in first_row else ""
        )
        if city_val.lower() in ("", "nan"):
            city_val = ""
        else:
            city_val = city_val.title()

        # Resolve the effective SKU column for ItemDesc annotation
        eff_sku_col: Optional[str] = None
        if sku_col and sku_col != "None" and sku_col in processed_df.columns:
            eff_sku_col = sku_col
        else:
            for cand in SIP_COLUMN_CANDIDATES["sku"]:
                if cand in processed_df.columns:
                    eff_sku_col = cand
                    break

        # Payment & COD check
        payment_method = str(first_row.get("Payment Method Title", "")).lower()
        is_paid = any(
            kw in payment_method
            for kw in ["online", "ssl", "bkash", "card", "prepaid", "paid"]
        )

        # Delivery fee calculation
        total_order_amount = (
            pd.to_numeric(first_row.get("Order Total Amount", 0), errors="coerce") or 0
        )
        items_cost_sum = (
            pd.to_numeric(order_group[cost_col], errors="coerce").fillna(0).sum()
            if cost_col
            else 0
        )
        diff = float(total_order_amount - items_cost_sum) if items_cost_sum else 0.0

        delivery_fee = (
            inside_dhaka_fee
            if is_inside_dhaka(city_val, address_val, diff)
            else outside_dhaka_fee
        )

        customer_note = (
            str(first_row.get("Customer Note", "")).strip()
            if pd.notna(first_row.get("Customer Note"))
            else ""
        )
        if customer_note.lower() == "nan":
            customer_note = ""

        # Map each item to its fulfillment group
        grp_tuples = [get_fulfillment_group(out) for out in order_group[target_col]]
        order_group = order_group.copy()
        order_group["_grp_name"] = [t[0] for t in grp_tuples]
        order_group["_grp_suffix"] = [t[1] for t in grp_tuples]
        order_group["_grp_outlet"] = [t[2] for t in grp_tuples]

        # Order groups so Warehouse/Mirpur is first dispatch if present
        unique_groups: List[str] = []
        for g in order_group["_grp_name"]:
            if g not in unique_groups:
                unique_groups.append(g)

        if "Warehouse" in unique_groups and unique_groups[0] != "Warehouse":
            unique_groups.remove("Warehouse")
            unique_groups.insert(0, "Warehouse")

        is_split = len(unique_groups) > 1

        for idx, grp_name in enumerate(unique_groups):
            grp_items = order_group[order_group["_grp_name"] == grp_name]
            suffix = grp_items["_grp_suffix"].iloc[0]
            outlet_label = grp_items["_grp_outlet"].iloc[0]

            merchant_order_id = f"{order_id}{suffix}"

            # Sum item cost for this consignment
            if cost_col:
                grp_cost = (
                    pd.to_numeric(grp_items[cost_col], errors="coerce").fillna(0).sum()
                )
            else:
                grp_cost = total_order_amount if idx == 0 else 0

            if is_paid:
                amount_to_collect = 0
            else:
                if idx == 0:
                    amount_to_collect = int(round(grp_cost + delivery_fee))
                else:
                    amount_to_collect = int(round(grp_cost))

            # Build Item Description — deduped "Item x{qty} - SKU;" entries
            # joined by '; ', with an '(n items)' tag when more than 2
            # distinct items are present.
            if qty_col and item_col:
                merged_items: Dict[Tuple[str, str], int] = {}
                item_order: List[Tuple[str, str]] = []
                for _, r in grp_items.iterrows():
                    item_name = " ".join(str(r[item_col]).split())
                    sku_val = ""
                    if eff_sku_col:
                        sku_val = str(r.get(eff_sku_col, "")).strip()
                        if sku_val.lower() in ("nan", "none", "null", "n/a", "0"):
                            sku_val = ""
                    key = (item_name, sku_val)
                    if key not in merged_items:
                        merged_items[key] = 0
                        item_order.append(key)
                    qty_num = pd.to_numeric(r[qty_col], errors="coerce")
                    qty_int = int(qty_num) if pd.notna(qty_num) and qty_num > 0 else 1
                    merged_items[key] += qty_int
                item_desc_list = []
                for item_name, sku_val in item_order:
                    entry = f"{item_name} x{merged_items[(item_name, sku_val)]}"
                    if sku_val:
                        entry += f" - {sku_val}"
                    item_desc_list.append(entry)
                item_desc = "; ".join(item_desc_list)
                if item_desc:
                    item_desc += ";"
                    if len(item_desc_list) > 2:
                        item_desc += f" ({len(item_desc_list)} items)"
                total_qty = int(
                    pd.to_numeric(grp_items[qty_col], errors="coerce").fillna(1).sum()
                )
            else:
                item_desc = f"Items ({len(grp_items)})"
                total_qty = len(grp_items)

            # Special Instruction
            inst_parts = []
            if is_split:
                inst_parts.append(
                    f"Split Part {idx + 1}/{len(unique_groups)} [{grp_name}]"
                )
            if customer_note:
                inst_parts.append(customer_note)
            special_instruction = " | ".join(inst_parts)

            consignments.append(
                {
                    "ItemType": "Parcel",
                    "StoreName": store_name,
                    "MerchantOrderId": merchant_order_id,
                    "RecipientName(*)": recipient_name,
                    "RecipientPhone(*)": recipient_phone,
                    "RecipientAddress(*)": address_val,
                    "RecipientCity(*)": city_val,
                    "RecipientZone(*)": city_val,
                    "RecipientArea": "",
                    "AmountToCollect(*)": amount_to_collect,
                    "ItemQuantity": total_qty,
                    "ItemWeight": default_weight,
                    "ItemDesc": item_desc,
                    "SpecialInstruction": special_instruction,
                    "WarehouseOutlet": outlet_label,
                }
            )

    out_df = pd.DataFrame(consignments)
    for col in PATHAO_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""

    return out_df[PATHAO_COLUMNS]


def convert_sip_to_smart_inventory(
    df: pd.DataFrame,
    order_col: str = "Order Number",
    sip_col: str = "SIP",
    target_col: str = "Item Outlet",
    item_col: str = "Item Name",
    sku_col: Optional[str] = "SKU",
    qty_col: str = "Quantity",
    price_col: Optional[str] = "Item Cost",
    size_col: Optional[str] = None,
) -> pd.DataFrame:
    """Convert SIP-mapped order line items into the Smart Inventory CSV format.

    Takes an order export with item-wise outlet routing (SIP JSON ->
    'Item Outlet' column) and aggregates the required units per
    Product/Size/SKU/Outlet combination, emitting the unified Smart Inventory
    'Current Stock Report' structure:

        Product, Size, SKU, Outlet, Stock Qty, Price, Last Updated

    The Stock Qty column carries the aggregated units required by open orders
    per outlet (i.e. a demand sheet in stock-report shape), so the output can
    be compared against live outlet stock or fed back into any tooling that
    consumes the Smart Inventory CSV layout.

    Args:
        df: Order export DataFrame (SIP column optional if target_col exists).
        order_col: Column identifying the order.
        sip_col: Column containing the SIP JSON routing data.
        target_col: Outlet-assignment column (created from SIP when missing).
        item_col: Column containing the product/item name.
        sku_col: Optional SKU column; None disables SKU output (reported as '-').
        qty_col: Column containing per-line quantity (each row counts as 1 when missing).
        price_col: Optional per-unit price column for the Price column.
        size_col: Optional explicit size column. Falls back to parsing
            "Product - Size" from the item name.

    Returns:
        DataFrame with Product, Size, SKU, Outlet, Stock Qty, Price, Last Updated.
    """
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "Product",
                "Size",
                "SKU",
                "Outlet",
                "Stock Qty",
                "Price",
                "Last Updated",
            ]
        )

    work = df.copy()

    # Ensure outlet assignment exists — derive from SIP when absent
    if target_col not in work.columns:
        work = process_order_item_outlets(
            df=work,
            order_col=order_col,
            sip_col=sip_col,
            target_col=target_col,
        )

    if item_col not in work.columns or target_col not in work.columns:
        return pd.DataFrame(
            columns=[
                "Product",
                "Size",
                "SKU",
                "Outlet",
                "Stock Qty",
                "Price",
                "Last Updated",
            ]
        )

    today = bd_today().strftime("%Y-%m-%d")
    records: List[Dict[str, Any]] = []

    for _, r in work.iterrows():
        product = str(r.get(item_col, "")).strip()
        if not product or product.lower() in ("nan", "none"):
            continue

        outlet = str(r.get(target_col, "")).strip()
        if not outlet:
            outlet = "Warehouse"

        # Size: explicit column first, else parse "Product - Size" from name
        size = ""
        if size_col and size_col in work.columns:
            raw_size = r.get(size_col, "")
            if pd.notna(raw_size) and str(raw_size).strip():
                size = str(raw_size).strip()
        if not size:
            parsed_size = get_size_from_name(product)
            size = parsed_size if parsed_size and parsed_size != "N/A" else ""

        # Quantity: numeric parse, default 1 per line
        qty = 1
        if qty_col in work.columns:
            try:
                val = r.get(qty_col)
                if pd.notna(val):
                    if isinstance(val, str):
                        val = val.replace(",", "").strip()
                    if val != "":
                        qty = max(1, int(float(val)))
            except Exception:
                qty = 1

        # SKU: keep raw value; junk becomes '-'
        sku = "—"
        if sku_col and sku_col != "None" and sku_col in work.columns:
            raw_sku = r.get(sku_col, "")
            if pd.notna(raw_sku) and str(raw_sku).strip():
                candidate = str(raw_sku).strip()
                if candidate.lower() not in ("nan", "none", "null", "n/a", "0"):
                    sku = candidate

        # Price: per-unit price if available
        price = ""
        if price_col and price_col in work.columns:
            try:
                val = r.get(price_col)
                if pd.notna(val) and str(val).strip():
                    price = float(str(val).replace(",", "").strip())
            except Exception:
                price = ""

        records.append(
            {
                "Product": product,
                "Size": size if size else "—",
                "SKU": sku,
                "Outlet": outlet,
                "Stock Qty": qty,
                "Price": price,
                "Last Updated": today,
            }
        )

    out = pd.DataFrame(records)
    if out.empty:
        return pd.DataFrame(
            columns=[
                "Product",
                "Size",
                "SKU",
                "Outlet",
                "Stock Qty",
                "Price",
                "Last Updated",
            ]
        )

    # Aggregate required units per Product/Size/SKU/Outlet
    agg = out.groupby(["Product", "Size", "SKU", "Outlet"], as_index=False).agg(
        {"Stock Qty": "sum", "Price": "first", "Last Updated": "first"}
    )
    agg["Stock Qty"] = agg["Stock Qty"].astype(int)
    agg = agg.sort_values(
        ["Product", "Size", "SKU", "Outlet"],
        key=lambda col: col.astype(str).str.lower(),
    ).reset_index(drop=True)

    return agg[
        ["Product", "Size", "SKU", "Outlet", "Stock Qty", "Price", "Last Updated"]
    ]


# ── Current Stock Report (CSV upload) support ─────────────────────────────

STOCK_REPORT_COLUMNS = [
    "Product",
    "Size",
    "SKU",
    "Outlet",
    "Stock Qty",
    "Price",
    "Last Updated",
]


def parse_stock_report(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a Smart Inventory 'Current Stock Report' export.

    Accepts the plugin's CSV/Excel export with columns Product, Size, SKU,
    Outlet, Stock Qty, Price, Last Updated (header naming is tolerant to
    case and aliases like 'Outlet Name' / 'Qty'). Steps:

    1. Strip the 'Size: ' prefix many exports carry ("Size: 3XL" -> "3XL").
    2. Normalize outlet slugs to canonical names ("Mirpur 12" -> "Mirpur").
    3. Deduplicate repeated rows by keeping the latest 'Last Updated' per
       Product/Size/SKU/Outlet — the export re-emits unchanged rows on every
       sync, so naive grouping would double-count stock.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=STOCK_REPORT_COLUMNS)

    work = df.copy()
    work.columns = [str(c).strip() for c in work.columns]

    aliases = {
        "Product Name": "Product",
        "Item Name": "Product",
        "Outlet Name": "Outlet",
        "Outlet Slug": "Outlet",
        "Qty": "Stock Qty",
        "Quantity": "Stock Qty",
        "Stock": "Stock Qty",
        "Updated": "Last Updated",
        "Last Update": "Last Updated",
    }
    work = work.rename(columns={k: v for k, v in aliases.items() if k in work.columns})

    missing = [c for c in ("Product", "Outlet", "Stock Qty") if c not in work.columns]
    if missing:
        raise ValueError(
            "Missing required column(s): " + ", ".join(missing) + ". "
            "Expected the Smart Inventory 'Current Stock Report' layout."
        )

    if "SKU" not in work.columns:
        work["SKU"] = "—"
    if "Size" not in work.columns:
        work["Size"] = ""
    if "Price" not in work.columns:
        work["Price"] = 0.0
    if "Last Updated" not in work.columns:
        work["Last Updated"] = ""

    work["Product"] = work["Product"].fillna("").astype(str).str.strip()
    work["Size"] = (
        work["Size"]
        .fillna("")
        .astype(str)
        .str.replace(r"^\s*size\s*:\s*", "", regex=True, case=False)
        .str.strip()
    )
    # Blank Size cells arrive as NaN or the literal string "nan" depending on
    # the source; normalize both to empty string so dedupe keys stay stable.
    work.loc[work["Size"].str.lower().isin(["nan", "none"]), "Size"] = ""
    work["SKU"] = work["SKU"].fillna("").astype(str).str.strip()
    work["Outlet"] = work["Outlet"].apply(normalize_outlet_name)
    # Quantities may carry unit noise ("3 pcs", "1,250"); extract the numeric
    # core so legitimate values survive and pure junk falls back to 0.
    qty_numeric = (
        work["Stock Qty"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.extract(r"(-?\d+\.?\d*)")[0]
    )
    work["Stock Qty"] = pd.to_numeric(qty_numeric, errors="coerce").fillna(0)
    work["Price"] = pd.to_numeric(
        work["Price"].astype(str).str.replace(r"[^\d.]", "", regex=True),
        errors="coerce",
    ).fillna(0.0)

    # Drop fully-empty rows (no product AND no SKU)
    work = work[
        (work["Product"] != "")
        & (~work["Product"].str.lower().isin(["nan", "none"]))
        & (work["SKU"] != "")
        & (~work["SKU"].str.lower().isin(["nan", "none"]))
    ]
    if work.empty:
        return pd.DataFrame(columns=STOCK_REPORT_COLUMNS)

    parsed_ts = pd.to_datetime(work["Last Updated"], errors="coerce")
    work["Last Updated"] = parsed_ts.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    work["_ts"] = parsed_ts

    # Latest observation wins per (Product, Size, SKU, Outlet)
    sort_keys = ["_ts", "Stock Qty"]
    work = work.sort_values(sort_keys, na_position="first")
    deduped = work.drop_duplicates(
        subset=["Product", "Size", "SKU", "Outlet"], keep="last"
    )

    deduped["Stock Qty"] = deduped["Stock Qty"].astype(int)
    return deduped[STOCK_REPORT_COLUMNS].reset_index(drop=True)


def pivot_stock_report(
    report_df: pd.DataFrame,
    outlet_order: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Pivot a parsed stock report into one row per Product/Size/SKU.

    Each outlet becomes a column (0 where the outlet has no stock recorded).
    Columns are ordered canonically (Warehouse first, then known outlets,
    then extras alphabetically) so the UI always renders a stable layout.
    Every canonical outlet is guaranteed a column even when absent from the
    data, keeping the pivot shape stable across reports.
    """
    if report_df is None or report_df.empty:
        return pd.DataFrame(columns=["Product", "Size", "SKU"])

    work = report_df.copy()
    work["Outlet"] = work["Outlet"].astype(str)

    index_cols = ["Product", "Size", "SKU"]
    pivot = work.pivot_table(
        index=index_cols,
        columns="Outlet",
        values="Stock Qty",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    pivot.columns.name = None

    # Guarantee canonical columns exist even with no rows for them
    default_order = ["Warehouse", "Mirpur", "Wari", "Cumilla", "Sylhet"]
    canonical = outlet_order or default_order
    for candidate in canonical:
        if candidate not in pivot.columns:
            pivot[candidate] = 0

    outlet_cols = [c for c in pivot.columns if c not in index_cols]
    ordered: List[str] = []
    for candidate in canonical:
        for o in outlet_cols:
            if o.lower() == candidate.lower() and o not in ordered:
                ordered.append(o)
    ordered += sorted(o for o in outlet_cols if o not in ordered)

    for col in ordered:
        pivot[col] = pd.to_numeric(pivot[col], errors="coerce").fillna(0).astype(int)
    pivot["Total"] = pivot[ordered].sum(axis=1)

    return pivot[index_cols + ordered + ["Total"]]
