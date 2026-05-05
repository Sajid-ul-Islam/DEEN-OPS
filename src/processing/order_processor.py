import pandas as pd
import streamlit as st
import os
import json
import re
from functools import lru_cache
from src.utils.product import get_category_from_name
from src.utils.text import normalize_city_name, peek_zone_from_address
from fuzzywuzzy import process


def _clean_text_part(value):
    text = str(value or "").replace("\n", " ").strip()
    if not text or text.lower() == "nan":
        return ""
    return " ".join(text.split())


def _title_text_part(value):
    cleaned = _clean_text_part(value)
    return cleaned.title() if cleaned else ""


def _dedupe_address_parts(parts):
    deduped = []
    seen = set()
    for part in parts:
        cleaned = _clean_text_part(part)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        deduped.append(cleaned)
        seen.add(key)
    return deduped


@lru_cache(maxsize=1)
def _load_pathao_map():
    pathao_map_path = "resources/pathao_map.json"
    if not os.path.exists(pathao_map_path):
        return {}

    try:
        with open(pathao_map_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _find_city_for_zone(zone_text, pathao_map):
    zone_name = _title_text_part(zone_text)
    if not zone_name or not pathao_map:
        return "", ""

    best_city = ""
    best_zone = ""
    best_score = 0

    for city_name, city_data in pathao_map.items():
        zones = city_data.get("zones", {})
        if zone_name in zones:
            return city_name, zone_name

        if not zones:
            continue

        zone_match = process.extractOne(zone_name, list(zones.keys()))
        if zone_match and zone_match[1] > best_score:
            best_city = city_name
            best_zone = zone_match[0]
            best_score = zone_match[1]

    if best_score >= 85:
        return best_city, best_zone
    return "", ""


def _coerce_item_qty(value, default=1):
    try:
        qty = int(float(value))
    except (TypeError, ValueError):
        qty = default
    return qty


def _format_item_label(item_name, sku=""):
    clean_name = _clean_text_part(item_name) or "Unknown Item"
    clean_sku = _clean_text_part(sku)
    if clean_sku:
        return f"{clean_name} - {clean_sku}"
    return clean_name


def _normalize_item_records(items):
    aggregated = {}
    for item in items:
        item_name = _clean_text_part(item.get("item_name", ""))
        if not item_name:
            continue

        sku = _clean_text_part(item.get("sku", ""))
        qty = _coerce_item_qty(item.get("qty", 1), default=1)
        if qty <= 0:
            continue

        category = get_category_from_name(item_name) or "Others"
        label = _format_item_label(item_name, sku)
        key = (category, label)
        aggregated[key] = aggregated.get(key, 0) + qty

    normalized = [
        {"category": cat, "label": label, "qty": qty}
        for (cat, label), qty in aggregated.items()
    ]
    normalized.sort(key=lambda item: (item["category"].casefold(), item["label"].casefold()))
    return normalized


def build_item_description(items, suffix_info=""):
    normalized_items = _normalize_item_records(items)
    total_qty = sum(item["qty"] for item in normalized_items)
    if not normalized_items:
        return "General Items"

    if total_qty == 1 and len(normalized_items) == 1:
        full_desc = normalized_items[0]["label"]
        if suffix_info:
            full_desc += f"; {suffix_info.lstrip('- ').strip()}"
        return full_desc

    grouped = {}
    for item in normalized_items:
        grouped.setdefault(item["category"], []).append(item)

    desc_parts = []
    for category in sorted(grouped.keys(), key=str.casefold):
        formatted_items = []
        cat_total = 0
        for item in grouped[category]:
            cat_total += item["qty"]
            if item["qty"] > 1:
                formatted_items.append(f'{item["label"]} ({item["qty"]} pcs)')
            else:
                formatted_items.append(item["label"])
        desc_parts.append(f'{cat_total} {category} = {"; ".join(formatted_items)}')

    full_desc = "; ".join(desc_parts)
    suffix_parts = [f"{int(total_qty)} items"]
    if suffix_info:
        suffix_parts.append(suffix_info)
    return full_desc + f"; ({' - '.join(suffix_parts)})"


def parse_manual_item_lines(raw_text):
    parsed_items = []
    for raw_line in str(raw_text or "").splitlines():
        line = _clean_text_part(raw_line)
        if not line:
            continue

        qty = 1
        payload = line

        prefix_match = re.match(r"^(\d+)\s*[xX]\s+(.+)$", payload)
        suffix_match = re.match(r"^(.+?)\s*[xX]\s*(\d+)$", payload)
        paren_match = re.match(r"^(.+?)\s*\((\d+)\s*(?:pcs?|pieces?)\)$", payload, re.IGNORECASE)

        if prefix_match:
            qty = _coerce_item_qty(prefix_match.group(1), default=1)
            payload = _clean_text_part(prefix_match.group(2))
        elif suffix_match:
            qty = _coerce_item_qty(suffix_match.group(2), default=1)
            payload = _clean_text_part(suffix_match.group(1))
        elif paren_match:
            qty = _coerce_item_qty(paren_match.group(2), default=1)
            payload = _clean_text_part(paren_match.group(1))

        item_name = payload
        sku = ""
        if "|" in payload:
            item_name, sku = [part.strip() for part in payload.split("|", 1)]

        parsed_items.append({"item_name": item_name, "sku": sku, "qty": qty})

    return parsed_items


def normalize_manual_item_input(raw_text):
    parsed_items = parse_manual_item_lines(raw_text)
    normalized_items = _normalize_item_records(parsed_items)
    description = build_item_description(parsed_items)
    return normalized_items, description


def clean_dataframe(df):
    """
    cleans and standardizes the input dataframe columns.
    """
    if df.empty:
        return df

    # Convert numeric columns safely
    numeric_cols = ["Quantity", "Item Cost", "Order Total Amount"]
    for col in numeric_cols:
        if col in df.columns:
            if df[col].dtype == "object":
                # Strip non-numeric characters for currency (e.g. "TK 100")
                df[col] = (
                    df[col].astype(str).str.replace(r"[^\d.]", "", regex=True)
                )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Clean string columns
    string_cols = [
        "Phone (Billing)",
        "Item Name",
        "SKU",
        "First Name (Shipping)",
        "State Name (Billing)",
        "Order Number",
        "Order ID",
    ]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def identify_columns(df):
    """
    Identifies dynamic column names like Address and Transaction ID.
    """
    cols = {}

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
    if "trxId" not in df.columns:
        for c in df.columns:
            if c.lower() == "trxid":
                cols["trx_col"] = c
                break

    # Order Number Column
    cols["order_col"] = "Order Number"
    if "Order Number" not in df.columns:
        for c in df.columns:
            if c.lower() in ["order number", "order id", "id", "order #", "order_id"]:
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

    # Recipient Name Column - Broaden search
    cols["name_col"] = None
    for c in df.columns:
        c_l = c.lower()
        if "name" in c_l:
            # Prefer shipping/full name, but take any name
            if any(k in c_l for k in ["shipping", "full", "customer", "recipient"]):
                cols["name_col"] = c
                break
            if not cols["name_col"]:
                cols["name_col"] = c

    # Recipient ID Fallback
    if not cols["name_col"]:
        for c in df.columns:
            if "id" in c.lower() or "number" in c.lower():
                cols["name_col"] = c
                break

    # Defaults if everything fails
    if not cols["name_col"]: cols["name_col"] = df.columns[0]
    if not cols["state_col"]:
        # Look for any col with 'state' or 'district'
        cols["state_col"] = next((c for c in df.columns if "state" in c.lower() or "district" in c.lower()), df.columns[0])
    if not cols["city_col"]:
        # Look for any col with 'city' or 'area' or 'zone'
        cols["city_col"] = next((c for c in df.columns if "city" in c.lower() or "area" in c.lower() or "zone" in c.lower()), df.columns[0])

    return cols


def process_single_order_group(phone, group, data_cols):
    """
    Processes a group of rows belonging to a single order (phone number).
    """
    order_col = data_cols.get("order_col", "Order Number")

    if order_col in group.columns:
        unique_orders = group.drop_duplicates(subset=[order_col])
    else:
        # Fallback if no order identification column is found
        unique_orders = group.head(1)

    first_row = group.iloc[0]
    total_qty = group["Quantity"].sum()
    order_items = []
    for _, row in group.iterrows():
        order_items.append(
            {
                "item_name": row.get("Item Name", ""),
                "sku": row.get("SKU", ""),
                "qty": row.get("Quantity", 0),
            }
        )

    # --- Amount to Collect & Payment Info (across unique orders) ---
    total_to_collect = 0
    trx_types = set()

    for _, order_row in unique_orders.iterrows():
        order_total = order_row.get("Order Total Amount", 0)
        pay_method = str(order_row.get("Payment Method Title", "")).lower()

        # Determine if this specific order is already paid
        is_paid = any(kw in pay_method for kw in ["pay online", "ssl", "bkash"])

        if is_paid:
            if "bkash" in pay_method:
                trx_types.add("Paid by Bkash")
            else:
                trx_types.add("Paid by SSL")
        else:
            total_to_collect += order_total

    trx_info = " / ".join(sorted(list(trx_types)))

    # Append Transaction IDs
    trx_col = data_cols["trx_col"]
    if trx_col in group.columns:
        trx_vals = set(group[trx_col].dropna().astype(str))
        cleaned_trx = [t for t in trx_vals if t.lower() != "nan" and t.strip() != ""]
        if cleaned_trx:
            trx_str = ", ".join(cleaned_trx)
            if trx_info:
                trx_info += f" - {trx_str}"
            else:
                trx_info = trx_str

    # --- Construct Description String ---
    full_desc = build_item_description(order_items, suffix_info=trx_info)

    # Address Processing
    addr_col = data_cols["addr_col"]
    raw_address = _clean_text_part(first_row.get(addr_col, ""))
    if not raw_address:
        raw_address = _clean_text_part(first_row.get("State Name (Billing)", ""))

    raw_state = _clean_text_part(first_row.get(data_cols["state_col"], ""))
    raw_city_or_zone = _clean_text_part(first_row.get(data_cols["city_col"], ""))
    recipient_city = normalize_city_name(raw_state)
    if recipient_city.lower() in ["nan", "unknown"]:
        recipient_city = ""

    # RecipientZone & Area: Smart Matching from Pathao Database
    recipient_area = ""
    extracted_zone = _title_text_part(raw_city_or_zone)
    inferred_zone = peek_zone_from_address(" ".join([raw_address, raw_city_or_zone]))
    if not extracted_zone:
        extracted_zone = inferred_zone

    # Load Pathao Map for intelligent correction
    pathao_map = _load_pathao_map()
    if pathao_map:
        try:
            if not recipient_city:
                inferred_city, official_zone = _find_city_for_zone(extracted_zone or inferred_zone, pathao_map)
                if inferred_city:
                    recipient_city = inferred_city
                    if official_zone:
                        extracted_zone = official_zone

            # 1. Match City
            city_data = pathao_map.get(recipient_city)
            if not city_data and recipient_city:
                # Try fuzzy matching city name if direct lookup fails
                match = process.extractOne(recipient_city, pathao_map.keys())
                if match and match[1] > 85:
                    recipient_city = match[0]
                    city_data = pathao_map[match[0]]

            if city_data:
                zones_dict = city_data.get("zones", {})
                if extracted_zone and zones_dict:
                    # 2. Match Zone
                    zone_match = process.extractOne(extracted_zone, zones_dict.keys())
                    if zone_match and zone_match[1] > 75:
                        official_zone_name = zone_match[0]
                        extracted_zone = official_zone_name

                        # 3. Match Area (Optional)
                        areas_list = zones_dict[official_zone_name].get("areas", [])
                        if areas_list:
                            # Try to find area name in the Address since it's rarely a separate column in WooCommerce
                            area_names = [a["area_name"] for a in areas_list]
                            area_match = process.extractOne(raw_address or extracted_zone, area_names)
                            if area_match and area_match[1] > 90:
                                recipient_area = area_match[0]
        except:
            pass # Fallback to raw data if map fails to load

    # Combine merchant IDs
    if order_col in unique_orders.columns:
        order_ids = [
            str(x)
            for x in unique_orders[order_col].unique()
            if str(x).lower() != "nan"
        ]
        combined_merchant_id = ", ".join(order_ids)
    else:
        combined_merchant_id = "N/A"

    # --- Final Brute Force Validation for Pathao Mandatory Cells ---
    recipient_name = str(first_row.get(data_cols["name_col"], "")).strip().title()
    if not recipient_name or recipient_name.lower() == "nan":
        recipient_name = "Customer"

    if not recipient_city or recipient_city.lower() in ["unknown", "nan", ""]:
        # Try to find city in address as last resort
        for city_name in ["Dhaka", "Chittagong", "Chattogram", "Sylhet", "Khulna", "Rajshahi", "Barisal", "Rangpur"]:
            if city_name.lower() in raw_address.lower():
                recipient_city = city_name
                break
        if not recipient_city: recipient_city = "Dhaka" # Default to capital

    # If extracted_zone is just the city name again, try to peek into the address
    if not extracted_zone or extracted_zone.lower() in ["unknown", "nan", "", recipient_city.lower(), "dhaka", "chattogram"]:
        peeked = inferred_zone or peek_zone_from_address(
            " ".join([raw_address, raw_city_or_zone, recipient_city])
        )
        if peeked:
            extracted_zone = peeked
        else:
            extracted_zone = recipient_city # Final fallback

    address_parts = _dedupe_address_parts(
        [
            _title_text_part(raw_address),
            recipient_area,
            extracted_zone,
            recipient_city,
        ]
    )
    address_val = ", ".join(address_parts) if address_parts else "Address Missing"

    # --- Build Record ---
    record = {
        "ItemType": "Parcel",
        "StoreName": "Deen Commerce",
        "MerchantOrderId": combined_merchant_id,
        "RecipientName(*)": recipient_name,
        "RecipientPhone(*)": phone if phone and str(phone).lower() != "nan" else "01700000000",
        "RecipientAddress(*)": address_val if address_val else "Address Missing",
        "RecipientCity(*)": recipient_city,
        "RecipientZone(*)": extracted_zone,
        "RecipientArea": recipient_area,
        "AmountToCollect(*)": total_to_collect if total_to_collect > 0 else 0,
        "ItemQuantity": int(total_qty) if total_qty > 0 else 1,
        "ItemWeight": "0.5",
        "ItemDesc": full_desc if full_desc else "General Items",
        "SpecialInstruction": "",
    }
    return record


@st.cache_data(show_spinner="Processing orders via Pathao Intelligence Engine...")
def process_orders_dataframe(df):
    """
    Main Logic: Takes raw DF, returns processed DF
    """
    # 1. Clean
    df = clean_dataframe(df)
    data_cols = identify_columns(df)

    if "Phone (Billing)" not in df.columns:
        raise ValueError("Column 'Phone (Billing)' not found in uploaded file.")

    # 2. Group
    grouped = df.groupby("Phone (Billing)")
    processed_data = []

    # 3. Process Groups
    for phone, group in grouped:
        record = process_single_order_group(phone, group, data_cols)
        processed_data.append(record)

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
    ]

    # Ensure all target columns exist
    for col in target_columns:
        if col not in result_df.columns:
            result_df[col] = ""

    return result_df[target_columns]
