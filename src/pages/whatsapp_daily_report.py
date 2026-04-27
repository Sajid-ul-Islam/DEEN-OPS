#!/usr/bin/env python
"""
DEEN-OPS Daily Insights Report Generator

This script extracts the active operational shift data from the WooCommerce API
using DEEN-OPS internal services, generates a predictive forecast and top products
summary, and sends an executive narrative via WhatsApp.

Usage:
    python scripts/whatsapp_daily_report.py
"""

import os
import sys
import pandas as pd
from datetime import datetime, timezone, timedelta

# Ensure DEEN-OPS root is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock Streamlit session state for headless execution before importing app modules
import streamlit as st
if "wc_sync_mode" not in st.session_state:
    st.session_state["wc_sync_mode"] = "Operational Cycle"
if "operational_holidays" not in st.session_state:
    st.session_state["operational_holidays"] = []

from src.services.woocommerce.client import load_from_woocommerce
from src.processing.data_processing import prepare_granular_data, aggregate_data
from src.processing.data_processing import get_dispatch_metrics
from src.processing.forecasting import PredictiveIntelligence

def generate_report_data():
    print("📥 Loading WooCommerce Data via DEEN-OPS engine...")
    try:
        wc_res = load_from_woocommerce()
    except Exception as e:
        return f"⚠️ *DEEN-OPS Daily Briefing*\n\nCould not generate report: API connection failed.\nError: {e}", None, None, None

    partitions = wc_res.get("partitions", {})
    df_live_raw = partitions.get("wc_curr_df")
    df_prev_raw = partitions.get("wc_prev_df")
    df_full_raw = wc_res.get("df_to_return")

    if df_live_raw is None or df_live_raw.empty:
        return "⚠️ *DEEN-OPS Daily Briefing*\n\nNo active orders found for today's operational shift.", None, None, None

    wc_raw_mapping = {
        "name": "Item Name", "cost": "Item Cost", "qty": "Quantity", 
        "date": "Order Date", "order_id": "Order ID", "phone": "Phone (Billing)", "sku": "SKU"
    }

    print("⚙️ Processing data aggregates...")
    df_live, _ = prepare_granular_data(df_live_raw, wc_raw_mapping)
    drill, summ, top, basket = aggregate_data(df_live, wc_raw_mapping)

    today_rev = summ['Total Amount'].sum() if summ is not None else 0
    today_qty = summ['Total Qty'].sum() if summ is not None else 0
    today_orders = basket.get('total_orders', 0) if basket else 0
    today_aov = basket.get('avg_basket_value', 0) if basket else 0

    # Process yesterday's context for delta comparison
    prev_rev, prev_orders = 0, 0
    if df_prev_raw is not None and not df_prev_raw.empty:
        df_prev, _ = prepare_granular_data(df_prev_raw, wc_raw_mapping)
        _, summ_prev, _, basket_prev = aggregate_data(df_prev, wc_raw_mapping)
        prev_rev = summ_prev['Total Amount'].sum() if summ_prev is not None else 0
        prev_orders = basket_prev.get('total_orders', 0) if basket_prev else 0

    rev_trend = "📈" if today_rev >= prev_rev else "📉"
    dm = get_dispatch_metrics(df_live, today_orders)

    # Predictive Intelligence (Forecast next day)
    forecast_str = ""
    if df_full_raw is not None and not df_full_raw.empty:
        df_full, _ = prepare_granular_data(df_full_raw, wc_raw_mapping)
        df_full['Day'] = pd.to_datetime(df_full['Date']).dt.date
        daily_rev = df_full.groupby('Day')['Total Amount'].sum()
        if len(daily_rev) >= 3:
            fc_res, _ = PredictiveIntelligence.forecast(daily_rev, steps=1)
            if fc_res:
                next_day_pred = fc_res[0]['forecast'][0]
                forecast_str = f"\n🔮 *ML Forecast (Tomorrow):* ৳{next_day_pred:,.0f}"

    # Spotlight Top Products
    top_products_str = "No product data available."
    if top is not None and not top.empty:
        top_3 = top.head(3)
        top_products_str = "\n".join([f"• {row['Product Name']} ({row['Total Qty']} pcs)" for _, row in top_3.iterrows()])

    # Build Narrative
    report_lines = [
        f"📊 *DEEN-OPS Executive Briefing*",
        f"📅 {datetime.now(timezone(timedelta(hours=6))).strftime('%A, %d %B %Y')}",
        "",
        f"💰 *Today's Revenue:* ৳{today_rev:,.0f} {rev_trend}",
        f"📦 *Gross Items Sold:* {today_qty:,.0f}",
        f"🛍️ *Avg Basket Value:* ৳{today_aov:,.0f}",
        "",
        f"🚚 *Last Shipped Order:* {dm['last_shipped_order']}",
        f"🖨️ *Last Pathao Print:* {dm['last_pathao_print']}",
        "",
        f"🛒 *Total Orders:* {today_orders:,.0f}", 
        f"🔄 *Exchange:* {dm['exchange_dispatch']:,.0f}",
        f"🚀 *Ecom Dispatch:* {dm['ecom_dispatch']:,.0f}", 
        f"🏪 *Outlet Dispatch:* {dm['outlet_dispatch']:,.0f}",
        "",
        f"🎁 *Free T-Shirts (>3499 TK):* {dm['free_tshirts']:,.0f}",
        f"💧 *Free Water Bottles (>2499 TK):* {dm['free_bottles']:,.0f}",
        f"",
        f"📉 *Yesterday's Revenue:* ৳{prev_rev:,.0f} ({prev_orders} orders)",
        forecast_str,
        "",
        "🔥 *Top Performing Products:*",
        top_products_str,
        "",
        "💻 _Access the full dashboard at your DEEN-OPS Terminal: https://deen-ops.streamlit.app/_"
    ]

    report_text = "\n".join([line for line in report_lines if line is not None])
    return report_text, df_live, summ, top

if __name__ == "__main__":
    report_text, df_live, summ, top = generate_report_data()
    
    export_filename = f"DEEN_OPS_Daily_Report_{datetime.now(timezone(timedelta(hours=6))).strftime('%Y-%m-%d')}.xlsx"
    print("💾 Exporting data to Excel for Power BI / Tableau...")
    
    df_narrative = pd.DataFrame({"Executive Summary": report_text.split('\n')})
    
    try:
        with pd.ExcelWriter(export_filename, engine="xlsxwriter") as writer:
            df_narrative.to_excel(writer, sheet_name="Executive Briefing", index=False)
            if summ is not None and not summ.empty:
                summ.to_excel(writer, sheet_name="Category Summary", index=False)
            if top is not None and not top.empty:
                top.to_excel(writer, sheet_name="Top Products", index=False)
            if df_live is not None and not df_live.empty:
                df_live.to_excel(writer, sheet_name="Raw Shift Data", index=False)
        
        print(f"\n✅ Successfully exported report to: {os.path.abspath(export_filename)}")
        print("💡 You can now import this .xlsx file directly into Power BI, Tableau, or Excel.")
    except Exception as e:
        print(f"❌ Failed to export Excel file: {e}")