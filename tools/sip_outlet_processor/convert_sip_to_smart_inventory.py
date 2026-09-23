#!/usr/bin/env python3
"""Standalone SIP → Smart Inventory Converter CLI.

Reads an order export (Excel / CSV) containing SIP outlet-routing JSON,
maps each line item to its dispatch outlet, and produces the unified
Smart Inventory 'Current Stock Report' layout:

    Product, Size, SKU, Outlet, Stock Qty, Price, Last Updated

'Stock Qty' holds the aggregated units required by the orders (a demand
sheet in stock-report shape) per Product/Size/SKU/Outlet combination.

Usage:
    python tools/sip_outlet_processor/convert_sip_to_smart_inventory.py orders.xlsx
    python tools/sip_outlet_processor/convert_sip_to_smart_inventory.py orders.xlsx -o demand.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Add project root to sys.path so it can reuse src.processing if available.
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.processing.sip_outlet_processor import (  # noqa: E402
    compute_sip_stats,
    convert_sip_to_smart_inventory,
    process_order_item_outlets,
)

SMART_INVENTORY_COLUMNS = [
    "Product",
    "Size",
    "SKU",
    "Outlet",
    "Stock Qty",
    "Price",
    "Last Updated",
]


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Convert SIP-mapped order exports into the Smart Inventory "
            "Current Stock Report format (Product, Size, SKU, Outlet, Stock Qty, Price, Last Updated)."
        )
    )
    parser.add_argument("input_file", help="Path to input Excel or CSV file")
    parser.add_argument(
        "-o",
        "--output",
        help="Path to output file (default: <input>_smart_inventory.csv)",
    )
    parser.add_argument(
        "--order-col",
        default="Order Number",
        help="Order ID column name (default: 'Order Number')",
    )
    parser.add_argument(
        "--sip-col", default="SIP", help="SIP JSON column name (default: 'SIP')"
    )
    parser.add_argument(
        "--target-col",
        default="Item Outlet",
        help="Outlet-assignment column (default: 'Item Outlet')",
    )
    parser.add_argument(
        "--item-col",
        default="Item Name",
        help="Product/item name column (default: 'Item Name')",
    )
    parser.add_argument(
        "--sku-col",
        default="SKU",
        help="SKU column (default: 'SKU'; pass 'none' to disable)",
    )
    parser.add_argument(
        "--qty-col",
        default="Quantity",
        help="Per-line quantity column (default: 'Quantity')",
    )
    parser.add_argument(
        "--price-col",
        default="Item Cost",
        help="Per-unit price column (default: 'Item Cost'; pass 'none' to disable)",
    )
    parser.add_argument(
        "--size-col",
        default=None,
        help="Optional explicit size column (default: parsed from 'Product - Size' item names)",
    )

    args = parser.parse_args()

    sku_col = None if args.sku_col.lower() == "none" else args.sku_col
    price_col = None if args.price_col.lower() == "none" else args.price_col

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  DEEN-OPS :: SIP → Smart Inventory Converter")
    print("=" * 60)
    print(f"Reading: {input_path}")

    if input_path.suffix.lower() == ".csv":
        df = pd.read_csv(input_path)
    else:
        df = pd.read_excel(input_path)

    print(f"Loaded {len(df):,} rows from {input_path.name}")

    # Derive outlet assignment when not already present
    if args.target_col not in df.columns:
        df = process_order_item_outlets(
            df=df,
            order_col=args.order_col,
            sip_col=args.sip_col,
            target_col=args.target_col,
        )

    stats = compute_sip_stats(
        df=df,
        order_col=args.order_col,
        outlet_col=args.target_col,
    )

    print("\n[Outlet Allocations]")
    total_items = stats["total_items"] or 1
    for outlet, count in stats["outlet_counts"].items():
        pct = count / total_items * 100
        print(f"  * {outlet:<15} : {count:>4} items ({pct:.1f}%)")

    smart_df = convert_sip_to_smart_inventory(
        df=df,
        order_col=args.order_col,
        sip_col=args.sip_col,
        target_col=args.target_col,
        item_col=args.item_col,
        sku_col=sku_col,
        qty_col=args.qty_col,
        price_col=price_col,
        size_col=args.size_col,
    )

    if smart_df.empty:
        print("\n[!] No convertible line items found — nothing to write.")
        sys.exit(1)

    smart_df = smart_df[SMART_INVENTORY_COLUMNS]
    total_units = int(smart_df["Stock Qty"].sum())

    print("\n[Smart Inventory Demand Summary]")
    print(f"  - Unique Product/Size/SKU/Outlet rows : {len(smart_df):,}")
    print(f"  - Total Units Required                : {total_units:,}")
    for outlet, grp in smart_df.groupby("Outlet"):
        print(f"  * {outlet:<15} : {int(grp['Stock Qty'].sum()):>4} units")

    output_path = args.output or input_path.parent / (
        f"{input_path.stem}_smart_inventory.csv"
    )
    output_path = Path(output_path)

    if output_path.suffix.lower() in (".xlsx", ".xls"):
        smart_df.to_excel(output_path, index=False, engine="openpyxl")
    else:
        smart_df.to_csv(output_path, index=False)

    print(f"\nSaved Smart Inventory file to: {output_path}")
    print("\n[SUCCESS] Conversion completed successfully.\n")


if __name__ == "__main__":
    main()
