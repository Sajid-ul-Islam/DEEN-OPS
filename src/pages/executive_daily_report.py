#!/usr/bin/env python
"""
DEEN-OPS Daily Insights Report Generator

This script extracts the active operational shift data from the WooCommerce API
using DEEN-OPS internal services, generates a predictive forecast and top products
summary, and sends an executive narrative via WhatsApp.

Usage:
    python src/pages/executive_daily_report.py
"""

import asyncio
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

from src.config.constants import SHIPPED_STATUSES
from src.services.woocommerce.client import load_from_woocommerce
from src.processing.data_processing import (aggregate_data, get_dispatch_metrics,
                                            prepare_granular_data)
from src.processing.forecasting import PredictiveIntelligence

def generate_report_data():
    print("📥 Loading WooCommerce Data via DEEN-OPS engine...")
    try:
        wc_res = load_from_woocommerce()
    except Exception as e:
        return f"⚠️ *DEEN-OPS Daily Briefing*\n\nCould not generate report: API connection failed.\nError: {e}", None, None, None

    partitions = wc_res.get("partitions", {})
    slots = wc_res.get("slots", {})
    df_live_raw = partitions.get("wc_curr_df")
    df_prev_raw = partitions.get("wc_prev_df")
    df_full_raw = wc_res.get("df_to_return")

    # Determine cutoff for modification tracking
    curr_slot = slots.get("wc_curr_slot")
    if curr_slot:
        slot_start, slot_end = curr_slot
    else:
        now_bd = datetime.now(timezone(timedelta(hours=6))).replace(tzinfo=None)
        slot_end = now_bd.replace(hour=17, minute=30, second=0, microsecond=0)
        slot_start = slot_end - timedelta(days=1)

    # Enforce strict "Shipped Only" filter for the operational briefing
    if df_live_raw is not None and not df_live_raw.empty:
        # Filter for orders modified to shipped during the active slot
        if "mod_dt_parsed" in df_live_raw.columns:
            df_live_raw["mod_dt"] = df_live_raw["mod_dt_parsed"]
        else:
            dt_s = pd.to_datetime(df_live_raw["Order Date Modified"], errors="coerce")
            df_live_raw["mod_dt"] = dt_s.dt.tz_localize(None) if getattr(dt_s.dt, "tz", None) is not None else dt_s

        df_live_raw = df_live_raw[
            (df_live_raw["Order Status"].isin(SHIPPED_STATUSES)) & 
            (df_live_raw["mod_dt"] >= slot_start) &
            (df_live_raw["mod_dt"] <= (slot_end + timedelta(minutes=30)))
        ]
            
    if df_prev_raw is not None and not df_prev_raw.empty:
        prev_slot = slots.get("wc_prev_slot")
        if prev_slot:
            p_start, p_end = prev_slot
            if "mod_dt_parsed" in df_prev_raw.columns:
                df_prev_raw["mod_dt"] = df_prev_raw["mod_dt_parsed"]
            else:
                dt_s_prev = pd.to_datetime(df_prev_raw["Order Date Modified"], errors="coerce")
                df_prev_raw["mod_dt"] = dt_s_prev.dt.tz_localize(None) if getattr(dt_s_prev.dt, "tz", None) is not None else dt_s_prev

            df_prev_raw = df_prev_raw[
                (df_prev_raw["Order Status"].isin(SHIPPED_STATUSES)) &
                (df_prev_raw["mod_dt"] >= p_start) &
                (df_prev_raw["mod_dt"] <= (p_end + timedelta(minutes=30)))
            ]

    if df_live_raw is None or df_live_raw.empty:
        return "⚠️ *DEEN-OPS Daily Briefing*\n\nNo shipped orders found for today's operational shift.", None, None, None

    wc_raw_mapping = {
        "name": "Item Name", "cost": "Item Cost", "qty": "Quantity", 
        "date": "Order Date", "order_id": "Order ID", "phone": "Phone (Billing)", "sku": "SKU"
    }

    print("⚙️ Processing data aggregates...")
    df_live, _ = prepare_granular_data(df_live_raw, wc_raw_mapping)
    drill, summ, top, basket = aggregate_data(df_live, wc_raw_mapping)

    # Filter out ended promotional offers from top products list
    if top is not None and not top.empty:
        top = top[~top["Product Name"].str.contains("Free T-Shirt|Free Water Bottle", case=False, na=False)]

    today_rev = summ['Total Amount'].sum() if summ is not None else 0
    today_qty = summ['Total Qty'].sum() if summ is not None else 0
    today_orders = basket.get('total_orders', 0) if basket else 0
    today_aov = basket.get('avg_customer_value', basket.get('avg_basket_value', 0)) if basket else 0

    # Process yesterday's context for delta comparison
    prev_rev, prev_orders = 0, 0
    if df_prev_raw is not None and not df_prev_raw.empty:
        df_prev, _ = prepare_granular_data(df_prev_raw, wc_raw_mapping)
        _, summ_prev, _, basket_prev = aggregate_data(df_prev, wc_raw_mapping)
        prev_rev = summ_prev['Total Amount'].sum() if summ_prev is not None else 0
        prev_orders = basket_prev.get('total_orders', 0) if basket_prev else 0

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
                forecast_str = f"🔮 *ML Forecast (Tomorrow):* ৳{next_day_pred:,.0f}"

    # AI-powered narrative generation
    print("🧠 Generating AI Executive Narrative...")
    context_data = {
        "sales_summary": summ,
        "top_products": top,
        "raw_sales_data": df_live,
    }
    
    prompt = f"""
    Generate an executive briefing for today's e-commerce operations.
    Today's key metrics:
    - Revenue: ৳{today_rev:,.0f}
    - Orders: {today_orders}
    - Items Sold: {today_qty}
    - Average Order Value: ৳{today_aov:,.0f}

    Comparison with yesterday:
    - Yesterday's Revenue: ৳{prev_rev:,.0f}
    - Yesterday's Orders: {prev_orders}

    Dispatch Metrics:
    - Shipped via Pathao: {dm.get('pathao_count', 0)}
    - Shipped via Other: {dm.get('other_count', 0)}

    {forecast_str}

    Based on the provided context data (sales_summary, top_products), write a concise, professional, and insightful narrative.
    Highlight key trends, mention the top-performing products/categories, and provide a concluding remark on the day's performance.
    The entire response should be a single block of text formatted for WhatsApp (using markdown like *bold* and _italic_).
    """

    try:
        from src.pages.data_pilot import AIDataAgent
        agent = AIDataAgent(context_dfs=context_data)
        
        async def get_narrative():
            full_response = ""
            async for chunk in agent.get_response_stream(prompt, history=[]):
                full_response += chunk
            return full_response
        report_text = asyncio.run(get_narrative())
    except Exception as e:
        print(f"❌ AI narrative generation failed: {e}. Falling back to template.")
        from src.processing.data_processing import generate_executive_briefing
        report_text = generate_executive_briefing(
            today_rev, today_qty, today_orders, today_aov, dm, top,
            prev_rev=prev_rev, prev_orders=prev_orders, forecast_str=forecast_str
        )
    
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