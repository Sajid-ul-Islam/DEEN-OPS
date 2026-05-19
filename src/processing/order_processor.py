import pandas as pd
import streamlit as st
import os
import json
import re
from src.processing.categorization import get_category_for_sales
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
    for c in df.columns:
        c_lower = c.lower()
        if c_lower in ["trxid", "transaction id", "transaction", "trx id", "bkash"]:
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
    if "active wear" in name_lower or "activewear" in name_lower or "sports" in name_lower or "jersey" in name_lower:
        return "Active Wear"
    if "full sleeve" in name_lower or "fs t-shirt" in name_lower or "fs tshirt" in name_lower:
        return "FS T-Shirt"
    if "sweatshirt" in name_lower:
        return "Sweatshirt"
    if "sweater" in name_lower:
        return "Sweater"
    if "hoodie" in name_lower:
        return "Hoodie"
    if "jacket" in name_lower:
        return "Jacket"
    if "t-shirt" in name_lower or "tshirt" in name_lower or "tee" in name_lower or "t shirt" in name_lower:
        return "HS T-Shirt"
    if "polo" in name_lower:
        return "Polo"
    if "panjabi" in name_lower or "punjabi" in name_lower:
        return "Panjabi"
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
    if "shirt" in name_lower:
        return "Shirt"
    if "wallet" in name_lower:
        return "Wallet"
    if "trouser" in name_lower:
        return "Trouser"
    if "executive formal shirt" in name_lower:
        return "Formal"
    if "t-shirt" in name_lower:
        return "T-Shirt"
    if "belt" in name_lower:
        return "Belt"
    if "kaftan" in name_lower:
        return "Kaftan"
    if "boxer" in name_lower:
        return "Boxer"
    if "mask" in name_lower:
        return "Mask"
    if "polo" in name_lower:
        return "Polo"
    if "turtleneck" or "turtle neck" in name_lower:
        return "Turtleneck"
    
    parts = str(item_name).split(" - ")
    return parts[0].strip()


def build_item_description(cat_map, total_qty, trx_info=""):
    """
    Builds the ItemDesc string for Pathao from a category map.
    """
    full_desc = ""

    if int(total_qty) == 1:
        # Single Item
        for cat, items in cat_map.items():
            for item_str, count in items.items():
                full_desc = str(item_str).strip().rstrip(';')
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
                clean_item = str(item_str).strip().rstrip(';')
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
    full_desc = re.sub(r'(\s*;\s*)+', '; ', full_desc).strip()

    return full_desc


