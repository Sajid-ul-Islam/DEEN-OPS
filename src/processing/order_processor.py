import json
import os
import re
from typing import Any, Dict, List, Tuple

import pandas as pd
from src.utils.streamlit_runtime import cache_data
from rapidfuzz import process

from src.config.constants import RESOURCES_DIR
from src.utils.text import normalize_city_name, peek_zone_from_address

# Column aliases for fallback when files use different header names
_COLUMN_ALIASES: Dict[str, List[str]] = {
    "Quantity": [
        "Quantity (- Refund)",
        "Qty",
        "Quantity (Refund)",
        "Item Qty",
        "Quantity(-Refund)",
    ],
    "Item Cost": ["Line Item Price", "Price", "Item Price", "Cost", "Line Total"],
    "Order Total Amount": [
        "Total",
        "Order Total",
        "Total Amount",
        "Grand Total",
        "Order Amount",
    ],
    "Phone (Billing)": [
        "Phone",
        "Billing Phone",
        "Customer Phone",
        "Phone Number",
        "Mobile",
        "Phone (Shipping)",
    ],
    "Full Name (Shipping)": [
        "Full Name",
        "Full Name (Shipping)",
        "Full Name (Billing)",
        "Customer Name",
        "Recipient Name",
        "Billing Name",
        "Name",
        "Customer",
    ],
    "First Name (Shipping)": [
        "Shipping First Name",
        "First Name",
        "First Name (Shipping)",
        "First Name (Billing)",
        "Billing First Name",
    ],
    "Last Name (Shipping)": [
        "Shipping Last Name",
        "Last Name",
        "Last Name (Shipping)",
        "Last Name (Billing)",
        "Billing Last Name",
        "Surname",
    ],
    "Address 1&2 (Shipping)": [
        "Shipping Address",
        "Address (Shipping)",
        "Address",
        "Delivery Address",
    ],
    "City (Shipping)": ["Shipping City", "City"],
    "State Code (Shipping)": ["Shipping State", "State", "State Code"],
}


def normalize_phone(phone_str: str) -> Tuple[str, List[str]]:
    """
    Normalize a phone number to 11-digit BD format (01XXXXXXXXX).
    Returns (normalized_phone, list_of_flags).
    """
    flags: List[str] = []
    raw = str(phone_str).strip()

    # Remove all non-digit characters
    digits = re.sub(r"\D", "", raw)

    # Handle +880 or 880 country code prefix
    if digits.startswith("880") and len(digits) > 10:
        digits = digits[3:]

    # Handle missing leading 0 (10-digit local format)
    if not digits.startswith("0") and len(digits) == 10:
        digits = "0" + digits

    # Take last 11 digits if string is longer (e.g. multiple phones concatenated)
    if len(digits) > 11:
        digits = digits[-11:]

    # Check for masked phone (contains * in original)
    if "*" in raw:
        flags.append("MASKED_PHONE")

    # Validate length
    if len(digits) != 11:
        flags.append(f"INVALID_PHONE_LEN_{len(digits)}")

    # Validate BD mobile format (starts with 01)
    if len(digits) == 11 and not digits.startswith("01"):
        flags.append("INVALID_PHONE_FORMAT")

    return digits, flags


