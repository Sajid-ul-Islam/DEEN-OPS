#!/usr/bin/env python3
"""Standalone SIP Item-Wise Outlet Processor CLI.

Extracts item-wise outlet fulfillment information from the SIP JSON column
in order exports (Excel / CSV) and generates an enriched spreadsheet with
the 'Item Outlet' column.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path so it can reuse src.processing if available,
# but also operates self-contained if needed.
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from src.processing.sip_outlet_processor import (
        compute_sip_stats,
        generate_outlet_product_listing,
        generate_pathao_bulk_consignments,
        process_order_item_outlets,
    )
except ImportError:
    # Fallback to embedded logic if run completely decoupled
    import json
    from typing import Any, Dict, List

    OUTLET_CANONICAL_NAMES = {
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
        if slug is None or pd.isna(slug):
            return "Warehouse"
        s = str(slug).strip()
        if not s:
            return "Warehouse"
        s_lower = s.lower()
        if canonical and s_lower in OUTLET_CANONICAL_NAMES:
            return OUTLET_CANONICAL_NAMES[s_lower]
        cleaned = s.replace("_", " ").strip()
        if canonical:
            cleaned = cleaned.replace("-", " ")
        return cleaned.title()

    def parse_sip_field(val: Any) -> List[Dict[str, Any]]:
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
        if df.empty or order_col not in df.columns or sip_col not in df.columns:
            df_out = df.copy()
            df_out[target_col] = default_outlet
            return df_out

        df_out = df.copy()
        item_outlets = []

        for _, group in df_out.groupby(order_col, sort=False):
            sip_val = None
            for val in group[sip_col]:
                if pd.notna(val) and str(val).strip():
                    sip_val = val
                    break
            parsed_items = parse_sip_field(sip_val)
            for idx in range(len(group)):
                if idx < len(parsed_items):
                    slug = parsed_items[idx].get("outlet_slug") or parsed_items[idx].get("outlet_name")
                    item_outlets.append(normalize_outlet_name(slug, canonical=canonical))
                elif parsed_items:
                    last_slug = parsed_items[-1].get("outlet_slug") or parsed_items[-1].get("outlet_name")
                    item_outlets.append(normalize_outlet_name(last_slug, canonical=canonical))
                else:
                    item_outlets.append(default_outlet)

        df_out[target_col] = item_outlets
        cols = df_out.columns.tolist()
        if sip_col in cols and target_col in cols:
            cols.remove(target_col)
            sip_idx = cols.index(sip_col)
            cols.insert(sip_idx + 1, target_col)
            df_out = df_out[cols]
        return df_out

    def compute_sip_stats(df: pd.DataFrame, order_col: str = "Order Number", outlet_col: str = "Item Outlet") -> Dict[str, Any]:
        total_items = len(df)
        total_orders = df[order_col].nunique() if order_col in df.columns else 0
        outlet_counts = df[outlet_col].value_counts().to_dict() if outlet_col in df.columns else {}
        multi_item_orders = 0
        split_orders = []
        for order_id, group in df.groupby(order_col, sort=False):
            if len(group) > 1:
                multi_item_orders += 1
            unique_outlets = group[outlet_col].dropna().unique().tolist()
            if len(unique_outlets) > 1:
                split_orders.append({"order_id": order_id, "outlets": unique_outlets})
        return {
            "total_items": total_items,
            "total_orders": total_orders,
            "multi_item_orders": multi_item_orders,
            "split_orders_count": len(split_orders),
            "split_orders": split_orders,
            "outlet_counts": outlet_counts,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Extract item-wise outlet mappings from SIP column in order exports."
    )
    parser.add_argument("input_file", help="Path to input Excel or CSV file")
    parser.add_argument("-o", "--output", help="Path to output file (default: <input>_with_outlets.xlsx)")
    parser.add_argument("--order-col", default="Order Number", help="Order ID column name (default: 'Order Number')")
    parser.add_argument("--sip-col", default="SIP", help="SIP JSON column name (default: 'SIP')")
    parser.add_argument("--target-col", default="Item Outlet", help="New column name (default: 'Item Outlet')")
    parser.add_argument("--raw-slugs", action="store_true", help="Keep raw outlet slugs instead of canonical names")

    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  DEEN-OPS :: SIP Item-Wise Outlet Processor")
    print("=" * 60)
    print(f"Reading: {input_path}")

    if input_path.suffix.lower() == ".csv":
        df = pd.read_csv(input_path)
    else:
        df = pd.read_excel(input_path)

    print(f"Loaded {len(df):,} rows from {input_path.name}")

    processed_df = process_order_item_outlets(
        df=df,
        order_col=args.order_col,
        sip_col=args.sip_col,
        target_col=args.target_col,
        canonical=not args.raw_slugs,
    )

    stats = compute_sip_stats(
        df=processed_df,
        order_col=args.order_col,
        outlet_col=args.target_col,
    )

    print("\n[Summary Statistics]")
    print(f"  - Total Line Items     : {stats['total_items']:,}")
    print(f"  - Total Orders         : {stats['total_orders']:,}")
    print(f"  - Multi-Item Orders    : {stats['multi_item_orders']:,}")
    print(f"  - Split-Outlet Orders  : {stats['split_orders_count']:,}")
    print("\n[Outlet Allocations]")
    for outlet, count in stats["outlet_counts"].items():
        pct = (count / stats['total_items'] * 100) if stats['total_items'] else 0
        print(f"  * {outlet:<15} : {count:>4} items ({pct:.1f}%)")

    if stats["split_orders_count"] > 0:
        print(f"\n[!] Split Orders Alert ({stats['split_orders_count']} orders require multi-outlet fulfillment):")
        for split in stats["split_orders"]:
            print(f"    - Order #{split['order_id']}: {' + '.join(split['outlets'])}")

    output_path = args.output
    if not output_path:
        output_path = input_path.parent / f"{input_path.stem}_with_outlets.xlsx"
    else:
        output_path = Path(output_path)

    print(f"\nSaving enriched file to: {output_path}")
    if output_path.suffix.lower() == ".csv":
        processed_df.to_csv(output_path, index=False)
    else:
        processed_df.to_excel(output_path, index=False, engine="openpyxl")

    # Generate Warehouse Product Listing (Picking List)
    item_col = "Item Name" if "Item Name" in processed_df.columns else processed_df.columns[1]
    qty_col = "Quantity" if "Quantity" in processed_df.columns else "Qty"
    sku_col = "SKU" if "SKU" in processed_df.columns else None

    if item_col in processed_df.columns and qty_col in processed_df.columns:
        wh_listing = generate_outlet_product_listing(
            df=processed_df,
            outlet="Warehouse",
            item_col=item_col,
            qty_col=qty_col,
            sku_col=sku_col,
            outlet_col=args.target_col,
        )

        if not wh_listing.empty:
            wh_path = input_path.parent / f"{input_path.stem}_warehouse_product_listing.xlsx"
            wh_tot_units = int(wh_listing[qty_col].sum())
            print("\n" + "-" * 60)
            print(f"  WAREHOUSE PRODUCT LISTING (PICKING LIST): {wh_tot_units} Total Units across {len(wh_listing)} SKUs")
            print("-" * 60)
            for idx, r in wh_listing.head(10).iterrows():
                sku_str = f" [{r[sku_col]}]" if sku_col and pd.notna(r.get(sku_col)) else ""
                print(f"  {r[qty_col]:>2}x {r[item_col]}{sku_str}")
            if len(wh_listing) > 10:
                print(f"  ... and {len(wh_listing) - 10} more SKUs.")

            wh_listing.to_excel(wh_path, index=False, engine="openpyxl")
            print(f"\nSaved Warehouse Product Listing to: {wh_path}")

    # Generate Pathao Bulk Upload Consignments
    try:
        pathao_df = generate_pathao_bulk_consignments(
            df=processed_df,
            order_col=args.order_col,
            sip_col=args.sip_col,
            target_col=args.target_col,
        )
        if not pathao_df.empty:
            pathao_path = input_path.parent / f"{input_path.stem}_pathao_bulk.xlsx"
            pathao_df.to_excel(pathao_path, index=False, engine="openpyxl")
            tot_cod = int(pd.to_numeric(pathao_df["AmountToCollect(*)"], errors="coerce").fillna(0).sum())
            print("\n" + "-" * 60)
            print(f"  PATHAO BULK CONSIGNMENTS: {len(pathao_df)} Total Consignments | Total COD: Tk {tot_cod:,}")
            print("-" * 60)
            split_p = pathao_df[pathao_df["SpecialInstruction"].str.contains("Split Part", na=False)]
            if not split_p.empty:
                print("  Split Consignments Created:")
                for _, r in split_p.iterrows():
                    print(f"    * ID: {r['MerchantOrderId']:<12} | COD: Tk {r['AmountToCollect(*)']:>5} | Outlet: {r['WarehouseOutlet']} ({r['ItemQuantity']} items)")
            print(f"\nSaved Pathao Bulk Upload to: {pathao_path}")
    except Exception as e:
        print(f"Note: Pathao bulk generation skipped: {e}")

    print("\n[SUCCESS] Processing completed successfully.\n")


if __name__ == "__main__":
    main()
