"""Aggregators and dispatch metrics calculation for DEEN-OPS order processing.

Handles granular data normalization, Polars-accelerated multi-level order aggregations,
and shift dispatch/courier metrics calculation.
"""

from __future__ import annotations

import pandas as pd
import polars as pl

from src.config.constants import ACTIVE_STATUSES, SHIPPED_STATUSES
from src.processing.categorization import (
    get_category_for_sales,
    get_sub_category_for_sales,
)
from src.processing.column_detection import (
    ORDER_ID_COL_CANDIDATES,
    find_columns,
    pick_column,
    scrub_raw_dataframe,
)
from src.processing.orders.date_utils import safe_coerce_datetime_naive
from src.processing.orders.status_filters import _detect_exchange_mask
from src.utils.logging import log_system_event
from src.utils.product import (
    get_base_product_name,
    get_size_from_name,
    is_bundle_or_combo,
)


def prepare_granular_data(
    df: pd.DataFrame, selected_cols: dict[str, str]
) -> tuple[pd.DataFrame, str]:
    """Sanitizes and prepares granular columns with unified internal names."""
    try:
        df = df.copy()
        df = scrub_raw_dataframe(df)

        if df.empty:
            return df, ""

        # Mapping to Standard Names for easier internal logic
        df["Product Name"] = (
            df[selected_cols["name"]].fillna("Unknown Product").astype(str)
        )
        df = df[~df["Product Name"].str.contains("Choose Any", case=False, na=False)]

        df["Item Cost"] = pd.to_numeric(
            df[selected_cols["cost"]]
            .astype(str)
            .str.replace(r"[^\d.]", "", regex=True),
            errors="coerce",
        ).fillna(0)
        df["Quantity"] = pd.to_numeric(
            df[selected_cols["qty"]].astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce",
        ).fillna(0)

        # Standardized SKU support
        sku_col = None
        if "sku" in selected_cols and selected_cols["sku"] in df.columns:
            sku_col = selected_cols["sku"]
        elif "SKU" in df.columns:
            sku_col = "SKU"
        else:
            sku_col = pick_column(df, ["SKU", "sku", "Item SKU", "Product SKU"])

        if sku_col and sku_col in df.columns:
            df["SKU"] = df[sku_col].fillna("N/A").astype(str)
        else:
            df["SKU"] = "N/A"

        # Standardized Order ID support
        if "Order ID" not in df.columns:
            cand = (
                selected_cols.get("order_id")
                if "order_id" in selected_cols
                and selected_cols["order_id"] in df.columns
                else pick_column(df, ORDER_ID_COL_CANDIDATES)
            )
            if cand and cand in df.columns:
                df["Order ID"] = df[cand]

        timeframe_suffix = ""
        if "date" in selected_cols and selected_cols["date"] in df.columns:
            try:
                df["Date"] = safe_coerce_datetime_naive(df[selected_cols["date"]])
                dates_valid = df["Date"].dropna()
                if not dates_valid.empty:
                    if dates_valid.dt.to_period("M").nunique() == 1:
                        timeframe_suffix = dates_valid.iloc[0].strftime("%B_%Y")
                    else:
                        timeframe_suffix = (
                            f"{dates_valid.min().strftime('%d%b')}_to_"
                            f"{dates_valid.max().strftime('%d%b_%y')}"
                        )
                else:
                    log_system_event(
                        "DATE_PARSE_WARN",
                        "No valid dates parsed from date column; "
                        "proceeding without date filtering.",
                    )
            except Exception as date_err:
                log_system_event(
                    "DATE_PARSE_ERROR",
                    f"Date parsing failed: {date_err}; proceeding without date column.",
                )
                non_null = df[selected_cols["date"]].dropna()
                val = str(non_null.iloc[0]) if not non_null.empty else ""
                timeframe_suffix = val.replace("/", "-").replace(" ", "_")[:20]

        if (df["Quantity"] < 0).any():
            log_system_event("DATA_ISSUE", "Found negative quantities, converted to 0.")
            df.loc[df["Quantity"] < 0, "Quantity"] = 0

        # Optimized Categorization & Extraction (Vectorized Maps)
        unique_names = df["Product Name"].unique()
        name_cat_map = {}
        name_subcat_map = {}
        name_size_map = {}
        name_clean_map = {}
        name_bundle_map = {}

        for name in unique_names:
            cat = get_category_for_sales(name)
            name_cat_map[name] = cat
            name_subcat_map[name] = get_sub_category_for_sales(name, cat)
            name_size_map[name] = get_size_from_name(name)
            name_clean_map[name] = get_base_product_name(name)
            name_bundle_map[name] = is_bundle_or_combo(name, "", cat)

        df["Category"] = df["Product Name"].map(name_cat_map)
        df["Sub-Category"] = df["Product Name"].map(name_subcat_map)
        df["Size"] = df["Product Name"].map(name_size_map)
        df["Clean_Product"] = df["Product Name"].map(name_clean_map)
        df["Filter_Identity"] = (
            df["Clean_Product"].astype(str) + " [" + df["SKU"].astype(str) + "]"
        )
        df["Is_Bundle_Combo"] = df["Product Name"].map(name_bundle_map)

        if "Subtotal Cost" in df.columns:
            df["Subtotal Cost"] = pd.to_numeric(
                df["Subtotal Cost"].astype(str).str.replace(r"[^\d.]", "", regex=True),
                errors="coerce",
            ).fillna(df["Item Cost"])
        else:
            df["Subtotal Cost"] = df["Item Cost"]

        df["Gross Amount"] = df["Subtotal Cost"] * df["Quantity"]
        df["Total Amount"] = df["Item Cost"] * df["Quantity"]

        if "Cashback Discount" in df.columns:
            df["Cashback Discount"] = pd.to_numeric(
                df["Cashback Discount"]
                .astype(str)
                .str.replace(r"[^\d.]", "", regex=True),
                errors="coerce",
            ).fillna(0)
        else:
            df["Cashback Discount"] = (df["Gross Amount"] - df["Total Amount"]).clip(
                lower=0
            )

        # Handle negative fee lines (if negative sign '-' is present, it is a fee discount/cashback)
        fee_cols = [
            c
            for c in df.columns
            if c.lower() in ["extra fee", "fee", "fees", "fee discount total"]
        ]
        for f_c in fee_cols:
            raw_fees = pd.to_numeric(
                df[f_c].astype(str).str.replace(r"[^\d.-]", "", regex=True),
                errors="coerce",
            ).fillna(0)
            neg_fees = raw_fees < 0
            if neg_fees.any():
                df.loc[neg_fees, "Cashback Discount"] = (
                    df.loc[neg_fees, "Cashback Discount"] + raw_fees[neg_fees].abs()
                )

        df["Net Amount"] = df["Total Amount"]

        # Ensure Order Status and other operational columns are present
        if "Order Status" not in df.columns:
            status_col = find_columns(df).get("status")
            if status_col:
                df["Order Status"] = (
                    df[status_col].fillna("completed").astype(str).str.lower()
                )
            else:
                df["Order Status"] = "completed"

        # Exclude pending payments, cancelled, and failed orders from all analytics
        df = df[
            ~df["Order Status"]
            .astype(str)
            .str.lower()
            .isin(
                [
                    "pending",
                    "pending payment",
                    "cancelled",
                    "failed",
                    "refunded",
                    "trash",
                ]
            )
        ]

        return df, timeframe_suffix
    except Exception as e:
        log_system_event("PREPARE_ERROR", str(e))
        return pd.DataFrame(), ""


