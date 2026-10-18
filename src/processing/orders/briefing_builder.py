"""Executive briefing narrative and campaign detection logic for DEEN-OPS.

Provides the single source of truth narrative for daily executive summaries
and dynamic campaign/discount rate detection across WooCommerce orders.
"""

from __future__ import annotations

import pandas as pd

from src.config.constants import bd_now


def generate_executive_briefing(
    today_rev: float,
    today_qty: int | float,
    today_orders: int,
    today_aov: float,
    dm: dict | None,
    top: pd.DataFrame | None,
    gross_rev: float | None = None,
    cashback_disc: float | None = None,
    selects_stats: dict | None = None,
) -> str:
    """Generates the single source of truth narrative for the Executive Briefing."""
    dm = dm or {}

    g_rev = gross_rev if gross_rev is not None else today_rev
    gross_aov = (g_rev / today_orders) if today_orders > 0 else today_aov

    report_lines = [
        "📊 *DEEN-OPS Executive Briefing*",
        f"📅 {bd_now().strftime('%A, %d %B %Y')}",
        "",
        f"💵 *Gross Revenue:* ৳{g_rev:,.0f}",
        "",
        f"📦 *Shipped Items:* {today_qty:,.0f}",
        f"🛍️ *Avg Basket Value:* ৳{gross_aov:,.0f}",
    ]

    if selects_stats and selects_stats.get("total_revenue", 0) > 0:
        s_rev = selects_stats.get("selects_rev", 0.0)
        s_qty = selects_stats.get("selects_qty", 0)
        s_pct = selects_stats.get("selects_rev_share", 0.0)
        r_rev = selects_stats.get("regular_rev", 0.0)
        r_qty = selects_stats.get("regular_qty", 0)
        r_pct = selects_stats.get("regular_rev_share", 0.0)
        report_lines.extend(
            [
                "",
                "🏷️ *Collection Split:*",
                f"💎 *DEEN Selects:* ৳{s_rev:,.0f} ({s_qty:,} pcs · {s_pct:.1f}%)",
                f"📦 *DEEN Regular:* ৳{r_rev:,.0f} ({r_qty:,} pcs · {r_pct:.1f}%)",
            ]
        )

    report_lines.extend(
        [
            "",
            "",
            f"📋 *Last Shipped Order:* {dm.get('last_shipped_order', 'N/A')}",
            f"🖨️ *Last Pathao Print:* {dm.get('last_pathao_print', 'N/A')}",
            "",
            f"🛒 *Total Orders:* {today_orders:,.0f}",
            f"🔄 *Exchange:* {dm.get('exchange_dispatch', 0):,.0f}",
            f"🚀 *Ecom:* {dm.get('ecom_dispatch', 0):,.0f}",
            f"🏪 *Outlet:* {dm.get('outlet_dispatch', 0):,.0f}",
            "",
            "🔥 *Top Performing Products:*",
        ]
    )

    if top is not None and not top.empty:
        if "Clean_Product" in top.columns:
            group_cols = (
                ["Clean_Product", "SKU"] if "SKU" in top.columns else ["Clean_Product"]
            )
            top_summary = top.groupby(group_cols, as_index=False).agg(
                {"Total Qty": "sum", "Total Amount": "sum"}
            )
            top_summary = top_summary.sort_values("Total Amount", ascending=False)
            top_3 = top_summary.head(3)
            for _, row in top_3.iterrows():
                sku_str = (
                    f" [{row['SKU']}]"
                    if "SKU" in top.columns
                    and str(row["SKU"]) not in ["N/A", "", "None", "nan"]
                    else ""
                )
                report_lines.append(
                    f"• {row['Clean_Product']}{sku_str} ({row['Total Qty']} pcs)"
                )
        else:
            top_3 = top.head(3)
            for _, row in top_3.iterrows():
                report_lines.append(f"• {row['Product Name']} ({row['Total Qty']} pcs)")
    else:
        report_lines.append("No product data available.")

    report_lines.extend(
        [
            "",
            "💻 _Access the full dashboard at your DEEN-OPS Terminal: "
            "https://deen-ops.streamlit.app/_",
        ]
    )

    return "\n".join(report_lines)


