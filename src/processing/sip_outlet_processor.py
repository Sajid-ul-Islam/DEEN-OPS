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
    "mirpur": "Mirpur",
    "cumilla": "Cumilla",
    "comilla": "Cumilla",
    "wari": "Wari",
    "sylhet": "Sylhet",
    "uttara": "Uttara",
    "chittagong": "Chittagong",
}


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
                item_outlets.append(
                    normalize_outlet_name(slug, canonical=canonical)
                )
            else:
                # If more rows than JSON entries, fallback to last known outlet or default
                if parsed_items:
                    last_slug = (
                        parsed_items[-1].get("outlet_slug")
                        or parsed_items[-1].get("outlet_name")
                    )
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
    if df.empty or item_col not in df.columns or qty_col not in df.columns:
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

    # Clean numeric quantity
    filtered_df[qty_col] = pd.to_numeric(
        filtered_df[qty_col].astype(str).str.replace(r"[^\d.-]", "", regex=True),
        errors="coerce",
    ).fillna(1)

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
    if out in ("warehouse", "mirpur", "mirpur-12", "mirpur 12", "ecom", "wh", "default"):
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
) -> pd.DataFrame:
    """Generate Pathao Bulk Upload format from orders with SIP item-wise outlets.

    Handles split-outlet orders by creating multiple consignments:
    - Items from Warehouse and Mirpur are dispatched together with no suffix.
    - Items from Cumilla receive suffix ' c'.
    - Items from Sylhet receive suffix ' s'.
    - Items from Wari receive suffix ' w'.
    - The first dispatch includes the delivery fee (50 inside Dhaka, 90 outside Dhaka).
    - Subsequent dispatches for the same order only include their respective item costs.
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

    actual_order_col = order_col if order_col in processed_df.columns else processed_df.columns[0]
    consignments: List[Dict[str, Any]] = []

    # Detect address and city columns
    name_col = "Full Name (Shipping)" if "Full Name (Shipping)" in processed_df.columns else "Name"
    phone_col = "Phone (Shipping)" if "Phone (Shipping)" in processed_df.columns else "Phone"
    addr_col = "Address 1&2 (Shipping)" if "Address 1&2 (Shipping)" in processed_df.columns else "Address"
    city_col = "City (Shipping)" if "City (Shipping)" in processed_df.columns else "City"
    cost_col = "Item Cost" if "Item Cost" in processed_df.columns else None
    qty_col = "Quantity" if "Quantity" in processed_df.columns else None
    item_col = "Item Name" if "Item Name" in processed_df.columns else processed_df.columns[1]

    for order_id, order_group in processed_df.groupby(actual_order_col, sort=False):
        first_row = order_group.iloc[0]

        recipient_name = str(first_row.get(name_col, "")).strip() if name_col in first_row else ""
        recipient_phone = normalize_phone_number(first_row.get(phone_col, ""))
        address_val = str(first_row.get(addr_col, "")).strip() if addr_col in first_row else ""
        city_val = str(first_row.get(city_col, "")).strip() if city_col in first_row else ""
        if city_val.lower() == "nan":
            city_val = ""

        # Payment & COD check
        payment_method = str(first_row.get("Payment Method Title", "")).lower()
        is_paid = any(kw in payment_method for kw in ["online", "ssl", "bkash", "card", "prepaid", "paid"])

        # Delivery fee calculation
        total_order_amount = pd.to_numeric(first_row.get("Order Total Amount", 0), errors="coerce") or 0
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

            # Build Item Description
            if qty_col and item_col:
                item_desc_list = [
                    f"{r[item_col]} x {r[qty_col]}"
                    for _, r in grp_items.iterrows()
                ]
                item_desc = ", ".join(item_desc_list)
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

