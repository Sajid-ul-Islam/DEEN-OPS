"""Multi-outlet and warehouse stock processing, filtering, and export analytics.

Provides parsing, pivoting, filtering, health classification, KPI aggregation,
and multi-sheet Excel generation for catalog stock across Central Warehouse and
retail outlets (Mirpur, Wari, Cumilla, Sylhet).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from src.processing.categorization import get_category_for_sales
from src.processing.sip_outlet_processor import (
    normalize_outlet_name,
    parse_stock_report,
    pivot_stock_report,
)
from src.utils.logging import log_system_event

STOCK_CACHE_FILE = Path("resources") / "stock_inventory.parquet"
LAST_STOCK_CSV = Path("resources") / "last_stock.csv"
STOCK_SNAPSHOT_CSV = Path("resources") / "stock_snapshot.csv"

CANONICAL_OUTLETS = ["Warehouse", "Mirpur", "Wari", "Cumilla", "Sylhet"]


def load_cached_stock_inventory() -> Optional[pd.DataFrame]:
    """Load persisted stock inventory DataFrame from disk if available."""
    if STOCK_CACHE_FILE.exists():
        try:
            return pd.read_parquet(STOCK_CACHE_FILE)
        except Exception as e:
            log_system_event("STOCK_CACHE_LOAD_ERROR", f"Parquet read failed: {e}")

    # Fallback to last_stock.csv baseline
    if LAST_STOCK_CSV.exists():
        try:
            df = pd.read_csv(LAST_STOCK_CSV)
            return build_stock_pivot_from_flat(df)
        except Exception as e:
            log_system_event("LAST_STOCK_CSV_LOAD_ERROR", str(e))

    if STOCK_SNAPSHOT_CSV.exists():
        try:
            df = pd.read_csv(STOCK_SNAPSHOT_CSV)
            return build_stock_pivot_from_flat(df)
        except Exception as e:
            log_system_event("STOCK_SNAPSHOT_CSV_LOAD_ERROR", str(e))

    return None


def save_cached_stock_inventory(pivot_df: pd.DataFrame) -> bool:
    """Persist stock inventory DataFrame to parquet on disk."""
    if pivot_df is None or pivot_df.empty:
        return False
    try:
        STOCK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        pivot_df.to_parquet(STOCK_CACHE_FILE, index=False)
        return True
    except Exception as e:
        log_system_event("STOCK_CACHE_SAVE_ERROR", str(e))
        return False


def build_stock_pivot_from_flat(df: pd.DataFrame) -> pd.DataFrame:
    """Build a normalized multi-outlet stock pivot from a flat CSV or Smart Inventory export."""
    if df is None or df.empty:
        return pd.DataFrame()

    work = df.copy()
    work.columns = [str(c).strip() for c in work.columns]

    # If it's already a pivoted layout with canonical outlet columns
    if (
        "Product" in work.columns
        and "Warehouse" in work.columns
        and "Total" in work.columns
    ):
        return ensure_stock_pivot_structure(work)

    # Check if it has 'Outlet' column (Smart Inventory layout)
    outlet_col = next(
        (
            c
            for c in work.columns
            if c.lower() in ("outlet", "outlet name", "outlet slug", "location")
        ),
        None,
    )
    if outlet_col:
        try:
            parsed = parse_stock_report(work)
            pivoted = pivot_stock_report(parsed)
            return ensure_stock_pivot_structure(pivoted)
        except Exception:
            pass

    # If it's a flat catalog export (Product, SKU, Stock, Price, Size, Category)
    prod_col = next(
        (
            c
            for c in work.columns
            if c.lower() in ("product", "product name", "item name", "title")
        ),
        "Product",
    )
    sku_col = next((c for c in work.columns if c.lower() in ("sku", "item sku")), "SKU")
    stock_col = next(
        (
            c
            for c in work.columns
            if c.lower() in ("stock", "stock qty", "quantity", "qty")
        ),
        "Stock",
    )
    size_col = next(
        (c for c in work.columns if c.lower() in ("size", "variation")), "Size"
    )
    cat_col = next(
        (c for c in work.columns if c.lower() in ("category", "categories")), "Category"
    )

    work["Product"] = (
        work[prod_col].fillna("").astype(str).str.strip()
        if prod_col in work.columns
        else "Product"
    )
    work["SKU"] = (
        work[sku_col].fillna("").astype(str).str.strip()
        if sku_col in work.columns
        else ""
    )
    work["Size"] = (
        work[size_col].fillna("").astype(str).str.strip()
        if size_col in work.columns
        else ""
    )
    work["Size"] = (
        work["Size"]
        .str.replace(r"^\s*size\s*:\s*", "", regex=True, case=False)
        .str.strip()
    )
    work.loc[work["Size"].str.lower().isin(["nan", "none"]), "Size"] = ""

    stock_num = (
        pd.to_numeric(
            work[stock_col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
        if stock_col in work.columns
        else 0
    )

    pivot = pd.DataFrame(
        {
            "Product": work["Product"],
            "Size": work["Size"],
            "SKU": work["SKU"],
            "Warehouse": stock_num,
            "Mirpur": 0,
            "Wari": 0,
            "Cumilla": 0,
            "Sylhet": 0,
            "Total": stock_num,
        }
    )

    if cat_col in work.columns:
        pivot["Category"] = work[cat_col].fillna("").astype(str).str.strip()
    else:
        pivot["Category"] = pivot["Product"].map(get_category_for_sales)

    return ensure_stock_pivot_structure(pivot)


def ensure_stock_pivot_structure(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee standard columns, numeric types, and total stock calculation."""
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    if "Product" not in out.columns:
        out["Product"] = "Unknown Product"
    if "Size" not in out.columns:
        out["Size"] = ""
    if "SKU" not in out.columns:
        out["SKU"] = ""
    if "Category" not in out.columns:
        out["Category"] = out["Product"].map(get_category_for_sales)

    # Ensure canonical outlet columns exist
    for o in CANONICAL_OUTLETS:
        if o not in out.columns:
            out[o] = 0
        else:
            out[o] = pd.to_numeric(out[o], errors="coerce").fillna(0).astype(int)

    # Identify all outlet columns (canonical + any custom extra outlets)
    index_cols = ["Product", "Size", "SKU", "Category"]
    outlet_cols = [
        c for c in out.columns if c not in index_cols and c != "Total" and c != "Status"
    ]

    for col in outlet_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)

    out["Total"] = out[outlet_cols].sum(axis=1)

    # Status column
    def _calc_status(tot: int) -> str:
        if tot <= 0:
            return "Out of Stock"
        if tot <= 5:
            return "Low Stock"
        return "In Stock"

    out["Status"] = out["Total"].map(_calc_status)

    col_order = (
        ["Product", "Size", "SKU", "Category"] + outlet_cols + ["Total", "Status"]
    )
    final_cols = [c for c in col_order if c in out.columns]
    return out[final_cols].reset_index(drop=True)