def aggregate_data(
    df: pd.DataFrame, selected_cols: dict[str, str]
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, dict]:
    """Generates dashboard aggregates from granular standardized data using Polars."""
    if df is None or df.empty:
        return None, None, None, {}

    try:
        if "Category" not in df.columns:
            df, _ = prepare_granular_data(df, selected_cols)
            if df is None or df.empty or "Category" not in df.columns:
                return None, None, None, {}

        cols_to_fill = [
            pl.col(c).fill_nan(0).fill_null(0)
            for c in ["Quantity", "Total Amount"]
            if c in df.columns
        ]
        lazy_df = pl.from_pandas(df).lazy()
        if cols_to_fill:
            lazy_df = lazy_df.with_columns(cols_to_fill)

        # 1. Summary
        group_keys = ["Category"]
        if "Sub-Category" in df.columns:
            group_keys.append("Sub-Category")

        summary = (
            lazy_df.group_by(group_keys)
            .agg(
                [
                    pl.col("Quantity").sum().alias("Total Qty"),
                    pl.col("Total Amount").sum().alias("Total Amount"),
                ]
            )
            .collect()
            .to_pandas()
        )

        total_rev = summary["Total Amount"].sum()
        total_qty = summary["Total Qty"].sum()
        if total_rev > 0:
            summary["Revenue Share (%)"] = (
                summary["Total Amount"] / total_rev * 100
            ).round(2)
        if total_qty > 0:
            summary["Quantity Share (%)"] = (
                summary["Total Qty"] / total_qty * 100
            ).round(2)

        # 2. Drilldown
        drill_keys = group_keys + (["Item Cost"] if "Item Cost" in df.columns else [])
        drilldown = (
            lazy_df.group_by(drill_keys)
            .agg(
                [
                    pl.col("Quantity").sum().alias("Total Qty"),
                    pl.col("Total Amount").sum().alias("Total Amount"),
                ]
            )
            .collect()
            .to_pandas()
        )
        if "Sub-Category" in drilldown.columns and "Item Cost" in df.columns:
            drilldown.columns = [
                "Category",
                "Sub-Category",
                "Price (TK)",
                "Total Qty",
                "Total Amount",
            ]
        elif "Item Cost" in df.columns:
            drilldown.columns = ["Category", "Price (TK)", "Total Qty", "Total Amount"]

        # 3. Top Items
        top_aggs = [
            pl.col("Quantity").sum().alias("Total Qty"),
            pl.col("Total Amount").sum().alias("Total Amount"),
            pl.col("Category").first().alias("Category"),
        ]
        if "Clean_Product" in df.columns:
            top_aggs.append(pl.col("Clean_Product").first().alias("Clean_Product"))
        elif "Product Name" in df.columns:
            top_aggs.append(pl.col("Product Name").first().alias("Clean_Product"))

        if "Sub-Category" in df.columns:
            top_aggs.append(pl.col("Sub-Category").first().alias("Sub-Category"))

        group_by_cols = ["Product Name"] if "Product Name" in df.columns else []
        if "SKU" in df.columns:
            group_by_cols.append("SKU")

        if group_by_cols:
            top_items = (
                lazy_df.group_by(group_by_cols).agg(top_aggs).collect().to_pandas()
            )
            top_items = top_items.sort_values("Total Amount", ascending=False)
        else:
            top_items = pd.DataFrame()

        # 4. Basket Metrics
        basket_metrics = {
            "avg_basket_qty": 0,
            "avg_basket_value": 0,
            "total_orders": 0,
            "attachment_rate": 0,
        }
        group_cols = []
        if "order_id" in selected_cols and selected_cols["order_id"] in df.columns:
            group_cols.append(selected_cols["order_id"])
        elif "Order ID" in df.columns:
            group_cols.append("Order ID")
        else:
            cand = pick_column(df, ORDER_ID_COL_CANDIDATES)
            if cand and cand in df.columns:
                group_cols.append(cand)

        # Count unique orders BEFORE adding phone to group_cols
        order_id_col = group_cols[0] if group_cols else None
        unique_orders_count = (
            int(df[order_id_col].nunique())
            if order_id_col and order_id_col in df.columns
            else len(df)
        )
        basket_metrics["total_orders"] = unique_orders_count

        if "phone" in selected_cols and selected_cols["phone"] in df.columns:
            group_cols.append(selected_cols["phone"])
        elif "Phone (Billing)" in df.columns:
            group_cols.append("Phone (Billing)")

        if group_cols:
            item_expr = (
                pl.when(~pl.col("Is_Bundle_Combo"))
                .then(1)
                .otherwise(0)
                .sum()
                .alias("Item Count")
                if "Is_Bundle_Combo" in df.columns
                else pl.count().alias("Item Count")
            )
            order_groups = (
                lazy_df.group_by(group_cols)
                .agg(
                    [
                        pl.col("Quantity").sum().alias("Quantity"),
                        pl.col("Total Amount").sum().alias("Total Amount"),
                        item_expr,
                    ]
                )
                .collect()
                .to_pandas()
            )

            avg_qty = order_groups["Quantity"].mean()
            avg_val = order_groups["Total Amount"].mean()
            basket_metrics["avg_basket_qty"] = (
                float(avg_qty) if pd.notna(avg_qty) else 0
            )
            basket_metrics["avg_basket_value"] = (
                float(avg_val) if pd.notna(avg_val) else 0
            )
            basket_metrics["total_orders"] = unique_orders_count

            multi_item_orders = len(order_groups[order_groups["Item Count"] > 1])
            basket_metrics["attachment_rate"] = (
                (multi_item_orders / unique_orders_count * 100)
                if unique_orders_count > 0
                else 0
            )

        phone_col = None
        if "phone" in selected_cols and selected_cols["phone"] in df.columns:
            phone_col = selected_cols["phone"]
        elif "Phone (Billing)" in df.columns:
            phone_col = "Phone (Billing)"

        if not phone_col:
            basket_metrics["avg_customer_value"] = basket_metrics["avg_basket_value"]
            basket_metrics["unique_customers"] = unique_orders_count

        basket_metrics["total_gross_revenue"] = (
            float(df["Gross Amount"].sum())
            if "Gross Amount" in df.columns
            else float(df["Total Amount"].sum())
        )
        basket_metrics["total_cashback_discount"] = (
            float(df["Cashback Discount"].sum())
            if "Cashback Discount" in df.columns
            else 0.0
        )

        return drilldown, summary, top_items, basket_metrics
    except Exception as e:
        log_system_event("AGGREGATE_ERROR", str(e))
        return None, None, None, {}