def _apply_column_fallbacks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Maps alternate column names to the canonical names the processor expects.
    Only applies when the canonical column is missing.
    """
    for canonical, aliases in _COLUMN_ALIASES.items():
        if canonical not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    df[canonical] = df[alias].copy()
                    break
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans and standardizes the input dataframe columns.
    Applies column fallbacks for files with alternate header names.
    Accepts recipient name either as Full Name or First Name + Last Name:
    - If Full Name is provided and has values, takes it.
    - If First Name and Last Name are provided, merges them into Full Name (Shipping).
    Adds empty Phone (Billing) if missing.
    """
    if df.empty:
        return df

    # Apply column fallbacks for alternate header names
    df = _apply_column_fallbacks(df)

    # Resolve recipient name: accept full name or first + last
    has_full_name = "Full Name (Shipping)" in df.columns and (
        df["Full Name (Shipping)"]
        .astype(str)
        .str.strip()
        .replace(["nan", "None", ""], pd.NA)
        .notna()
        .any()
    )

    first_col = next(
        (
            c
            for c in [
                "First Name (Shipping)",
                "First Name",
                "Shipping First Name",
                "First Name (Billing)",
            ]
            if c in df.columns
        ),
        None,
    )
    last_col = next(
        (
            c
            for c in [
                "Last Name (Shipping)",
                "Last Name",
                "Shipping Last Name",
                "Last Name (Billing)",
            ]
            if c in df.columns
        ),
        None,
    )

    if first_col or last_col:
        first_series = (
            df[first_col]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace(["nan", "None"], "")
            if first_col
            else pd.Series("", index=df.index)
        )
        last_series = (
            df[last_col].fillna("").astype(str).str.strip().replace(["nan", "None"], "")
            if last_col
            else pd.Series("", index=df.index)
        )
        merged_series = (first_series + " " + last_series).str.strip()
    else:
        merged_series = pd.Series("", index=df.index)

    if has_full_name:
        # Full name exists: take it, and fill any blank row from merged first+last if available
        full_series = (
            df["Full Name (Shipping)"]
            .astype(str)
            .str.strip()
            .replace(["nan", "None", ""], pd.NA)
        )
        if (first_col or last_col) and merged_series.ne("").any():
            df["Full Name (Shipping)"] = full_series.fillna(merged_series)
        else:
            df["Full Name (Shipping)"] = full_series.fillna("")
    else:
        # No full name: take merged first + last
        df["Full Name (Shipping)"] = merged_series

    # Ensure First Name (Shipping) exists for compatibility with components expecting it
    if (
        "First Name (Shipping)" not in df.columns
        or df["First Name (Shipping)"].isna().all()
    ):
        df["First Name (Shipping)"] = df["Full Name (Shipping)"]

    # Add empty Phone (Billing) if missing
    if "Phone (Billing)" not in df.columns:
        df["Phone (Billing)"] = ""

    # Normalize phone numbers to last 11 digits
    df["Phone (Billing)"] = df["Phone (Billing)"].apply(
        lambda x: normalize_phone(str(x))[0] if pd.notna(x) else ""
    )

    # Convert numeric columns safely
    numeric_cols = ["Quantity", "Item Cost", "Order Total Amount"]
    for col in numeric_cols:
        if col in df.columns:
            if df[col].dtype == "object":
                # Strip non-numeric characters for currency (e.g. "TK 100")
                df[col] = df[col].astype(str).str.replace(r"[^\d.]", "", regex=True)
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Clean string columns
    string_cols = [
        "Phone (Billing)",
        "Item Name",
        "SKU",
        "Full Name (Shipping)",
        "First Name (Shipping)",
        "Last Name (Shipping)",
        "State Name (Billing)",
        "Order Number",
        "Order ID",
    ]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Ensure Order ID and Order Number equivalence if one is missing or empty
    if "Order Number" in df.columns and "Order ID" not in df.columns:
        df["Order ID"] = df["Order Number"]
    elif "Order ID" in df.columns and "Order Number" not in df.columns:
        df["Order Number"] = df["Order ID"]
    elif "Order Number" in df.columns and "Order ID" in df.columns:
        num_has = (
            df["Order Number"].notna()
            & df["Order Number"].astype(str).str.strip().ne("")
        ).any()
        id_has = (
            df["Order ID"].notna() & df["Order ID"].astype(str).str.strip().ne("")
        ).any()
        if num_has and not id_has:
            df["Order ID"] = df["Order Number"]
        elif id_has and not num_has:
            df["Order Number"] = df["Order ID"]

    return df


