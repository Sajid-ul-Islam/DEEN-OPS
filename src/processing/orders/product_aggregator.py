"""Product listing aggregation logic for DEEN-OPS.

Handles grouping orders by product item name and SKU variant for export and listing.
"""

from __future__ import annotations

import pandas as pd


def aggregate_product_listing(
    df: pd.DataFrame,
    item_col: str,
    qty_col: str,
    sku_col: str | None = None,
) -> pd.DataFrame:
    """Aggregate orders by item name and optionally SKU for product listing export.

    Sorts products first item-wise (case-insensitive alphabetical ascending),
    then SKU-wise (case-insensitive alphabetical ascending) so that variants of
    each product stay strictly grouped together in the export file.
    """
    if df is None or df.empty or item_col not in df.columns:
        return pd.DataFrame()

    group_cols = [item_col]
    use_sku = bool(sku_col and sku_col != "None" and sku_col in df.columns)
    if use_sku:
        group_cols.append(sku_col)

    df_copy = df.copy()
    df_copy[qty_col] = pd.to_numeric(
        df_copy[qty_col].astype(str).str.replace(r"[^\d.-]", "", regex=True),
        errors="coerce",
    ).fillna(1)

    merged = df_copy.groupby(group_cols, as_index=False)[qty_col].sum()

    sort_cols = [item_col]
    if use_sku:
        sort_cols.append(sku_col)

    merged = merged.sort_values(
        by=sort_cols,
        ascending=True,
        key=lambda col: col.astype(str).str.lower(),
        na_position="last",
    ).reset_index(drop=True)

    return merged
