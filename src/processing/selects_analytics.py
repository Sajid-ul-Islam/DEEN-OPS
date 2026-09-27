"""DEEN Selects vs Regular Collection Sales & Category Analytics Processor.

Provides classification rules and aggregation analytics to compare sales performance,
category distribution, and top product metrics between the premium 'DEEN Selects' line
and the core 'DEEN Regular' line.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import pandas as pd

SELECTS_LABEL = "DEEN Selects"
REGULAR_LABEL = "DEEN Regular"

# Patterns to detect DEEN Selects collection across product names, categories, or SKUs
_SELECTS_PATTERN = re.compile(r"\b(selects?|deen\s*selects?)\b", re.IGNORECASE)
_SELECTS_SKU_PREFIX = re.compile(r"^(DS|SEL)[-_0-9]", re.IGNORECASE)

# Brands and product lines categorized under WooCommerce Category ID 1281 ('DEEN SELECT')
_SELECTS_BRANDS = [
    "pull & bear",
    "pull and bear",
    "springfield",
    "calvin klein",
    "levi's",
    "levis",
    "lee workwear",
    "lee carpenter",
    "allen solly",
    "sorbino",
    "lefties",
    "dragon ball z",
]


@lru_cache(maxsize=4096)
def classify_product_line(
    name: str = "",
    sku: str = "",
    category: str = "",
) -> str:
    """Classify a product as 'DEEN Selects' or 'DEEN Regular' based on WooCommerce API standards.

    Args:
        name: Product name or item name string.
        sku: Product SKU identifier.
        category: Category or tag name.

    Returns:
        'DEEN Selects' if the item matches select collection patterns, else 'DEEN Regular'.
    """
    s_name = str(name).strip().lower() if name else ""
    s_sku = str(sku).strip().lower() if sku else ""
    s_cat = str(category).strip().lower() if category else ""

    # Direct select keyword or category match
    if _SELECTS_PATTERN.search(s_name) or _SELECTS_PATTERN.search(s_cat):
        return SELECTS_LABEL

    # SKU prefix match (e.g. DS-104-...)
    if _SELECTS_PATTERN.search(s_sku) or _SELECTS_SKU_PREFIX.match(s_sku):
        return SELECTS_LABEL

    # WooCommerce DEEN SELECT brand line match
    if any(b in s_name for b in _SELECTS_BRANDS):
        return SELECTS_LABEL

    return REGULAR_LABEL


def compute_selects_regular_analytics(
    df: pd.DataFrame,
    cat_col: str = "Category",
    subcat_col: str = "Sub-Category",
) -> dict[str, Any]:
    """Compute comprehensive sales and category analytics for DEEN Selects vs Regular.

    Args:
        df: Granular orders DataFrame with line items.
        cat_col: Column name for Category.
        subcat_col: Column name for Sub-Category.

    Returns:
        Dict containing overview metrics, category breakdowns, comparison matrix,
        and top products for both DEEN Selects and DEEN Regular.
    """
    empty_res: dict[str, Any] = {
        "summary": {
            "total_revenue": 0.0,
            "total_qty": 0,
            "total_orders": 0,
            "selects_rev": 0.0,
            "selects_qty": 0,
            "selects_orders": 0,
            "selects_rev_share": 0.0,
            "selects_qty_share": 0.0,
            "selects_avg_price": 0.0,
            "regular_rev": 0.0,
            "regular_qty": 0,
            "regular_orders": 0,
            "regular_rev_share": 0.0,
            "regular_qty_share": 0.0,
            "regular_avg_price": 0.0,
        },
        "selects_df": pd.DataFrame(),
        "regular_df": pd.DataFrame(),
        "selects_cat_summary": pd.DataFrame(),
        "regular_cat_summary": pd.DataFrame(),
        "comparison_matrix": pd.DataFrame(),
        "selects_top_products": pd.DataFrame(),
        "regular_top_products": pd.DataFrame(),
        "classified_df": pd.DataFrame(),
    }

    if df is None or df.empty:
        return empty_res

    work_df = df.copy()

    # Detect name, sku, rev, qty, order_id columns defensively
    name_col = (
        "Product Name"
        if "Product Name" in work_df.columns
        else ("Item Name" if "Item Name" in work_df.columns else None)
    )
    sku_col = "SKU" if "SKU" in work_df.columns else None
    amt_col = (
        "Total Amount"
        if "Total Amount" in work_df.columns
        else ("Gross Amount" if "Gross Amount" in work_df.columns else "Item Cost")
    )
    qty_col = "Quantity" if "Quantity" in work_df.columns else None
    oid_col = "Order ID" if "Order ID" in work_df.columns else None

    if not name_col or not qty_col or not amt_col:
        return empty_res

    # Ensure numeric columns
    work_df["_amt"] = pd.to_numeric(work_df[amt_col], errors="coerce").fillna(0.0)
    work_df["_qty"] = pd.to_numeric(work_df[qty_col], errors="coerce").fillna(0.0)

    # Apply product line classification
    if "Product Line" not in work_df.columns:
        cat_series = work_df[cat_col] if cat_col in work_df.columns else ""
        sku_series = work_df[sku_col] if sku_col else ""
        work_df["Product Line"] = [
            classify_product_line(str(n), str(s), str(c))
            for n, s, c in zip(work_df[name_col], sku_series, cat_series)
        ]

    # Partition datasets
    sel_df = work_df[work_df["Product Line"] == SELECTS_LABEL].copy()
    reg_df = work_df[work_df["Product Line"] == REGULAR_LABEL].copy()

    tot_rev = float(work_df["_amt"].sum())
    tot_qty = int(work_df["_qty"].sum())
    tot_ords = (
        len(work_df[oid_col].dropna().unique())
        if oid_col and oid_col in work_df.columns
        else len(work_df)
    )

    sel_rev = float(sel_df["_amt"].sum()) if not sel_df.empty else 0.0
    sel_qty = int(sel_df["_qty"].sum()) if not sel_df.empty else 0
    sel_ords = (
        len(sel_df[oid_col].dropna().unique())
        if oid_col and oid_col in sel_df.columns and not sel_df.empty
        else (len(sel_df) if not sel_df.empty else 0)
    )

    reg_rev = float(reg_df["_amt"].sum()) if not reg_df.empty else 0.0
    reg_qty = int(reg_df["_qty"].sum()) if not reg_df.empty else 0
    reg_ords = (
        len(reg_df[oid_col].dropna().unique())
        if oid_col and oid_col in reg_df.columns and not reg_df.empty
        else (len(reg_df) if not reg_df.empty else 0)
    )

    sel_rev_share = (sel_rev / tot_rev * 100.0) if tot_rev > 0 else 0.0
    sel_qty_share = (sel_qty / tot_qty * 100.0) if tot_qty > 0 else 0.0
    sel_avg_price = (sel_rev / sel_qty) if sel_qty > 0 else 0.0

    reg_rev_share = (reg_rev / tot_rev * 100.0) if tot_rev > 0 else 0.0
    reg_qty_share = (reg_qty / tot_qty * 100.0) if tot_qty > 0 else 0.0
    reg_avg_price = (reg_rev / reg_qty) if reg_qty > 0 else 0.0

    summary = {
        "total_revenue": tot_rev,
        "total_qty": tot_qty,
        "total_orders": tot_ords,
        "selects_rev": sel_rev,
        "selects_qty": sel_qty,
        "selects_orders": sel_ords,
        "selects_rev_share": sel_rev_share,
        "selects_qty_share": sel_qty_share,
        "selects_avg_price": sel_avg_price,
        "regular_rev": reg_rev,
        "regular_qty": reg_qty,
        "regular_orders": reg_ords,
        "regular_rev_share": reg_rev_share,
        "regular_qty_share": reg_qty_share,
        "regular_avg_price": reg_avg_price,
    }

    # Helper function to compute category breakdown
    def _build_cat_summary(sub_df: pd.DataFrame, sub_total_rev: float) -> pd.DataFrame:
        if sub_df.empty or cat_col not in sub_df.columns:
            return pd.DataFrame(
                columns=[
                    "Category",
                    "Total Amount",
                    "Total Qty",
                    "Order Count",
                    "Share %",
                    "Avg Price",
                    "Top Product",
                ]
            )

        records = []
        for cat, group in sub_df.groupby(cat_col):
            cat_amt = float(group["_amt"].sum())
            cat_q = int(group["_qty"].sum())
            cat_o = (
                len(group[oid_col].dropna().unique())
                if oid_col and oid_col in group.columns
                else len(group)
            )
            share_pct = (cat_amt / sub_total_rev * 100.0) if sub_total_rev > 0 else 0.0
            avg_p = (cat_amt / cat_q) if cat_q > 0 else 0.0

            # Find top selling product in this category
            top_prod_name = "N/A"
            if name_col in group.columns and not group.empty:
                prod_agg = (
                    group.groupby(name_col)["_amt"].sum().sort_values(ascending=False)
                )
                if not prod_agg.empty:
                    top_prod_name = str(prod_agg.index[0])

            records.append(
                {
                    "Category": str(cat),
                    "Total Amount": cat_amt,
                    "Total Qty": cat_q,
                    "Order Count": cat_o,
                    "Share %": round(share_pct, 1),
                    "Avg Price": round(avg_p, 1),
                    "Top Product": top_prod_name,
                }
            )

        res_df = pd.DataFrame(records)
        if not res_df.empty:
            res_df = res_df.sort_values("Total Amount", ascending=False).reset_index(
                drop=True
            )
        return res_df

    sel_cat_sum = _build_cat_summary(sel_df, sel_rev)
    reg_cat_sum = _build_cat_summary(reg_df, reg_rev)

    # Build Comparative Matrix
    comp_matrix = pd.DataFrame()
    all_cats = set()
    if not sel_cat_sum.empty:
        all_cats.update(sel_cat_sum["Category"].tolist())
    if not reg_cat_sum.empty:
        all_cats.update(reg_cat_sum["Category"].tolist())

    if all_cats:
        sel_lookup = (
            sel_cat_sum.set_index("Category").to_dict(orient="index")
            if not sel_cat_sum.empty
            else {}
        )
        reg_lookup = (
            reg_cat_sum.set_index("Category").to_dict(orient="index")
            if not reg_cat_sum.empty
            else {}
        )

        matrix_rows = []
        for cat in all_cats:
            s_data = sel_lookup.get(cat, {})
            r_data = reg_lookup.get(cat, {})

            s_rev = s_data.get("Total Amount", 0.0)
            s_q = s_data.get("Total Qty", 0)
            r_rev = r_data.get("Total Amount", 0.0)
            r_q = r_data.get("Total Qty", 0)

            c_tot_rev = s_rev + r_rev
            c_tot_q = s_q + r_q
            s_share = (s_rev / c_tot_rev * 100.0) if c_tot_rev > 0 else 0.0

            matrix_rows.append(
                {
                    "Category": cat,
                    "Selects Revenue": s_rev,
                    "Selects Qty": s_q,
                    "Regular Revenue": r_rev,
                    "Regular Qty": r_q,
                    "Total Revenue": c_tot_rev,
                    "Total Qty": c_tot_q,
                    "Selects Rev %": round(s_share, 1),
                }
            )
        comp_matrix = (
            pd.DataFrame(matrix_rows)
            .sort_values("Total Revenue", ascending=False)
            .reset_index(drop=True)
        )

    # Top products breakdown
    def _build_top_products(sub_df: pd.DataFrame) -> pd.DataFrame:
        if sub_df.empty or name_col not in sub_df.columns:
            return pd.DataFrame(
                columns=[
                    "Product Name",
                    "Category",
                    "Total Qty",
                    "Total Amount",
                    "Avg Price",
                ]
            )

        agg_cols = {"_qty": "sum", "_amt": "sum"}
        grp_keys = [name_col]
        if cat_col in sub_df.columns:
            grp_keys.append(cat_col)
        if sku_col and sku_col in sub_df.columns:
            grp_keys.append(sku_col)

        top_df = sub_df.groupby(grp_keys, as_index=False).agg(agg_cols)
        top_df = top_df.rename(columns={"_qty": "Total Qty", "_amt": "Total Amount"})
        top_df["Avg Price"] = (top_df["Total Amount"] / top_df["Total Qty"]).round(1)
        top_df = top_df.sort_values("Total Amount", ascending=False).reset_index(
            drop=True
        )
        return top_df

    sel_top = _build_top_products(sel_df)
    reg_top = _build_top_products(reg_df)

    return {
        "summary": summary,
        "selects_df": sel_df,
        "regular_df": reg_df,
        "selects_cat_summary": sel_cat_sum,
        "regular_cat_summary": reg_cat_sum,
        "comparison_matrix": comp_matrix,
        "selects_top_products": sel_top,
        "regular_top_products": reg_top,
        "classified_df": work_df,
    }