def identify_columns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Identifies dynamic column names like Address and Transaction ID.
    """
    cols: Dict[str, Any] = {}

    # Address Column
    cols["addr_col"] = "Address_Fallback"
    for col in df.columns:
        if "address" in col.lower() and "shipping" in col.lower():
            cols["addr_col"] = col
            break
    if cols["addr_col"] == "Address_Fallback":
        df["Address_Fallback"] = ""

    # Transaction ID Column
    cols["trx_col"] = "trxId"
    for c in df.columns:
        c_lower = c.lower()
        if c_lower in ["trxid", "transaction id", "transaction", "trx id", "bkash"]:
            cols["trx_col"] = c
            break

    # Order Number Column (Order ID and Order Number are interchangeable)
    cols["order_col"] = "Order Number"
    if (
        "Order Number" in df.columns
        and (
            df["Order Number"].notna()
            & df["Order Number"].astype(str).str.strip().ne("")
        ).any()
    ):
        cols["order_col"] = "Order Number"
    elif (
        "Order ID" in df.columns
        and (
            df["Order ID"].notna() & df["Order ID"].astype(str).str.strip().ne("")
        ).any()
    ):
        cols["order_col"] = "Order ID"
    else:
        for c in df.columns:
            if c.lower() in [
                "order number",
                "order id",
                "id",
                "order #",
                "order_id",
                "order_number",
                "order no",
                "order no.",
                "invoice no",
                "invoice #",
                "invoice number",
                "merchantorderid",
            ]:
                cols["order_col"] = c
                break

    # RecipientCity Column (District/State/County)
    cols["state_col"] = None
    for c in df.columns:
        c_l = c.lower()
        if ("state" in c_l) or ("district" in c_l) or ("county" in c_l):
            cols["state_col"] = c
            break

    # RecipientZone Column (City/Thana/Area)
    cols["city_col"] = None
    for c in df.columns:
        c_l = c.lower()
        if ("city" in c_l) or ("zone" in c_l) or ("area" in c_l):
            cols["city_col"] = c
            break

    # Robust Fallback: If one is missing, use the other
    if not cols["state_col"] and cols["city_col"]:
        cols["state_col"] = cols["city_col"]
    if not cols["city_col"] and cols["state_col"]:
        cols["city_col"] = cols["state_col"]

    # Recipient Name Column - Prioritize Full Name first
    cols["name_col"] = None
    if (
        "Full Name (Shipping)" in df.columns
        and df["Full Name (Shipping)"]
        .astype(str)
        .str.strip()
        .replace(["nan", "None", ""], pd.NA)
        .notna()
        .any()
    ):
        cols["name_col"] = "Full Name (Shipping)"
    elif (
        "Full Name" in df.columns
        and df["Full Name"]
        .astype(str)
        .str.strip()
        .replace(["nan", "None", ""], pd.NA)
        .notna()
        .any()
    ):
        cols["name_col"] = "Full Name"
    else:
        for c in df.columns:
            c_l = c.lower()
            if "name" in c_l:
                # Prefer Full Name first, then shipping/first/last
                if "full" in c_l:
                    cols["name_col"] = c
                    break
                if any(k in c_l for k in ["shipping", "customer", "recipient"]):
                    if (
                        not cols["name_col"]
                        or "first" in cols["name_col"].lower()
                        or "last" in cols["name_col"].lower()
                    ):
                        cols["name_col"] = c
                        if "first" not in c_l and "last" not in c_l:
                            break
                if not cols["name_col"]:
                    cols["name_col"] = c

    # If name_col is still first/last only, prefer full name
    if cols["name_col"] and (
        "first" in cols["name_col"].lower() or "last" in cols["name_col"].lower()
    ):
        for c in df.columns:
            if "full name" in c.lower():
                cols["name_col"] = c
                break

    # Recipient ID Fallback
    if not cols["name_col"]:
        for c in df.columns:
            if "id" in c.lower() or "number" in c.lower():
                cols["name_col"] = c
                break

    # Defaults if everything fails
    if not cols["name_col"]:
        cols["name_col"] = df.columns[0]
    if not cols["state_col"]:
        # Look for any col with 'state' or 'district'
        cols["state_col"] = next(
            (c for c in df.columns if "state" in c.lower() or "district" in c.lower()),
            df.columns[0],
        )
    if not cols["city_col"]:
        # Look for any col with 'city' or 'area' or 'zone'
        cols["city_col"] = next(
            (
                c
                for c in df.columns
                if "city" in c.lower() or "area" in c.lower() or "zone" in c.lower()
            ),
            df.columns[0],
        )

    return cols


def get_short_sub_category(item_name: str) -> str:
    """Extracts a shortened sub-category name for Pathao ItemDesc formatting."""
    name_lower = str(item_name).lower()

    if "tank top" in name_lower or "tanktop" in name_lower or "tank-top" in name_lower:
        return "TankTop"
    if "jeans" in name_lower:
        return "Jeans"
    if "denim" in name_lower:
        return "Denim"
    if "flannel" in name_lower:
        return "Flannel"
    if "drop shoulder" in name_lower or "oversized" in name_lower:
        return "Drop Shoulder"
    if (
        "active wear" in name_lower
        or "activewear" in name_lower
        or "sports" in name_lower
        or "jersey" in name_lower
    ):
        return "Active Wear"

    # T-Shirt categorization: check t-shirt explicitly before generic sleeve keywords
    is_tshirt = (
        "t-shirt" in name_lower
        or "tshirt" in name_lower
        or "tee" in name_lower
        or "t shirt" in name_lower
    )
    if is_tshirt:
        if (
            "full sleeve" in name_lower
            or "fs" in name_lower
            or "long sleeve" in name_lower
        ):
            return "FS T-Shirt"
        return "HS T-Shirt"

    if "sweatshirt" in name_lower:
        return "Sweatshirt"
    if "sweater" in name_lower:
        return "Sweater"
    if "hoodie" in name_lower:
        return "Hoodie"
    if "jacket" in name_lower:
        return "Jacket"
    if "polo" in name_lower:
        return "Polo"
    if "panjabi" in name_lower or "punjabi" in name_lower:
        return "Panjabi"
    if "pajama" in name_lower or "payjama" in name_lower:
        return "Pajama"
    if "oxford" in name_lower:
        return "Oxford"
    if "cuban" in name_lower:
        return "Cuban"
    if "linen" in name_lower:
        return "Linen"
    if "corduroy" in name_lower:
        return "Corduroy"
    if "chino" in name_lower:
        return "Chino"
    if "twill" in name_lower:
        return "Twill"
    if "cargo" in name_lower:
        return "Cargo"
    if "jogger" in name_lower:
        return "Jogger"
    if "trouser" in name_lower:
        return "Trouser"
    if "executive" in name_lower or "formal" in name_lower:
        return "Formal"

    # Casual Shirt: Don't show generic 'Shirt =', show 'Casual ='
    if "casual" in name_lower:
        return "Casual"

    # Full Sleeve Shirt (non-casual) -> FS Shirt
    if (
        "full sleeve shirt" in name_lower
        or "fs shirt" in name_lower
        or ("full sleeve" in name_lower and "shirt" in name_lower)
        or (name_lower.startswith("fs ") and "shirt" in name_lower)
    ):
        return "FS Shirt"

    # Half Sleeve Shirt (non-casual) -> HS Shirt
    if (
        "half sleeve shirt" in name_lower
        or "hs shirt" in name_lower
        or ("half sleeve" in name_lower and "shirt" in name_lower)
        or (name_lower.startswith("hs ") and "shirt" in name_lower)
    ):
        return "HS Shirt"

    if "shirt" in name_lower:
        return "Shirt"
    if "wallet" in name_lower:
        return "Wallet"

    if "belt" in name_lower:
        return "Belt"
    if "kaftan" in name_lower:
        return "Kaftan"
    if "boxer" in name_lower:
        return "Boxer"
    if "mask" in name_lower:
        return "Mask"
    if "turtleneck" in name_lower or "turtle neck" in name_lower:
        return "Turtleneck"

    parts = str(item_name).split(" - ")
    return parts[0].strip()


def build_item_description(
    cat_map: Dict[str, Dict[str, int]], total_qty: int, trx_info: str = ""
) -> str:
    """
    Builds the ItemDesc string for Pathao from a category map.
    """
    full_desc = ""

    if int(total_qty) == 1:
        # Single Item
        for _cat, items in cat_map.items():
            for item_str, _count in items.items():
                full_desc = str(item_str).strip().rstrip(";")
                break
            if full_desc:
                break

        if trx_info:
            single_trx_info = trx_info
            if single_trx_info.startswith(" - "):
                single_trx_info = single_trx_info[3:].strip()
            elif single_trx_info.startswith("- "):
                single_trx_info = single_trx_info[2:].strip()

            full_desc += f"; {single_trx_info}"
    else:
        # Multi Item
        desc_parts = []
        for cat, items_dict in cat_map.items():
            formatted_items = []
            cat_total = 0
            for item_str, count in items_dict.items():
                cat_total += count
                clean_item = str(item_str).strip().rstrip(";")
                if count > 1:
                    formatted_items.append(f"{clean_item} ({count} pcs)")
                else:
                    formatted_items.append(clean_item)

            items_joined = "; ".join(filter(None, formatted_items))
            desc_parts.append(f"{cat_total} {cat} = {items_joined}")

        full_desc = "; ".join(filter(None, desc_parts))

        suffix_parts = [f"{int(total_qty)} items"]
        if trx_info:
            suffix_parts.append(trx_info)

        full_desc += f"; ({' - '.join(suffix_parts)})"

    # Clean up any accidental double semicolons
    full_desc = re.sub(r"(\s*;\s*)+", "; ", full_desc).strip()

    return full_desc


def parse_manual_item_lines(raw_text: str) -> Tuple[Dict[str, Dict[str, int]], int]:
    """
    Parses a raw text block of manual items into a category map and total quantity.
    """
    lines = [line.strip() for line in str(raw_text).splitlines() if line.strip()]
    cat_map = {}
    total_qty = 0

    for raw_line in lines:
        line_clean = raw_line.strip().rstrip(";")
        if not line_clean:
            continue

        qty = 1
        item_str = line_clean

        m1 = re.match(r"^(\d+)\s*[xX]\s*(.+)", item_str)
        if m1:
            qty = int(m1.group(1))
            item_str = m1.group(2)
        else:
            m2 = re.search(r"(.+?)\s*[xX]\s*(\d+)$", item_str)
            if m2:
                item_str = m2.group(1)
                qty = int(m2.group(2))
            else:
                m3 = re.search(
                    r"(.+?)\s*\(\s*(\d+)\s*pcs?\s*\)$", item_str, re.IGNORECASE
                )
                if m3:
                    item_str = m3.group(1)
                    qty = int(m3.group(2))

        item_str = item_str.strip().rstrip(";")
        item_str = item_str.replace(" | ", " - ")

        category = get_short_sub_category(item_str)

        if category not in cat_map:
            cat_map[category] = {}
        if item_str not in cat_map[category]:
            cat_map[category][item_str] = 0

        cat_map[category][item_str] += qty
        total_qty += qty

    return cat_map, total_qty


def normalize_manual_item_input(raw_text: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Returns normalized items (list of dicts) and the formatted description string.
    """
    cat_map, total_qty = parse_manual_item_lines(raw_text)

    normalized_items = []
    ordered_cat_map = {}
    for cat, items in sorted(cat_map.items(), key=lambda entry: entry[0]):
        ordered_items = dict(sorted(items.items(), key=lambda entry: entry[0]))
        ordered_cat_map[cat] = ordered_items
        for item, q in ordered_items.items():
            normalized_items.append({"category": cat, "label": item, "qty": q})

    full_desc = build_item_description(ordered_cat_map, total_qty)
    return normalized_items, full_desc