def get_dispatch_metrics(active_df: pd.DataFrame, total_orders: int = 0) -> dict:
    """Calculates dispatch, exchange, and freebie metrics from active shift data."""
    metrics = {
        "outlet_dispatch": 0,
        "exchange_dispatch": 0,
        "last_shipped_order": "N/A",
        "last_pathao_print": "N/A",
        "ecom_dispatch": 0,
        "pathao_count": 0,
        "other_count": 0,
        "pending": 0,
        "dispatched": 0,
        "dispatch_rate": 0.0,
    }

    if active_df is not None and not active_df.empty:
        status_col = (
            "Order Status"
            if "Order Status" in active_df.columns
            else "Status"
            if "Status" in active_df.columns
            else None
        )
        order_col = (
            "Order ID"
            if "Order ID" in active_df.columns
            else "Order Number"
            if "Order Number" in active_df.columns
            else None
        )

        mod_date_col = (
            "mod_dt_parsed"
            if "mod_dt_parsed" in active_df.columns
            else (
                "Order Date Modified"
                if "Order Date Modified" in active_df.columns
                else None
            )
        )
        date_col = (
            mod_date_col
            if mod_date_col
            else (
                "Date"
                if "Date" in active_df.columns
                else "Order Date"
                if "Order Date" in active_df.columns
                else None
            )
        )
        pmt_col = (
            "Payment Method Title"
            if "Payment Method Title" in active_df.columns
            else None
        )

        if order_col:
            if status_col:
                metrics["exchange_dispatch"] = active_df[
                    active_df[status_col]
                    .astype(str)
                    .str.lower()
                    .str.contains("exchange", na=False)
                ][order_col].nunique()

                outlet_mask = (
                    active_df[status_col]
                    .astype(str)
                    .str.lower()
                    .str.contains("outlet", na=False)
                )
                if pmt_col:
                    outlet_mask = outlet_mask | active_df[pmt_col].astype(
                        str
                    ).str.lower().str.contains("outlet", na=False)
                metrics["outlet_dispatch"] = active_df[outlet_mask][order_col].nunique()

                status_lower = active_df[status_col].astype(str).str.lower().str.strip()
                # Pending orders
                pending_mask = status_lower.isin([s.lower() for s in ACTIVE_STATUSES])
                metrics["pending"] = active_df[pending_mask][order_col].nunique()

                # Dispatched orders: ONLY orders with status in SHIPPED_STATUSES
                shipped_mask = status_lower.isin([s.lower() for s in SHIPPED_STATUSES])
                exchange_mask = _detect_exchange_mask(active_df)
                shipped_df = active_df[shipped_mask & ~exchange_mask]
                metrics["dispatched"] = (
                    shipped_df[order_col].nunique() if not shipped_df.empty else 0
                )
            else:
                metrics["dispatched"] = active_df[order_col].nunique()
                shipped_df = active_df

            # Pathao Consignment ID check on shipped dataframe
            if not shipped_df.empty:
                if "Pathao Consignment ID" in shipped_df.columns:
                    p_col = (
                        shipped_df["Pathao Consignment ID"]
                        .astype(str)
                        .str.strip()
                        .str.lower()
                    )
                    pathao_mask = (
                        (p_col != "")
                        & (p_col != "nan")
                        & (p_col != "none")
                        & (p_col != "n/a")
                    )
                    metrics["pathao_count"] = shipped_df[pathao_mask][
                        order_col
                    ].nunique()
                elif "Shipping Method Title" in shipped_df.columns:
                    p_col = shipped_df["Shipping Method Title"].astype(str).str.lower()
                    pathao_mask = p_col.str.contains("pathao", na=False)
                    metrics["pathao_count"] = shipped_df[pathao_mask][
                        order_col
                    ].nunique()
                else:
                    metrics["pathao_count"] = metrics["dispatched"]
            else:
                metrics["pathao_count"] = 0

            metrics["other_count"] = max(
                0, metrics["dispatched"] - metrics["pathao_count"]
            )

            if not shipped_df.empty:
                latest_shipped = (
                    shipped_df.sort_values(date_col, ascending=False).iloc[0]
                    if date_col and date_col in shipped_df.columns
                    else shipped_df.iloc[0]
                )
                metrics["last_shipped_order"] = str(latest_shipped[order_col])

                if "Pathao Consignment ID" in shipped_df.columns:
                    p_col_s = (
                        shipped_df["Pathao Consignment ID"]
                        .astype(str)
                        .str.strip()
                        .str.lower()
                    )
                    p_shipped = shipped_df[
                        (p_col_s != "")
                        & (p_col_s != "nan")
                        & (p_col_s != "none")
                        & (p_col_s != "n/a")
                    ]
                    if not p_shipped.empty:
                        latest_pathao = (
                            p_shipped.sort_values(date_col, ascending=False).iloc[0]
                            if date_col and date_col in p_shipped.columns
                            else p_shipped.iloc[0]
                        )
                        metrics["last_pathao_print"] = str(latest_pathao[order_col])
                    else:
                        metrics["last_pathao_print"] = str(latest_shipped[order_col])
                else:
                    metrics["last_pathao_print"] = str(latest_shipped[order_col])

    if total_orders > 0:
        metrics["dispatch_rate"] = (metrics["dispatched"] / total_orders) * 100.0
    metrics["ecom_dispatch"] = max(
        0, total_orders - metrics["outlet_dispatch"] - metrics["exchange_dispatch"]
    )
    return metrics
