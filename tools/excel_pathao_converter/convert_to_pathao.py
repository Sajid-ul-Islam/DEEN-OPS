#!/usr/bin/env python3
"""
Standalone Product-Wise Order List to Pathao Bulk Upload Converter.

This script is self-contained and portable. It converts e-commerce product-wise
order exports (Excel/CSV) where each product line item is a row into the
official 15-column Pathao Bulk Upload format.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Constants & Column Definitions
# ---------------------------------------------------------------------------

PATHAO_COLUMNS = [
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

DEFAULT_STORE_NAME = "Deen Commerce"
DEFAULT_WEIGHT = "0.5"

COLUMN_ALIASES: Dict[str, List[str]] = {
    "order_id": [
        "Order ID",
        "Order Number",
        "Order #",
        "Order No",
        "Order No.",
        "order_id",
        "order_number",
        "order no",
        "order #",
        "order id",
        "Invoice Number",
        "Invoice #",
        "Invoice No",
        "MerchantOrderId",
        "ID",
    ],
    "phone": [
        "Phone (Billing)",
        "Phone",
        "Billing Phone",
        "Customer Phone",
        "Phone Number",
        "Mobile",
        "Contact",
        "Phone (Shipping)",
        "Customer Mobile",
    ],
    "name": [
        "Full Name (Shipping)",
        "Full Name",
        "Full Name (Billing)",
        "Customer Name",
        "Recipient Name",
        "Billing Name",
        "Name",
        "Customer",
    ],
    "first_name": [
        "First Name (Shipping)",
        "First Name",
        "Shipping First Name",
        "First Name (Billing)",
        "Billing First Name",
    ],
    "last_name": [
        "Last Name (Shipping)",
        "Last Name",
        "Shipping Last Name",
        "Last Name (Billing)",
        "Billing Last Name",
        "Surname",
    ],
    "address": [
        "Address 1&2 (Shipping)",
        "Shipping Address",
        "Address (Shipping)",
        "Address",
        "Delivery Address",
        "Street Address",
        "Customer Address",
    ],
    "city": [
        "City (Shipping)",
        "Shipping City",
        "City",
        "District",
        "Recipient City",
        "Town / City",
    ],
    "state": [
        "State Code (Shipping)",
        "Shipping State",
        "State",
        "State Code",
        "Division",
        "State / County",
    ],
    "item_name": [
        "Item Name",
        "Product Name",
        "Product",
        "Line Item Name",
        "Item",
        "Product Title",
        "Title",
    ],
    "sku": ["SKU", "Item SKU", "Product SKU", "Variation SKU"],
    "quantity": [
        "Quantity",
        "Quantity (- Refund)",
        "Qty",
        "Quantity (Refund)",
        "Item Qty",
        "Item Quantity",
        "Line Item Quantity",
    ],
    "item_cost": [
        "Item Cost",
        "Line Item Price",
        "Price",
        "Item Price",
        "Cost",
        "Line Total",
        "Item Total",
    ],
    "order_total": [
        "Order Total Amount",
        "Total",
        "Order Total",
        "Total Amount",
        "Grand Total",
        "Order Amount",
        "Total (BDT)",
    ],
    "payment_method": [
        "Payment Method Title",
        "Payment Method",
        "Payment Type",
        "Payment Status",
        "Payment",
        "Payment Title",
    ],
}

# ---------------------------------------------------------------------------
# Data Cleaning & Normalization Helpers
# ---------------------------------------------------------------------------


def normalize_phone(phone_str: Any) -> str:
    """Normalize phone number to 11-digit BD mobile format (01XXXXXXXXX)."""
    if pd.isna(phone_str):
        return ""
    raw = str(phone_str).strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("880") and len(digits) > 10:
        digits = digits[3:]
    if not digits.startswith("0") and len(digits) == 10:
        digits = "0" + digits
    if len(digits) > 11:
        digits = digits[-11:]
    return digits


def detect_columns(df: pd.DataFrame) -> Dict[str, str | None]:
    """Map canonical column keys to actual DataFrame column names."""
    detected: Dict[str, str | None] = {}
    lower_map = {str(col).strip().lower(): col for col in df.columns}

    for key, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in df.columns:
                found = alias
                break
            if alias.lower() in lower_map:
                found = lower_map[alias.lower()]
                break
        detected[key] = found

    return detected


def clean_dataframe(df: pd.DataFrame, col_map: Dict[str, str | None]) -> pd.DataFrame:
    """Clean and standardize input columns."""
    df = df.copy()

    # Recipient name resolution
    if not col_map.get("name") or col_map["name"] not in df.columns:
        first_col = col_map.get("first_name")
        last_col = col_map.get("last_name")
        if first_col and first_col in df.columns:
            first_s = df[first_col].fillna("").astype(str).str.strip()
            last_s = (
                df[last_col].fillna("").astype(str).str.strip()
                if last_col and last_col in df.columns
                else ""
            )
            df["_resolved_name"] = (first_s + " " + last_s).str.strip()
            col_map["name"] = "_resolved_name"
        else:
            df["_resolved_name"] = "Customer"
            col_map["name"] = "_resolved_name"
    else:
        name_col = col_map["name"]
        df[name_col] = df[name_col].fillna("Customer").astype(str).str.strip()
        df[name_col] = df[name_col].replace(["nan", "None", ""], "Customer")

    # Clean numeric fields
    for key in ["quantity", "item_cost", "order_total"]:
        c = col_map.get(key)
        if c and c in df.columns:
            if df[c].dtype == "object":
                df[c] = df[c].astype(str).str.replace(r"[^\d.]", "", regex=True)
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # Clean string fields
    for key in [
        "order_id",
        "phone",
        "address",
        "city",
        "state",
        "item_name",
        "payment_method",
    ]:
        c = col_map.get(key)
        if c and c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    return df


def categorize_item(item_name: str) -> str:
    """Classify product item into concise summary category for Pathao ItemDesc."""
    n = str(item_name).lower()
    if "tank top" in n or "tanktop" in n or "tank-top" in n:
        return "TankTop"
    if "drop shoulder" in n or "oversized" in n:
        return "Drop Shoulder"
    if "active wear" in n or "activewear" in n or "jersey" in n:
        return "Active Wear"
    if "polo" in n:
        return "Polo"
    if "t-shirt" in n or "tshirt" in n or "tee" in n:
        return "T-Shirt"
    if "panjabi" in n or "punjabi" in n:
        return "Panjabi"
    if "pajama" in n or "pyjama" in n:
        return "Pajama"
    if "shirt" in n:
        return "Shirt"
    if "jeans" in n or "denim" in n:
        return "Jeans"
    if "trouser" in n or "pant" in n:
        return "Pant"
    if "hoodie" in n:
        return "Hoodie"
    if "jacket" in n:
        return "Jacket"
    if "attar" in n or "perfume" in n:
        return "Attar"
    if "cap" in n or "kufi" in n:
        return "Cap"

    # Default fallback: First 2-3 words cleaned
    cleaned = re.sub(r"[^\w\s-]", "", item_name).strip()
    words = cleaned.split()
    return " ".join(words[:2]).title() if words else "Apparel"


def build_item_description(
    items_df: pd.DataFrame, item_col: str | None, qty_col: str | None
) -> str:
    """Build item description (e.g. '2x Drop Shoulder, 1x Jeans')."""
    if not item_col or item_col not in items_df.columns:
        return "General Items"

    summary: Dict[str, int] = {}
    for _, row in items_df.iterrows():
        raw_name = str(row.get(item_col, "")).strip()
        if not raw_name or raw_name.lower() == "nan":
            continue
        cat = categorize_item(raw_name)
        try:
            qty = (
                int(float(row.get(qty_col, 1)))
                if qty_col and qty_col in items_df.columns
                else 1
            )
            qty = max(1, qty)
        except Exception:
            qty = 1
        summary[cat] = summary.get(cat, 0) + qty

    if not summary:
        return "General Items"

    parts = [f"{q}x {cat}" for cat, q in summary.items()]
    return ", ".join(parts)


def resolve_address_and_city(
    row: pd.Series,
    addr_col: str | None,
    city_col: str | None,
    state_col: str | None,
) -> Tuple[str, str, str]:
    """Resolve full address, recipient city, and zone without duplicate names."""
    raw_addr = str(row.get(addr_col, "")).strip() if addr_col else ""
    raw_city = str(row.get(city_col, "")).strip() if city_col else ""
    raw_state = str(row.get(state_col, "")).strip() if state_col else ""

    if raw_addr.lower() == "nan":
        raw_addr = ""
    if raw_city.lower() == "nan":
        raw_city = ""
    if raw_state.lower() == "nan":
        raw_state = ""

    # Normalization for common city names
    norm_city = raw_city.title()
    if not norm_city or norm_city.lower() in ["nan", "none", ""]:
        norm_city = raw_state.title() if raw_state else "Dhaka"

    # Zone detection
    norm_zone = norm_city

    # Full combined address without duplicates
    parts = []
    if raw_addr and raw_addr.lower() != "nan":
        parts.append(raw_addr)
    if (
        raw_city
        and raw_city.lower() != "nan"
        and raw_city.lower() not in raw_addr.lower()
    ):
        parts.append(raw_city)
    if (
        raw_state
        and raw_state.lower() != "nan"
        and raw_state.lower() not in raw_addr.lower()
        and raw_state.lower() not in raw_city.lower()
    ):
        parts.append(raw_state)

    full_address = ", ".join(parts) if parts else (raw_addr or "Address Not Provided")
    return full_address, norm_city, norm_zone


def calculate_amount_to_collect(
    group: pd.DataFrame, total_col: str | None, payment_col: str | None, city: str
) -> int:
    """Calculate Cash on Delivery (COD) amount to collect."""
    if not total_col or total_col not in group.columns:
        return 0

    first_row = group.iloc[0]
    total_val = float(first_row.get(total_col, 0) or 0)
    pay_method = (
        str(first_row.get(payment_col, "")).lower()
        if payment_col and payment_col in group.columns
        else ""
    )

    # Prepaid detection (bKash, Nagad, Card, SSLCommerz, etc.)
    is_prepaid = any(
        kw in pay_method
        for kw in [
            "bkash",
            "nagad",
            "rocket",
            "sslcommerz",
            "card",
            "bank",
            "online",
            "paid",
            "advance",
        ]
    )

    if is_prepaid:
        # Prepaid orders have 0 COD collection unless delivery fee only
        return 0

    return int(round(total_val))


# ---------------------------------------------------------------------------
# Core Transformation Logic
# ---------------------------------------------------------------------------


def convert_orders(
    df_raw: pd.DataFrame,
    store_name: str = DEFAULT_STORE_NAME,
    default_weight: str = DEFAULT_WEIGHT,
) -> pd.DataFrame:
    """
    Core function: transforms product-wise DataFrame to Pathao Bulk Upload DataFrame.
    """
    col_map = detect_columns(df_raw)
    df = clean_dataframe(df_raw, col_map)

    order_col = col_map.get("order_id")
    phone_col = col_map.get("phone")

    # Determine grouping column: prefer Order ID if present, otherwise Phone
    if (
        order_col
        and order_col in df.columns
        and df[order_col].replace("", pd.NA).notna().any()
    ):
        df["_group_key"] = df[order_col].astype(str).str.strip()
    elif phone_col and phone_col in df.columns:
        df["_group_key"] = df[phone_col].apply(normalize_phone)
    else:
        # Fallback to index grouping
        df["_group_key"] = df.index.astype(str)

    name_col = col_map.get("name")
    addr_col = col_map.get("address")
    city_col = col_map.get("city")
    state_col = col_map.get("state")
    item_col = col_map.get("item_name")
    qty_col = col_map.get("quantity")
    total_col = col_map.get("order_total")
    pay_col = col_map.get("payment_method")

    pathao_records: List[Dict[str, Any]] = []

    for group_key, group in df.groupby("_group_key", sort=False):
        if not str(group_key).strip() or str(group_key).lower() in ["nan", "none"]:
            continue

        first_row = group.iloc[0]

        # Order ID
        raw_order_id = str(first_row.get(order_col, group_key)).strip()
        if raw_order_id.endswith(".0"):
            raw_order_id = raw_order_id[:-2]

        # Recipient Name
        recipient_name = str(first_row.get(name_col, "Customer")).strip().title()
        if not recipient_name or recipient_name.lower() in ["nan", "none", ""]:
            recipient_name = "Customer"

        # Phone
        raw_phone = str(first_row.get(phone_col, "")).strip() if phone_col else ""
        norm_phone = normalize_phone(raw_phone)
        if not norm_phone or len(norm_phone) < 11:
            norm_phone = norm_phone or "01700000000"

        # Address & City
        address_val, recipient_city, recipient_zone = resolve_address_and_city(
            first_row, addr_col, city_col, state_col
        )

        # Quantity
        if qty_col and qty_col in group.columns:
            total_qty = int(group[qty_col].sum())
            if total_qty <= 0:
                total_qty = len(group)
        else:
            total_qty = len(group)

        # Item Description
        item_desc = build_item_description(group, item_col, qty_col)

        # Amount to Collect
        amount_to_collect = calculate_amount_to_collect(
            group, total_col, pay_col, recipient_city
        )

        # Special instruction
        special_instruction = ""
        if pay_col and pay_col in group.columns:
            pm = str(first_row.get(pay_col, "")).strip()
            if pm:
                special_instruction = f"Payment: {pm}"

        record = {
            "ItemType": "Parcel",
            "StoreName": store_name,
            "MerchantOrderId": raw_order_id,
            "RecipientName(*)": recipient_name,
            "RecipientPhone(*)": norm_phone,
            "RecipientAddress(*)": address_val,
            "RecipientCity(*)": recipient_city,
            "RecipientZone(*)": recipient_zone,
            "RecipientArea": "",
            "AmountToCollect(*)": amount_to_collect,
            "ItemQuantity": total_qty,
            "ItemWeight": default_weight,
            "ItemDesc": item_desc,
            "SpecialInstruction": special_instruction,
            "WarehouseOutlet": "",
        }
        pathao_records.append(record)

    out_df = pd.DataFrame(pathao_records)
    for c in PATHAO_COLUMNS:
        if c not in out_df.columns:
            out_df[c] = ""

    return out_df[PATHAO_COLUMNS]


def convert_file(
    input_path: str,
    output_path: str | None = None,
    store_name: str = DEFAULT_STORE_NAME,
    default_weight: str = DEFAULT_WEIGHT,
) -> str:
    """Reads input Excel/CSV, converts to Pathao bulk, and saves to output_path."""
    input_path = os.path.abspath(input_path)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Read input file preserving strings/leading zeros
    ext = os.path.splitext(input_path)[1].lower()
    if ext in [".xlsx", ".xls", ".xlsm"]:
        df_raw = pd.read_excel(input_path, dtype=str)
    elif ext in [".csv", ".txt"]:
        df_raw = pd.read_csv(input_path, dtype=str)
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. Supported: .xlsx, .xls, .csv"
        )

    out_df = convert_orders(
        df_raw, store_name=store_name, default_weight=default_weight
    )

    # Determine output path if not given
    if not output_path:
        dir_name = os.path.dirname(input_path)
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(dir_name, f"{base_name}_Pathao_Bulk.xlsx")
    else:
        output_path = os.path.abspath(output_path)

    # Export styled Excel using openpyxl
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        out_df.to_excel(writer, sheet_name="Pathao Bulk", index=False)
        ws = writer.sheets["Pathao Bulk"]

        # Openpyxl styling
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        header_fill = PatternFill(
            start_color="1E3A8A", end_color="1E3A8A", fill_type="solid"
        )
        header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        header_align = Alignment(horizontal="center", vertical="center")
        cell_font = Font(name="Segoe UI", size=10)
        thin_side = Side(border_style="thin", color="CBD5E1")
        border = Border(
            left=thin_side, right=thin_side, top=thin_side, bottom=thin_side
        )

        ws.row_dimensions[1].height = 28

        # Find column indices for phone and merchant order id
        phone_col_idx = None
        order_col_idx = None
        for col_idx, col_name in enumerate(out_df.columns, start=1):
            if "phone" in col_name.lower():
                phone_col_idx = col_idx
            if "merchantorderid" in col_name.lower() or "order" in col_name.lower():
                order_col_idx = col_idx

        # Format header row
        for col_idx in range(1, len(out_df.columns) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_align
            cell.border = border

        # Format data rows
        for row_idx in range(2, len(out_df) + 2):
            ws.row_dimensions[row_idx].height = 20
            for col_idx in range(1, len(out_df.columns) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = cell_font
                cell.border = border

                if col_idx in (phone_col_idx, order_col_idx):
                    cell.number_format = "@"
                    val = str(cell.value) if cell.value is not None else ""
                    if (
                        col_idx == phone_col_idx
                        and val
                        and not val.startswith("0")
                        and len(val) == 10
                    ):
                        val = "0" + val
                    cell.value = val

        # Auto-fit column widths
        for col_idx, col_name in enumerate(out_df.columns, start=1):
            max_len = len(str(col_name))
            for row_idx in range(2, len(out_df) + 2):
                val_str = str(ws.cell(row=row_idx, column=col_idx).value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            col_letter = ws.cell(row=1, column=col_idx).column_letter
            ws.column_dimensions[col_letter].width = min(max_len + 4, 55)

    return output_path


# ---------------------------------------------------------------------------
# Graphical User Interface (GUI)
# ---------------------------------------------------------------------------


def launch_gui():
    """Launch a clean desktop file picker and converter dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print(
            "Tkinter is not available. Please run in CLI mode: python convert_to_pathao.py -i <file>"
        )
        return

    root = tk.Tk()
    root.title("Pathao Bulk Order Converter")
    root.geometry("520x280")
    root.resizable(False, False)

    # Styling
    root.configure(bg="#F8F9FA")

    title_label = tk.Label(
        root,
        text="Excel to Pathao Bulk Converter",
        font=("Segoe UI", 14, "bold"),
        bg="#F8F9FA",
        fg="#1E293B",
    )
    title_label.pack(pady=(18, 6))

    sub_label = tk.Label(
        root,
        text="Convert product-wise order lists into official Pathao upload format",
        font=("Segoe UI", 9),
        bg="#F8F9FA",
        fg="#64748B",
    )
    sub_label.pack(pady=(0, 16))

    selected_file = tk.StringVar(value="")

    file_frame = tk.Frame(root, bg="#F8F9FA")
    file_frame.pack(fill="x", padx=24, pady=4)

    file_entry = tk.Entry(
        file_frame, textvariable=selected_file, font=("Segoe UI", 9), width=42
    )
    file_entry.pack(side="left", padx=(0, 8), ipady=3)

    def browse_file():
        filetypes = [
            ("Excel and CSV Files", "*.xlsx *.xls *.csv"),
            ("Excel Files", "*.xlsx *.xls"),
            ("CSV Files", "*.csv"),
            ("All Files", "*.*"),
        ]
        chosen = filedialog.askopenfilename(
            title="Select Product-Wise Order List File", filetypes=filetypes
        )
        if chosen:
            selected_file.set(chosen)

    browse_btn = tk.Button(
        file_frame,
        text="Browse...",
        command=browse_file,
        font=("Segoe UI", 9),
        bg="#E2E8F0",
        fg="#1E293B",
        relief="flat",
        padx=10,
        pady=2,
    )
    browse_btn.pack(side="right")

    status_var = tk.StringVar(value="Ready. Select an Excel file to convert.")
    status_label = tk.Label(
        root, textvariable=status_var, font=("Segoe UI", 8), bg="#F8F9FA", fg="#475569"
    )
    status_label.pack(pady=(12, 10))

    def run_conversion():
        in_file = selected_file.get().strip()
        if not in_file:
            messagebox.showwarning(
                "File Missing", "Please select a product-wise Excel or CSV file."
            )
            return

        status_var.set("Converting orders...")
        root.update()

        try:
            out_file = convert_file(in_file)
            status_var.set("Conversion successful!")
            messagebox.showinfo(
                "Success",
                f"Pathao Bulk file successfully created:\n\n{out_file}",
            )
        except Exception as e:
            status_var.set(f"Error: {str(e)[:50]}")
            messagebox.showerror(
                "Conversion Failed", f"An error occurred during conversion:\n\n{str(e)}"
            )

    convert_btn = tk.Button(
        root,
        text="Convert to Pathao Bulk",
        command=run_conversion,
        font=("Segoe UI", 11, "bold"),
        bg="#0284C7",
        fg="white",
        activebackground="#0369A1",
        activeforeground="white",
        relief="flat",
        padx=18,
        pady=6,
        cursor="hand2",
    )
    convert_btn.pack(pady=(4, 12))

    root.mainloop()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Convert product-wise order list to Pathao Bulk Upload format."
    )
    parser.add_argument("-i", "--input", help="Path to input Excel or CSV file")
    parser.add_argument("-o", "--output", help="Path to output Excel file (optional)")
    parser.add_argument(
        "--store-name", default=DEFAULT_STORE_NAME, help="Pathao store name"
    )
    parser.add_argument(
        "--default-weight", default=DEFAULT_WEIGHT, help="Default parcel weight in kg"
    )
    parser.add_argument(
        "--gui", action="store_true", help="Explicitly launch graphical user interface"
    )

    args = parser.parse_args()

    # If an argument is passed without flag (e.g. drag and drop)
    if not args.input and len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        args.input = sys.argv[1]

    # If no input is specified, launch GUI
    if not args.input or args.gui:
        launch_gui()
        return

    try:
        out_file = convert_file(
            input_path=args.input,
            output_path=args.output,
            store_name=args.store_name,
            default_weight=args.default_weight,
        )
        print("[SUCCESS] Converted successfully!")
        print(f"Output saved to: {out_file}")
    except Exception as e:
        print(f"[ERROR] Conversion failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