def _get_dispatch_warehouse(dispatch_loc: str) -> str:
    """
    Map a dispatch location string to a warehouse/outlet label.
    Uses the same routing logic as _get_dispatch_group but returns
    a canonical warehouse name for the new WarehouseOutlet column.
    """
    loc_lower = str(dispatch_loc).lower()
    if "cumilla" in loc_lower:
        return "Cumilla Outlet"
    if "wari" in loc_lower:
        return "Wari Outlet"
    if "sylhet" in loc_lower:
        return "Sylhet Outlet"
    if "mirpur" in loc_lower or "ecom" in loc_lower:
        return "Ecom Mirpur"
    return "Ecom-Mirpur"


def _get_dispatch_group(row: pd.Series, order_col: str) -> str:
    """Determine the dispatch location for a given row."""
    sugg = str(row.get("Dispatch Suggestion", "")).strip()
    if sugg and sugg.lower() != "nan" and sugg != "Multiple / Split":
        return sugg
    val = str(row.get(order_col, "")).lower()
    if val.endswith(" c"):
        return "Cumilla"
    if val.endswith(" w"):
        return "Wari"
    if val.endswith(" s"):
        return "Sylhet"
    return "Ecom-Mirpur"


def _extract_payment_info(
    group: pd.DataFrame, order_col: str, trx_col: str
) -> Tuple[float, str]:
    """Extract total_to_collect, trx_types, and trx_info from an order group."""
    total_to_collect = 0
    trx_types = set()

    if order_col in group.columns:
        unique_orders = group.drop_duplicates(subset=[order_col])
    else:
        unique_orders = group.head(1)

    for _, order_row in unique_orders.iterrows():
        order_total = order_row.get("Order Total Amount", 0)
        pay_method = str(order_row.get("Payment Method Title", "")).lower()

        is_paid = any(
            kw in pay_method
            for kw in [
                "pay online",
                "ssl",
                "bkash",
                "card",
                "nagad",
                "rocket",
                "portpos",
                "paid",
            ]
        )

        if is_paid:
            if "pay online" in pay_method or "ssl" in pay_method:
                trx_types.add("Paid by SSL")
            elif "bkash" in pay_method:
                trx_types.add("Paid by Bkash")
            else:
                trx_types.add("Paid by SSL")
        else:
            total_to_collect += (
                float(order_total)
                if pd.notna(order_total) and str(order_total).strip()
                else 0
            )

    trx_info = " / ".join(sorted(list(trx_types)))

    if trx_col in group.columns and "Paid by Bkash" in trx_types:
        trx_vals = set(group[trx_col].dropna().astype(str))
        cleaned_trx = [t for t in trx_vals if t.lower() != "nan" and t.strip() != ""]
        if cleaned_trx:
            trx_str = ", ".join(cleaned_trx)
            trx_info = f"{trx_info} - {trx_str}" if trx_info else trx_str

    return total_to_collect, trx_info


