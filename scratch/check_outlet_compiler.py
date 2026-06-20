import os
import io
import pandas as pd
from src.inventory import core as inv_core
from src.processing.stock_categorization import map_to_csv_category
from src.utils.snapshots import load_stock_snapshot
from src.config.constants import OFFER_KEYWORDS
from src.utils.product import get_base_product_name

# Mock streamlit session state
class SessionState(dict):
    pass

import streamlit as st
st.session_state = SessionState()

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

ecom_df = pd.read_csv("resources/stock_snapshot.csv")
ecom_df["Stock"] = pd.to_numeric(ecom_df["Stock"], errors="coerce").fillna(0).astype(float)
if ecom_df is not None:
    loc_files["Ecom"] = ecom_df
    st.session_state["wc_stock_df"] = ecom_df

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

all_ordered = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet"]
active_locs = [loc for loc in all_ordered if loc in loc_files]

cat_aggregates = {}
for k, locs in inv_map.items():
    if str(k).upper().startswith("SKU:"): continue
    if k in sku_to_title_size: continue
    if any(kw in str(k).lower() for kw in OFFER_KEYWORDS): continue
    
    display_cat = None
    resolved_via_wc = False
    raw_sku = title_size_to_sku.get(k)
    if raw_sku:
        norm_sku = inv_core.normalize_sku(raw_sku)
        wc_name = wc_sku_to_name.get(norm_sku)
        if wc_name:
            if any(kw in wc_name.lower() for kw in OFFER_KEYWORDS): continue
            display_cat = map_to_csv_category(wc_name)
            resolved_via_wc = True
    
    if not display_cat:
        display_cat = map_to_csv_category(k)
    
    if display_cat not in cat_aggregates:
        cat_aggregates[display_cat] = {loc: 0 for loc in active_locs}
        cat_aggregates[display_cat]["Total Outlet Stock"] = 0
        
    for loc in active_locs:
        qty = locs.get(loc, 0)
        cat_aggregates[display_cat][loc] += qty
        if loc in ["Mirpur", "Wari", "Cumilla", "Sylhet"]:
            cat_aggregates[display_cat]["Total Outlet Stock"] += qty

rows = []
for cat_name, counts in cat_aggregates.items():
    row = {"Products Name": cat_name}
    for loc in active_locs:
        row[loc] = counts.get(loc, 0)
    row["Total Outlet Stock"] = counts.get("Total Outlet Stock", 0)
    rows.append(row)

out_df = pd.DataFrame(rows).sort_values("Products Name")
print(out_df.to_string(index=False))
