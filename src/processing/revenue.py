from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from src.processing.column_detection import pick_column, ORDER_ID_COL_CANDIDATES
from src.processing.data_processing import _detect_exchange_mask


def compute_revenue_breakdown(df: pd.DataFrame) -> dict:
    """Single source of truth for the gross / cashback / net revenue triple.

    Returns
    -------
    dict
        ``{
            'gross': float,
            'cashback': float,
            'net': float,
            'loss_pct': float,
            'item_rev': float,
        }``

    Rules
    -----
    * ``gross`` is ``df['Gross Amount'].sum()`` when that column exists,
      otherwise it falls back to the line-level quantity * item-cost total.
    * ``cashback`` is ``df['Cashback Discount'].sum()`` (0 when the column
      is absent).
    * ``net`` is ``max(0.0, gross - cashback)``.
    * ``loss_pct`` is ``cashback / gross * 100`` (0 when gross is 0).
    * ``item_rev`` is always the quantity * item-cost total, used as a
      secondary signal by downstream consumers.
    """
    if df is None or df.empty:
        return {
            "gross": 0.0,
            "cashback": 0.0,
            "net": 0.0,
            "loss_pct": 0.0,
            "item_rev": 0.0,
        }

    qty_col = "Quantity" if "Quantity" in df.columns else None
    cost_col = "Item Cost" if "Item Cost" in df.columns else None
    item_rev = (
        float((df[qty_col] * df[cost_col]).sum()) if qty_col and cost_col else 0.0
    )

    gross = (
        float(df["Gross Amount"].sum()) if "Gross Amount" in df.columns else item_rev
    )
    cashback = (
        float(df["Cashback Discount"].sum())
        if "Cashback Discount" in df.columns
        else 0.0
    )

    net = max(0.0, gross - cashback)
    loss_pct = (cashback / gross * 100.0) if gross > 0 else 0.0

    return {
        "gross": gross,
        "cashback": cashback,
        "net": net,
        "loss_pct": loss_pct,
        "item_rev": item_rev,
    }


def count_exchange_orders(
    df: pd.DataFrame,
    *,
    order_id_col: str | None = None,
    order_id_candidates: tuple[str, ...] = ORDER_ID_COL_CANDIDATES,
) -> int:
    """Count unique exchange orders in *df*, using the canonical exchange rule.

    An order is an exchange when its Order Status contains "exchange" **or** its
    Fee Notes contains "exchange credit". This is the same detection as
    ``_detect_exchange_mask`` and the rule already shared by
    ``data_processing._partition_operational_data``,
    ``completed_analytics``, ``live_dashboard``, and the dispatch export.

    Parameters
    ----------
    df : pd.DataFrame
    order_id_col : str | None
        Explicit order id column. When ``None`` the first present candidate of
        ``ORDER_ID_COL_CANDIDATES`` is used.
    order_id_candidates : tuple[str, ...]
        Candidate order-id columns, in priority order.

    Returns
    -------
    int
    """
    if df is None or df.empty:
        return 0

    if order_id_col is None:
        order_id_col = pick_column(df, order_id_candidates) or None

    mask = _detect_exchange_mask(df)
    exchange_df = df[mask]

    if order_id_col and order_id_col in exchange_df.columns:
        return int(exchange_df[order_id_col].nunique())

    return int(mask.sum())