def _build_parcel_category_map(
    df_sub: pd.DataFrame,
) -> Tuple[Dict[str, Dict[str, int]], float]:
    """Build category map and calculate base value for a parcel subgroup."""
    cat_map = {}
    base_val = 0
    for _, row in df_sub.iterrows():
        item_name = str(row.get("Item Name", "")).strip()
        sku = row.get("SKU", "")

        category = get_short_sub_category(item_name)

        clean_sku = str(sku).strip()
        item_str = (
            f"{item_name} - {clean_sku}"
            if clean_sku and clean_sku.lower() != "nan"
            else item_name
        )

        qty = int(float(row.get("Quantity", 0))) if pd.notna(row.get("Quantity")) else 0
        cost = (
            float(row.get("Item Cost", 0))
            if pd.notna(row.get("Item Cost")) and str(row.get("Item Cost")).strip()
            else 0
        )

        if category not in cat_map:
            cat_map[category] = {}
        if item_str not in cat_map[category]:
            cat_map[category][item_str] = 0
        cat_map[category][item_str] += qty
        base_val += cost * qty

    return cat_map, base_val


def _resolve_address(
    first_row: pd.Series, data_cols: Dict[str, Any]
) -> Tuple[str, str, str]:
    """Resolve recipient address components from row data."""
    addr_col = data_cols["addr_col"]
    raw_address = str(first_row.get(addr_col, "")).strip()
    raw_state = str(first_row.get(data_cols["state_col"], "")).strip()
    raw_city = str(first_row.get(data_cols["city_col"], "")).strip()

    recipient_city = normalize_city_name(raw_state)

    address_parts = []
    if raw_address and raw_address.lower() != "nan":
        address_parts.append(raw_address)
    if (
        raw_city
        and raw_city.lower() != "nan"
        and raw_city.lower() not in raw_address.lower()
    ):
        address_parts.append(raw_city)
    if (
        recipient_city
        and recipient_city.lower() != "nan"
        and recipient_city.lower() not in raw_address.lower()
        and recipient_city.lower() not in raw_city.lower()
    ):
        address_parts.append(recipient_city)

    combined_address = ", ".join(address_parts)
    if not combined_address:
        combined_address = str(first_row.get("State Name (Billing)", "")).strip()

    address_val = " ".join(combined_address.split()).title()

    extracted_zone = raw_city.title()
    if extracted_zone.lower() == "nan":
        extracted_zone = ""

    return address_val, recipient_city, extracted_zone