def compute_stock_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute high-level summary KPIs from a stock inventory pivot."""
    if df is None or df.empty:
        return {
            "total_skus": 0,
            "total_stock": 0,
            "warehouse_stock": 0,
            "outlets_stock": 0,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "outlet_breakdown": {},
        }

    total_skus = len(df)
    total_stock = int(df["Total"].sum()) if "Total" in df.columns else 0
    warehouse_stock = int(df["Warehouse"].sum()) if "Warehouse" in df.columns else 0

    index_cols = {"Product", "Size", "SKU", "Category", "Total", "Status"}
    outlet_cols = [c for c in df.columns if c not in index_cols and c != "Warehouse"]
    outlets_stock = int(df[outlet_cols].sum().sum()) if outlet_cols else 0

    outlet_breakdown = {}
    if "Warehouse" in df.columns:
        outlet_breakdown["Warehouse"] = warehouse_stock
    for col in outlet_cols:
        outlet_breakdown[col] = int(df[col].sum())

    low_stock_count = (
        int((df["Total"].between(1, 5)).sum()) if "Total" in df.columns else 0
    )
    out_of_stock_count = int((df["Total"] <= 0).sum()) if "Total" in df.columns else 0

    return {
        "total_skus": total_skus,
        "total_stock": total_stock,
        "warehouse_stock": warehouse_stock,
        "outlets_stock": outlets_stock,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "outlet_breakdown": outlet_breakdown,
    }


def filter_stock_inventory(
    df: pd.DataFrame,
    outlet: str = "All Outlets",
    stock_status: str = "All",
    category: str = "All Categories",
    search_query: str = "",
) -> pd.DataFrame:
    """Filter the stock inventory pivot by outlet, health status, category, and keyword search."""
    if df is None or df.empty:
        return pd.DataFrame()

    filtered = df.copy()

    # 1. Category Filter
    if category and category != "All Categories" and "Category" in filtered.columns:
        filtered = filtered[filtered["Category"].astype(str) == str(category)]

    # 2. Outlet Stock Filtering
    if outlet and outlet != "All Outlets":
        canonical_target = normalize_outlet_name(outlet)
        matched_col = next(
            (c for c in filtered.columns if c.lower() == canonical_target.lower()), None
        )
        if matched_col:
            if stock_status == "In Stock":
                filtered = filtered[filtered[matched_col] > 0]
            elif stock_status == "Low Stock":
                filtered = filtered[filtered[matched_col].between(1, 5)]
            elif stock_status == "Out of Stock":
                filtered = filtered[filtered[matched_col] <= 0]
            elif stock_status == "Replenish Needed":
                # In stock at central Warehouse (> 0) but stockout (<= 0) at this specific outlet
                if "Warehouse" in filtered.columns and matched_col != "Warehouse":
                    filtered = filtered[
                        (filtered["Warehouse"] > 0) & (filtered[matched_col] <= 0)
                    ]
    else:
        # Stock Status Filter applied to Total
        if stock_status == "In Stock":
            filtered = filtered[filtered["Total"] > 0]
        elif stock_status == "Low Stock":
            filtered = filtered[filtered["Total"].between(1, 5)]
        elif stock_status == "Out of Stock":
            filtered = filtered[filtered["Total"] <= 0]
        elif stock_status == "Replenish Needed":
            # In stock at Warehouse, but 0 in at least one retail outlet
            index_cols = {
                "Product",
                "Size",
                "SKU",
                "Category",
                "Total",
                "Status",
                "Warehouse",
            }
            retail_cols = [c for c in filtered.columns if c not in index_cols]
            if retail_cols and "Warehouse" in filtered.columns:
                has_outlet_stockout = (filtered[retail_cols] <= 0).any(axis=1)
                filtered = filtered[(filtered["Warehouse"] > 0) & has_outlet_stockout]

    # 3. Text Search Query
    if search_query and search_query.strip():
        q = str(search_query).strip().lower()
        search_cols = [
            c for c in ["Product", "SKU", "Size", "Category"] if c in filtered.columns
        ]
        mask = pd.Series(False, index=filtered.index)
        for col in search_cols:
            mask = mask | filtered[col].astype(str).str.lower().str.contains(
                q, regex=False, na=False
            )
        filtered = filtered[mask]

    return filtered.reset_index(drop=True)
