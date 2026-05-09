import pandas as pd
import streamlit as st
import os
import json
import re
from src.utils.product import get_category_from_name
from src.utils.text import normalize_city_name, peek_zone_from_address
from fuzzywuzzy import process


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


def build_item_description(cat_map, total_qty, trx_info=""):
    """
    Builds the ItemDesc string for Pathao from a category map.
    """
    full_desc = ""

    if int(total_qty) == 1:
        # Single Item
        for cat, items in cat_map.items():
            for item_str, count in items.items():
                full_desc = item_str
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
                if count > 1:
                    formatted_items.append(f"{item_str} ({count} pcs)")
                else:
                    formatted_items.append(item_str)

            items_joined = "; ".join(formatted_items)
            desc_parts.append(f"{cat_total} {cat} = {items_joined}")

        full_desc = "; ".join(desc_parts)

        suffix_parts = [f"{int(total_qty)} items"]
        if trx_info:
            suffix_parts.append(trx_info)

        full_desc += f"; ({' - '.join(suffix_parts)})"
        
    return full_desc


def parse_manual_item_lines(raw_text):
    """
    Parses a raw text block of manual items into a category map and total quantity.
    """
    lines = [line.strip() for line in str(raw_text).splitlines() if line.strip()]
    cat_map = {}
    total_qty = 0
    
    for line in lines:
        qty = 1
        item_str = line
        
        m1 = re.match(r'^(\d+)\s*[xX]\s*(.+)', item_str)
        if m1:
            qty = int(m1.group(1))
            item_str = m1.group(2)
        else:
            m2 = re.search(r'(.+?)\s*[xX]\s*(\d+)$', item_str)
            if m2:
                item_str = m2.group(1)
                qty = int(m2.group(2))
            else:
                m3 = re.search(r'(.+?)\s*\(\s*(\d+)\s*pcs?\s*\)$', item_str, re.IGNORECASE)
                if m3:
                    item_str = m3.group(1)
                    qty = int(m3.group(2))
                    
        item_str = item_str.strip()
        item_str = item_str.replace(" | ", " - ")
        category = get_category_from_name(item_str)
        
        if category not in cat_map:
            cat_map[category] = {}
        if item_str not in cat_map[category]:
            cat_map[category][item_str] = 0
            
        cat_map[category][item_str] += qty
        total_qty += qty
        
    return cat_map, total_qty


def normalize_manual_item_input(raw_text):
    """
    Returns normalized items (list of dicts) and the formatted description string.
    """
    cat_map, total_qty = parse_manual_item_lines(raw_text)
    
    normalized_items = []
    for cat, items in cat_map.items():
        for item, q in items.items():
            normalized_items.append({
                "category": cat,
                "label": item,
                "qty": q
            })
            
    full_desc = build_item_description(cat_map, total_qty)
    return normalized_items, full_desc


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

    # --- Categorize Items (across all rows in group) ---
    cat_map = {}
    for _, row in group.iterrows():
        item_name = row.get("Item Name", "")
        sku = row.get("SKU", "")
        category = get_category_from_name(item_name)

        # Format: "Item Name - SKU"
        item_str = f"{item_name} - {sku}"
        qty = int(row.get("Quantity", 0))

        if category not in cat_map:
            cat_map[category] = {}
        if item_str not in cat_map[category]:
            cat_map[category][item_str] = 0
        cat_map[category][item_str] += qty

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
    full_desc = build_item_description(cat_map, total_qty, trx_info)

    # Address Processing
    addr_col = data_cols["addr_col"]
    raw_address = str(first_row.get(addr_col, "")).strip()
    raw_state = str(first_row.get(data_cols["state_col"], "")).strip()
    raw_city = str(first_row.get(data_cols["city_col"], "")).strip()

    # Combine Address, City, and State into the main address field
    address_parts = []
    if raw_address and raw_address.lower() != "nan":
        address_parts.append(raw_address)
    if raw_city and raw_city.lower() != "nan" and raw_city.lower() not in raw_address.lower():
        address_parts.append(raw_city)
    if raw_state and raw_state.lower() != "nan" and raw_state.lower() not in raw_address.lower():
        address_parts.append(raw_state)

    combined_address = ", ".join(address_parts)
    if not combined_address:
        combined_address = str(first_row.get("State Name (Billing)", "")).strip()

    # Normalize City & Address (Pathao RecipientCity is the District/State)
    recipient_city = normalize_city_name(raw_state)
    address_val = " ".join(combined_address.split()).title()

    # RecipientZone & Area: Smart Matching from Pathao Database
    recipient_area = ""
    extracted_zone = raw_city.title()
    if extracted_zone.lower() == "nan":
        extracted_zone = ""

    # Load Pathao Map for intelligent correction
    pathao_map_path = "resources/pathao_map.json"
    if os.path.exists(pathao_map_path):
        try:
            with open(pathao_map_path, "r") as f:
                pathao_map = json.load(f)

            # 1. Match City
            city_data = pathao_map.get(recipient_city)
            if not city_data:
                # Try fuzzy matching city name if direct lookup fails
                match = process.extractOne(recipient_city, pathao_map.keys())
                if match and match[1] > 85:
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
                            area_match = process.extractOne(address_val, area_names)
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
            if city_name.lower() in address_val.lower():
                recipient_city = city_name
                break
        if not recipient_city: recipient_city = "Dhaka" # Default to capital

    # If extracted_zone is just the city name again, try to peek into the address
    if not extracted_zone or extracted_zone.lower() in ["unknown", "nan", "", recipient_city.lower(), "dhaka", "chattogram"]:
        peeked = peek_zone_from_address(address_val)
        if peeked:
            extracted_zone = peeked
        else:
            extracted_zone = recipient_city # Final fallback

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