def _lookup_pathao_geocoding(
    recipient_city: str, extracted_zone: str, address_val: str
) -> Tuple[str, str, str]:
    """Use Pathao map data to correct city, zone, and area."""
    recipient_area = ""
    pathao_map_path = os.path.join(RESOURCES_DIR, "pathao_map.json")
    if not os.path.exists(pathao_map_path):
        return recipient_city, extracted_zone, recipient_area

    try:
        with open(pathao_map_path, "r") as f:
            pathao_map = json.load(f)

        city_data = pathao_map.get(recipient_city)
        if not city_data:
            match = process.extractOne(recipient_city, pathao_map.keys())
            if match and match[1] > 85:
                city_data = pathao_map[match[0]]

        if city_data:
            zones_dict = city_data.get("zones", {})
            if extracted_zone and zones_dict:
                zone_match = process.extractOne(extracted_zone, zones_dict.keys())
                if zone_match and zone_match[1] > 75:
                    official_zone_name = zone_match[0]
                    extracted_zone = official_zone_name

                    areas_list = zones_dict[official_zone_name].get("areas", [])
                    if areas_list:
                        area_names = [a["area_name"] for a in areas_list]
                        area_match = process.extractOne(address_val, area_names)
                        if area_match and area_match[1] > 90:
                            recipient_area = area_match[0]
    except Exception:
        pass

    return recipient_city, extracted_zone, recipient_area


def _build_combined_merchant_id(df_sub: pd.DataFrame, order_col: str) -> str:
    """Combine merchant order IDs with dispatch suffixes."""
    if order_col not in df_sub.columns:
        return "N/A"

    order_ids = []
    for _, r in df_sub.iterrows():
        val = str(r[order_col])
        if val.lower() == "nan":
            continue
        if val.endswith(".0"):
            val = val[:-2]

        sugg = str(r.get("Dispatch Suggestion", "")).strip()
        suffix = ""
        if sugg == "Cumilla":
            suffix = " c"
        elif sugg == "Wari":
            suffix = " w"
        elif sugg == "Sylhet":
            suffix = " s"

        if suffix and not val.endswith(suffix):
            val += suffix

        if val not in order_ids:
            order_ids.append(val)

    return ", ".join(order_ids)


