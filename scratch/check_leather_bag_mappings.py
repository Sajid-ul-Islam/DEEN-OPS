import os
import io
import pandas as pd
from src.inventory import core as inv_core
from src.processing.stock_categorization import map_to_csv_category
from src.utils.snapshots import load_stock_snapshot

# Load files
default_files = {
    "Mirpur": "src/inventory/Mir.xlsx",
    "Wari": "src/inventory/War.xlsx",
    "Cumilla": "src/inventory/Cum.xlsx",
    "Sylhet": "src/inventory/Syl.xlsx"
}

loc_files = {}
for loc, path in default_files.items():
    if os.path.exists(path):
        with open(path, "rb") as f:
            loc_files[loc] = io.BytesIO(f.read())

ecom_df = load_stock_snapshot()
if ecom_df is not None:
    loc_files["Ecom"] = ecom_df

# Run compile logic
inv_map, warnings, enriched_dfs, sku_to_title_size = inv_core.load_inventory_from_uploads(loc_files)

# Build Title-Size to SKU lookup from enriched dataframes
title_size_to_sku = {}
for loc, df in enriched_dfs.items():
    _, _, _, sku_col = inv_core.identify_columns(df)
    if sku_col and sku_col in df.columns:
        for _, row in df.iterrows():
            ts_val = str(row.get("Title - Size", "")).strip().casefold()
            sku_val = str(row.get(sku_col, "")).strip()
            if ts_val and sku_val and sku_val not in ["nan", "0", "N/A", "N/A"]:
                title_size_to_sku[ts_val] = sku_val

# Build WooCommerce SKU -> Product Name map
wc_sku_to_name = {}
wc_stock = ecom_df
if wc_stock is not None and "SKU" in wc_stock.columns and ("Product" in wc_stock.columns or "Product Name" in wc_stock.columns):
    name_col = "Product" if "Product" in wc_stock.columns else "Product Name"
    for _, row in wc_stock.iterrows():
        sku_val = inv_core.normalize_sku(row.get("SKU", ""))
        prod_name = str(row.get(name_col, "")).strip()
        if sku_val and sku_val != "0" and prod_name:
            wc_sku_to_name[sku_val] = prod_name

# Print all inv_map keys containing bag
for k, locs in inv_map.items():
    if "bag" in str(k).lower():
        print(f"Key: {k}, SKU: {title_size_to_sku.get(k)}, Ecom stock: {locs.get('Ecom', 0)}, Outlet stock: {locs.get('Mirpur', 0)}")