def parse_manual_item_lines(raw_text):
    """
    Parses a raw text block of manual items into a category map and total quantity.
    """
    lines = [line.strip() for line in str(raw_text).splitlines() if line.strip()]
    cat_map = {}
    total_qty = 0
    
    for line in lines:
        line = line.strip().rstrip(';')
        if not line:
            continue
            
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
                    
        item_str = item_str.strip().rstrip(';')
        item_str = item_str.replace(" | ", " - ")
        
        parts = item_str.split(" - ")
        category = get_short_sub_category(parts[0])
            
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
    Splits into multiple parcels if items have different dispatch locations,
    assigning the delivery fee to the parcel with the highest item value.
    Returns a list of dictionaries (records).
    """
    order_col = data_cols.get("order_col", "Order Number")
    group = group.copy()

    # Determine dispatch groups for each row to handle split parcels
    def get_dispatch_group(row):
        sugg = str(row.get("Dispatch Suggestion", "")).strip()
        if sugg and sugg.lower() != "nan" and sugg != "Multiple / Split":
            return sugg
        val = str(row.get(order_col, "")).lower()
        if val.endswith(" c"): return "Cumilla"
        if val.endswith(" w"): return "Wari"
        if val.endswith(" s"): return "Sylhet"
        return "Ecom-Mirpur"
        
    group["_dispatch_loc"] = group.apply(get_dispatch_group, axis=1)
    
    subgroups = [df_sub for _, df_sub in group.groupby("_dispatch_loc")]

    # --- Amount to Collect & Payment Info (across the entire customer group) ---
    total_to_collect = 0
    trx_types = set()

    if order_col in group.columns:
        unique_orders = group.drop_duplicates(subset=[order_col])
    else:
        unique_orders = group.head(1)

    for _, order_row in unique_orders.iterrows():
        order_total = order_row.get("Order Total Amount", 0)
        pay_method = str(order_row.get("Payment Method Title", "")).lower()

        # Determine if this specific order is already paid
        is_paid = any(kw in pay_method for kw in ["pay online", "ssl", "bkash", "card", "nagad", "rocket", "portpos", "paid"])

        if is_paid:
            if "pay online" in pay_method or "ssl" in pay_method:
                trx_types.add("Paid by SSL")
            elif "bkash" in pay_method:
                trx_types.add("Paid by Bkash")
            else:
                trx_types.add("Paid by SSL")
        else:
            total_to_collect += float(order_total) if pd.notna(order_total) and str(order_total).strip() else 0

    trx_info = " / ".join(sorted(list(trx_types)))

    # Append Transaction IDs
    trx_col = data_cols["trx_col"]
    if trx_col in group.columns and "Paid by Bkash" in trx_types:
        trx_vals = set(group[trx_col].dropna().astype(str))
        cleaned_trx = [t for t in trx_vals if t.lower() != "nan" and t.strip() != ""]
        if cleaned_trx:
            trx_str = ", ".join(cleaned_trx)
            if trx_info:
                trx_info += f" - {trx_str}"
            else:
                trx_info = trx_str

    parcel_records = []
    parcel_base_values = []

    # --- Process each dispatch parcel separately ---
    for df_sub in subgroups:
        first_row = df_sub.iloc[0]
        total_qty = df_sub["Quantity"].sum()

        # Categorize Items and calculate Base Value for this parcel
        cat_map = {}
        base_val = 0
        for _, row in df_sub.iterrows():
            item_name = str(row.get("Item Name", "")).strip()
            sku = row.get("SKU", "")
            
            category = get_short_sub_category(item_name)
            
            clean_sku = str(sku).strip()
            if clean_sku and clean_sku.lower() != "nan":
                item_str = f"{item_name} - {clean_sku}"
            else:
                item_str = item_name

            qty = int(float(row.get("Quantity", 0))) if pd.notna(row.get("Quantity")) else 0
            cost = float(row.get("Item Cost", 0)) if pd.notna(row.get("Item Cost")) and str(row.get("Item Cost")).strip() else 0

            if category not in cat_map:
                cat_map[category] = {}
            if item_str not in cat_map[category]:
                cat_map[category][item_str] = 0
            cat_map[category][item_str] += qty
            
            base_val += (cost * qty)

        full_desc = build_item_description(cat_map, total_qty, trx_info)

        # Address Processing
        addr_col = data_cols["addr_col"]
        raw_address = str(first_row.get(addr_col, "")).strip()
        raw_state = str(first_row.get(data_cols["state_col"], "")).strip()
        raw_city = str(first_row.get(data_cols["city_col"], "")).strip()

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

        recipient_city = normalize_city_name(raw_state)
        address_val = " ".join(combined_address.split()).title()

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
            except:
                pass 

        # Combine merchant IDs
        if order_col in df_sub.columns:
            order_ids = []
            for _, r in df_sub.iterrows():
                val = str(r[order_col])
                if val.lower() == "nan":
                    continue
                if val.endswith(".0"):
                    val = val[:-2]
                    
                sugg = str(r.get("Dispatch Suggestion", "")).strip()
                suffix = ""
                if sugg == "Cumilla": suffix = " c"
                elif sugg == "Wari": suffix = " w"
                elif sugg == "Sylhet": suffix = " s"
                
                if suffix and not val.endswith(suffix):
                    val += suffix
                    
                if val not in order_ids:
                    order_ids.append(val)
                    
            combined_merchant_id = ", ".join(order_ids)
        else:
            combined_merchant_id = "N/A"

        # Final Brute Force Validation
        recipient_name = str(first_row.get(data_cols["name_col"], "")).strip().title()
        if not recipient_name or recipient_name.lower() == "nan":
            recipient_name = "Customer"

        if not recipient_city or recipient_city.lower() in ["unknown", "nan", ""]:
            for city_name in ["Dhaka", "Chittagong", "Chattogram", "Sylhet", "Khulna", "Rajshahi", "Barisal", "Rangpur"]:
                if city_name.lower() in address_val.lower():
                    recipient_city = city_name
                    break
            if not recipient_city: recipient_city = "Dhaka" 

        if not extracted_zone or extracted_zone.lower() in ["unknown", "nan", "", recipient_city.lower(), "dhaka", "chattogram"]:
            peeked = peek_zone_from_address(address_val)
            if peeked:
                extracted_zone = peeked
            else:
                extracted_zone = recipient_city

        special_instruction = ""
        if len(subgroups) > 1:
            special_instruction = "⚠️ SPLIT PARCEL - This is part of a multi-parcel order."

        if trx_info:
            if special_instruction:
                special_instruction += f" | {trx_info}"
            else:
                special_instruction = trx_info

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
            "AmountToCollect(*)": 0, # Distributed below
            "ItemQuantity": int(total_qty) if total_qty > 0 else 1,
            "ItemWeight": "0.5",
            "ItemDesc": full_desc if full_desc else "General Items",
            "SpecialInstruction": special_instruction,
        }
        
        parcel_records.append(record)
        parcel_base_values.append(base_val)

    # --- Distribute Total Amount to Collect across parcels ---
    total_base = sum(parcel_base_values)
    
    # Fallback if Order Total Amount is missing but it's a COD order
    if total_to_collect == 0 and "Paid" not in trx_info and total_base > 0:
        city_lower = str(recipient_city).lower()
        delivery_fee = 60 if any(d in city_lower for d in ["dhaka", "savar", "keraniganj"]) else 120
        total_to_collect = total_base + delivery_fee

    if total_to_collect > 0:
        diff = total_to_collect - total_base
        
        # If difference is unusually large (> 250 TK), it indicates a partial order 
        # where items were removed (e.g., Out of Stock). We must not overcharge the customer.
        # We sum up the item costs they contain and add a standard delivery fee.
        if diff > 250:
            city_lower = str(recipient_city).lower()
            delivery_fee = 60 if any(d in city_lower for d in ["dhaka", "savar", "keraniganj"]) else 120
            total_to_collect = total_base + delivery_fee
            
            for rec in parcel_records:
                if rec["SpecialInstruction"]:
                    rec["SpecialInstruction"] += " | ⚠️ PARTIAL ORDER"
                else:
                    rec["SpecialInstruction"] = "⚠️ PARTIAL ORDER"

        if len(parcel_records) == 1:
            parcel_records[0]["AmountToCollect(*)"] = total_to_collect
        else:
            # Add delivery fee/discounts only to the parcel with the highest base value
            max_idx = parcel_base_values.index(max(parcel_base_values))
            sum_others = sum(v for i, v in enumerate(parcel_base_values) if i != max_idx)
            
            for i, rec in enumerate(parcel_records):
                if i == max_idx:
                    rec["AmountToCollect(*)"] = max(0, total_to_collect - sum_others)
                else:
                    rec["AmountToCollect(*)"] = parcel_base_values[i]
    
    return parcel_records


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
        records = process_single_order_group(phone, group, data_cols)
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
    ]

    # Ensure all target columns exist
    for col in target_columns:
        if col not in result_df.columns:
            result_df[col] = ""

    return result_df[target_columns]