def _validate_city_zone(
    recipient_city: str, extracted_zone: str, address_val: str
) -> Tuple[str, str]:
    """Final brute-force validation for city and zone."""
    if not recipient_city or recipient_city.lower() in ["unknown", "nan", ""]:
        for city_name in [
            "Dhaka",
            "Chittagong",
            "Chattogram",
            "Sylhet",
            "Khulna",
            "Rajshahi",
            "Barisal",
            "Rangpur",
        ]:
            if city_name.lower() in address_val.lower():
                recipient_city = city_name
                break
        if not recipient_city:
            recipient_city = "Dhaka"

    if not extracted_zone or extracted_zone.lower() in [
        "unknown",
        "nan",
        "",
        recipient_city.lower(),
        "dhaka",
        "chattogram",
    ]:
        peeked = peek_zone_from_address(address_val)
        extracted_zone = peeked if peeked else recipient_city

    return recipient_city, extracted_zone


def _distribute_amount_to_collect(
    total_to_collect: float,
    total_base: float,
    parcel_records: List[Dict[str, Any]],
    parcel_base_values: List[float],
    recipient_city: str,
) -> None:
    """Distribute the total amount to collect across parcels with partial order detection."""
    if total_to_collect == 0 and total_base > 0:
        city_lower = str(recipient_city).lower()
        delivery_fee = (
            60
            if any(d in city_lower for d in ["dhaka", "savar", "keraniganj"])
            else 120
        )
        total_to_collect = total_base + delivery_fee

    if total_to_collect <= 0:
        return

    diff = total_to_collect - total_base

    if diff > 250:
        city_lower = str(recipient_city).lower()
        delivery_fee = (
            60
            if any(d in city_lower for d in ["dhaka", "savar", "keraniganj"])
            else 120
        )
        total_to_collect = total_base + delivery_fee

        for rec in parcel_records:
            tag = "⚠️ PARTIAL ORDER"
            rec["SpecialInstruction"] = (
                f"{rec['SpecialInstruction']} | {tag}"
                if rec["SpecialInstruction"]
                else tag
            )

    if len(parcel_records) == 1:
        parcel_records[0]["AmountToCollect(*)"] = int(total_to_collect)
    else:
        max_idx = parcel_base_values.index(max(parcel_base_values))
        sum_others = sum(v for i, v in enumerate(parcel_base_values) if i != max_idx)
        for i, rec in enumerate(parcel_records):
            rec["AmountToCollect(*)"] = int(
                max(0, total_to_collect - sum_others)
                if i == max_idx
                else parcel_base_values[i]
            )


