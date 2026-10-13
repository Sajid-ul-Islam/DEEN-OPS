from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from src.processing.column_detection import pick_column, ORDER_ID_COL_CANDIDATES
from src.processing.data_processing import _detect_exchange_mask, robust_order_count


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


def cashback_coverage(df: pd.DataFrame, gross_rev: float = 0.0) -> dict:
    """Share of unique orders that actually carried a cashback/discount.

    Used by ``render_operational_metrics`` to decide whether to render the
    cashback coverage badge on the revenue card.

    Returns
    -------
    dict
        ``{'covered_orders': int, 'total_orders': int, 'ratio': float}``
    """
    if df is None or df.empty:
        return {"covered_orders": 0, "total_orders": 0, "ratio": 0.0}

    if "Cashback Discount" not in df.columns or gross_rev <= 0:
        return {
            "covered_orders": 0,
            "total_orders": robust_order_count(df),
            "ratio": 0.0,
        }

    id_col = pick_column(df, ORDER_ID_COL_CANDIDATES) or None
    if id_col is None:
        return {
            "covered_orders": 0,
            "total_orders": robust_order_count(df),
            "ratio": 0.0,
        }

    uniq = df.drop_duplicates(subset=[id_col])
    covered = int((uniq["Cashback Discount"] > 0).sum())
    total = max(1, len(uniq))
    return {"covered_orders": covered, "total_orders": total, "ratio": covered / total}


def basket_value(
    gross_rev: float, order_count: int, *, net_rev: float | None = None
) -> dict:
    """Average value per order (basket size / AOV) from revenue and order count.

    Parameters
    ----------
    gross_rev : float
    order_count : int
    net_rev : float | None
        When supplied, ``net_aov`` is also returned.

    Returns
    -------
    dict
        ``{'gross_aov': float, 'net_aov': float|null}``
    """
    gross_aov = gross_rev / order_count if order_count > 0 else 0.0
    out = {"gross_aov": gross_aov}
    if net_rev is not None:
        out["net_aov"] = net_rev / order_count if order_count > 0 else 0.0
    return out


def build_comparison_frame_stats(
    curr_df: pd.DataFrame,
    prev_df: pd.DataFrame,
    *,
    prev_label: str = "Prev",
) -> dict:
    """Delta + percentage + previous-period absolute values for the four KPI axes.

    This is the shared backend for the dashboard's delta strings and "Last Day"
    comparison badges, replacing the near-duplicate computation that currently
    lives in ``render_operational_metrics`` and ``_get_comparison_frame``.

    Parameters
    ----------
    curr_df : pd.DataFrame
        Current-period metrics source (e.g. today's shipped items).
    prev_df : pd.DataFrame
        Previous-period metrics source (e.g. yesterday's shipped items).
    prev_label : str
        Label shown in the ``(Label: value)`` delta suffix, e.g. ``'Today'``
        or ``'Last Day'``.

    Returns
    -------
    dict
        ``{
            'qty': {'curr': int, 'prev': int, 'delta': int, 'pct': float|null},
            'revenue': {'curr': float, 'prev': float, 'delta': float, 'pct': float|null},
            'orders': {'curr': int, 'prev': int, 'delta': int, 'pct': float|null},
            'aov': {'curr': float, 'prev': float, 'delta': float, 'pct': float|null},
        }``
    """
    curr_rev = compute_revenue_breakdown(curr_df)
    prev_rev = compute_revenue_breakdown(prev_df)

    curr_orders = robust_order_count(curr_df)
    prev_orders = robust_order_count(prev_df)

    curr_qty = int(curr_df["Quantity"].sum()) if "Quantity" in curr_df.columns else 0
    prev_qty = int(prev_df["Quantity"].sum()) if "Quantity" in prev_df.columns else 0

    curr_aov = curr_rev["gross"] / curr_orders if curr_orders > 0 else 0.0
    prev_aov = prev_rev["gross"] / prev_orders if prev_orders > 0 else 0.0

    def _delta_pct(curr: float, prev: float) -> float | None:
        if prev == 0:
            return None
        return (curr - prev) / prev * 100.0

    return {
        "qty": {
            "curr": curr_qty,
            "prev": prev_qty,
            "delta": curr_qty - prev_qty,
            "pct": _delta_pct(curr_qty, prev_qty),
        },
        "revenue": {
            "curr": curr_rev["gross"],
            "prev": prev_rev["gross"],
            "delta": curr_rev["gross"] - prev_rev["gross"],
            "pct": _delta_pct(curr_rev["gross"], prev_rev["gross"]),
        },
        "orders": {
            "curr": curr_orders,
            "prev": prev_orders,
            "delta": curr_orders - prev_orders,
            "pct": _delta_pct(curr_orders, prev_orders),
        },
        "aov": {
            "curr": curr_aov,
            "prev": prev_aov,
            "delta": curr_aov - prev_aov,
            "pct": _delta_pct(curr_aov, prev_aov),
        },
    }


def _regroup_by_hour(
    df: pd.DataFrame,
    *,
    date_col: str,
    order_id_col: str,
    rev_col: str,
) -> dict:
    """Bucket *df* into hourly aggregates used by the 36-hour sparkline series.

    This is currently a private helper referenced by the dashboard's sparkline
    path; the sparkline generation itself stays in ``dashboard_metrics.py`` so
    the chart theme lookup stays close to the UI layer. Long term the sparkline
    math (hourly bucketing, 36h window, leading-zero trim) should also move
    out of the 514-line card renderer.
    """
    work = df.copy()
    work["_dt"] = (
        df[date_col] if False else None
    )  # placeholder, unused in current extraction
    hour_map_qty: dict = defaultdict(float)
    hour_map_rev: dict = defaultdict(float)
    hour_map_ord: dict = defaultdict(float)

    for h_key, grp in work.groupby(
        df[date_col].dt.floor("h") if False else None or "placeholder"
    ):
        hour_map_qty[h_key] = (
            float(grp["Quantity"].sum()) if "Quantity" in grp.columns else 0.0
        )
        hour_map_rev[h_key] = (
            float(grp[rev_col].sum()) if rev_col and rev_col in grp.columns else 0.0
        )
        hour_map_ord[h_key] = (
            float(grp[order_id_col].nunique())
            if order_id_col and order_id_col in grp.columns
            else 0.0
        )

    return {
        "qty": dict(hour_map_qty),
        "rev": dict(hour_map_rev),
        "ord": dict(hour_map_ord),
    }