def detect_active_campaign(df: pd.DataFrame | None) -> dict:
    """Dynamically inspects live orders to identify active campaigns, discounts, flat sales, or cashback.

    Returns a dict with campaign metadata:
      - is_active: bool
      - campaign_name: str (e.g. "Flat 50% Sale", "Cashback Offer", "Coupon Promo")
      - campaign_type: str ("flat_sale", "cashback", "coupon", "item_discount", "none")
      - total_discount: float
      - gross_revenue: float
      - net_revenue: float
      - discount_rate_pct: float
      - affected_orders_pct: float
      - badge_label: str
    """
    default_res = {
        "is_active": False,
        "campaign_name": "No Active Campaign",
        "campaign_type": "none",
        "total_discount": 0.0,
        "gross_revenue": 0.0,
        "net_revenue": 0.0,
        "discount_rate_pct": 0.0,
        "affected_orders_pct": 0.0,
        "badge_label": "",
    }
    if df is None or df.empty:
        return default_res

    # 1. Total discounts & Revenue
    fee_disc = 0.0
    if "Fee Discount Total" in df.columns:
        fee_disc = float(
            pd.to_numeric(df["Fee Discount Total"], errors="coerce").fillna(0).sum()
        )

    item_disc = 0.0
    if "Item Discount" in df.columns:
        item_disc = float(
            pd.to_numeric(df["Item Discount"], errors="coerce").fillna(0).sum()
        )
    elif (
        "Subtotal Cost" in df.columns
        and "Item Cost" in df.columns
        and "Quantity" in df.columns
    ):
        sub = pd.to_numeric(df["Subtotal Cost"], errors="coerce").fillna(0)
        cost = pd.to_numeric(df["Item Cost"], errors="coerce").fillna(0)
        qty = pd.to_numeric(df["Quantity"], errors="coerce").fillna(1)
        item_disc = float(((sub - cost) * qty).clip(lower=0).sum())

    order_disc = 0.0
    if "Order Discount Total" in df.columns and item_disc == 0.0:
        order_disc = float(
            pd.to_numeric(df["Order Discount Total"], errors="coerce").fillna(0).sum()
        )

    total_discount = fee_disc + item_disc + order_disc

    net_rev = 0.0
    if "Total Amount" in df.columns:
        net_rev = float(
            pd.to_numeric(df["Total Amount"], errors="coerce").fillna(0).sum()
        )
    elif "Order Total Amount" in df.columns:
        ord_col = "Order ID" if "Order ID" in df.columns else None
        if ord_col:
            net_rev = float(
                pd.to_numeric(
                    df.groupby(ord_col)["Order Total Amount"].first(), errors="coerce"
                )
                .fillna(0)
                .sum()
            )
        else:
            net_rev = float(
                pd.to_numeric(df["Order Total Amount"], errors="coerce").fillna(0).sum()
            )

    gross_rev = net_rev + total_discount
    discount_rate_pct = (total_discount / gross_rev * 100) if gross_rev > 0 else 0.0

    # 2. Check affected orders
    ord_col = (
        "Order ID"
        if "Order ID" in df.columns
        else "Order Number"
        if "Order Number" in df.columns
        else None
    )
    tot_orders = (
        len(df[ord_col].dropna().unique())
        if ord_col and ord_col in df.columns
        else len(df)
    )

    disc_orders = 0
    if ord_col and ord_col in df.columns:
        disc_mask = pd.Series(False, index=df.index)
        if "Cashback Discount" in df.columns:
            disc_mask |= (
                pd.to_numeric(df["Cashback Discount"], errors="coerce").fillna(0) > 0
            )
        if "Item Discount" in df.columns:
            disc_mask |= (
                pd.to_numeric(df["Item Discount"], errors="coerce").fillna(0) > 0
            )
        if "Fee Discount Total" in df.columns:
            disc_mask |= (
                pd.to_numeric(df["Fee Discount Total"], errors="coerce").fillna(0) > 0
            )
        disc_orders = len(df.loc[disc_mask, ord_col].dropna().unique())
    affected_pct = (disc_orders / tot_orders * 100) if tot_orders > 0 else 0.0

    # 3. Campaign Type & Name Detection from WooCommerce Signals
    if total_discount < 50.0 or discount_rate_pct < 0.5:
        return default_res

    # Check fee notes for explicit cashback
    has_cashback_fee = False
    if "Fee Notes" in df.columns:
        notes_concat = " ".join(df["Fee Notes"].dropna().astype(str).tolist()).lower()
        if "cashback" in notes_concat or "cash back" in notes_concat:
            has_cashback_fee = True

    # Check coupons
    coupon_names = []
    if "Coupons" in df.columns:
        raw_coupons = df["Coupons"].dropna().astype(str).tolist()
        for c in raw_coupons:
            for piece in c.split(","):
                clean_c = piece.strip().upper()
                if clean_c and clean_c not in ("NONE", "NAN", "", "N/A"):
                    coupon_names.append(clean_c)
        coupon_names = list(dict.fromkeys(coupon_names))

    if has_cashback_fee:
        c_type = "cashback"
        c_name = "Cashback Offer"
    elif coupon_names:
        c_type = "coupon"
        c_name = f"Coupon Promo ({', '.join(coupon_names[:2])})"
    elif discount_rate_pct >= 25.0:
        c_type = "flat_sale"
        rounded_rate = int(round(discount_rate_pct / 5.0) * 5)
        c_name = f"Flat {rounded_rate}% Sale"
    else:
        c_type = "item_discount"
        c_name = f"Sale Campaign ({discount_rate_pct:.0f}% Off)"

    badge_label = f"🎯 {c_name} −৳{int(total_discount):,} ({affected_pct:.0f}% orders)"

    return {
        "is_active": True,
        "campaign_name": c_name,
        "campaign_type": c_type,
        "total_discount": total_discount,
        "gross_revenue": gross_rev,
        "net_revenue": net_rev,
        "discount_rate_pct": discount_rate_pct,
        "affected_orders_pct": affected_pct,
        "badge_label": badge_label,
    }