def process_single_order_group(
    phone: str,
    group: pd.DataFrame,
    data_cols: Dict[str, Any],
    phone_flags: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Processes a group of rows belonging to a single order (phone number).
    Splits into multiple parcels if items have different dispatch locations,
    assigning the delivery fee to the parcel with the highest item value.
    Returns a list of dictionaries (records).
    """
    order_col = data_cols.get("order_col", "Order Number")
    trx_col = data_cols["trx_col"]
    group = group.copy()

    group["_dispatch_loc"] = group.apply(
        lambda r: _get_dispatch_group(r, order_col), axis=1
    )
    subgroups = [df_sub for _, df_sub in group.groupby("_dispatch_loc")]

    total_to_collect, trx_info = _extract_payment_info(group, order_col, trx_col)

    # Detect missing city on any row in the group
    group_flags: List[str] = list(phone_flags or [])
    for _, row in group.iterrows():
        raw_city = str(row.get(data_cols["city_col"], "")).strip()
        raw_state = str(row.get(data_cols["state_col"], "")).strip()
        if (not raw_city or raw_city.lower() == "nan") and (
            not raw_state or raw_state.lower() == "nan"
        ):
            if "MISSING_CITY_STATE" not in group_flags:
                group_flags.append("MISSING_CITY_STATE")

    parcel_records = []
    parcel_base_values = []

    for df_sub in subgroups:
        first_row = df_sub.iloc[0]
        from src.utils.product import is_bundle_or_combo

        physical_items = df_sub[
            ~df_sub.apply(
                lambda r: is_bundle_or_combo(r.get("Item Name", ""), r.get("SKU", "")),
                axis=1,
            )
        ]
        total_qty = (
            physical_items["Quantity"].sum()
            if not physical_items.empty
            else df_sub["Quantity"].sum()
        )

        cat_map, base_val = _build_parcel_category_map(df_sub)
        full_desc = build_item_description(cat_map, total_qty, trx_info)

        address_val, recipient_city, extracted_zone = _resolve_address(
            first_row, data_cols
        )
        recipient_city, extracted_zone, recipient_area = _lookup_pathao_geocoding(
            recipient_city, extracted_zone, address_val
        )

        combined_merchant_id = _build_combined_merchant_id(df_sub, order_col)

        recipient_name = str(first_row.get(data_cols["name_col"], "")).strip().title()
        if not recipient_name or recipient_name.lower() in (
            "nan",
            "none",
            "customer",
            "",
        ):
            full_val = str(first_row.get("Full Name (Shipping)", "")).strip().title()
            if full_val and full_val.lower() not in ("nan", "none", ""):
                recipient_name = full_val
            else:
                recipient_name = "Customer"

        recipient_city, extracted_zone = _validate_city_zone(
            recipient_city, extracted_zone, address_val
        )

        # Determine dispatch location for this subgroup
        dispatch_loc = _get_dispatch_group(df_sub.iloc[0], order_col)
        warehouse_outlet = _get_dispatch_warehouse(dispatch_loc)

        special_instruction = (
            "⚠️ SPLIT PARCEL - This is part of a multi-parcel order."
            if len(subgroups) > 1
            else ""
        )
        if trx_info:
            special_instruction = (
                f"{special_instruction} | {trx_info}"
                if special_instruction
                else trx_info
            )

        # Append issue flags to SpecialInstruction
        if group_flags:
            flag_str = " | ".join(group_flags)
            special_instruction = (
                f"{special_instruction} | {flag_str}"
                if special_instruction
                else flag_str
            )

        record = {
            "ItemType": "Parcel",
            "StoreName": "Deen Commerce",
            "MerchantOrderId": combined_merchant_id,
            "RecipientName(*)": recipient_name,
            "RecipientPhone(*)": (
                phone if phone and str(phone).lower() != "nan" else "01700000000"
            ),
            "RecipientAddress(*)": address_val if address_val else "Address Missing",
            "RecipientCity(*)": recipient_city,
            "RecipientZone(*)": extracted_zone,
            "RecipientArea": recipient_area,
            "AmountToCollect(*)": 0,
            "ItemQuantity": int(total_qty) if total_qty > 0 else 1,
            "ItemWeight": "0.5",
            "ItemDesc": full_desc if full_desc else "General Items",
            "SpecialInstruction": special_instruction,
            "WarehouseOutlet": warehouse_outlet,
        }

        parcel_records.append(record)
        parcel_base_values.append(base_val)

    total_base = sum(parcel_base_values)
    _distribute_amount_to_collect(
        total_to_collect, total_base, parcel_records, parcel_base_values, recipient_city
    )

    return parcel_records


@cache_data(show_spinner="Processing orders via Pathao Intelligence Engine...")
def process_orders_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main Logic: Takes raw DF, returns processed DF.
    Normalizes phone numbers to last 11 digits and groups by normalized phone
    so that masked +880, 880-prefixed, and 10-digit numbers from the same
    person merge into one order.
    """
    # 1. Clean
    df = clean_dataframe(df)
    data_cols = identify_columns(df)

    if "Phone (Billing)" not in df.columns:
        raise ValueError("Column 'Phone (Billing)' not found in uploaded file.")

    # 2. Normalize phones and group
    #    Apply normalize_phone to every row; store normalized + flags on the df
    phone_info = df["Phone (Billing)"].apply(normalize_phone)
    df["_norm_phone"] = phone_info.apply(lambda x: x[0])
    df["_phone_flags"] = phone_info.apply(lambda x: x[1])

    grouped = df.groupby("_norm_phone")
    processed_data = []

    # 3. Process Groups
    for phone, group in grouped:
        # Aggregate flags across all rows in the group
        all_flags: List[str] = []
        for flag_list in group["_phone_flags"]:
            for f in flag_list:
                if f not in all_flags:
                    all_flags.append(f)
        records = process_single_order_group(
            phone, group, data_cols, phone_flags=all_flags
        )
        processed_data.extend(records)

    # 4. Result DF
    result_df = pd.DataFrame(processed_data)

    target_columns = [
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

    # Ensure all target columns exist
    for col in target_columns:
        if col not in result_df.columns:
            result_df[col] = ""

    return result_df[target_columns]
