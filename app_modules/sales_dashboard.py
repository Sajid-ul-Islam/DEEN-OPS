import re
import functools
import streamlit as st
import pandas as pd
import plotly.express as px
import os
import json
import streamlit.components.v1 as components
import base64
import requests
from datetime import datetime, timedelta, timezone
from io import BytesIO
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse
from requests.auth import HTTPBasicAuth
from concurrent.futures import ThreadPoolExecutor, as_completed

from app_modules.ui_components import (
    section_card,
    render_action_bar,
    render_reset_confirm,
)

def render_snapshot_button(marker_id="snapshot-target"):
    """Capture and download dashboard area snapshot as PNG."""
    html_code = """
    <div style="text-align:right; margin:6px 0 2px 0;">
      <button onclick="captureDashboard()" style="
          background:#1d4ed8; color:#fff; border:none; border-radius:8px;
          padding:7px 12px; font-size:13px; font-weight:600; cursor:pointer;">
          Save Snapshot
      </button>
    </div>
    <script>
    function captureDashboard() {
      const marker = window.parent.document.getElementById('__MARKER__');
      let target = null;
      if (marker) {
        target = marker.closest('[data-testid="stVerticalBlock"]');
      }
      if (!target) {
        target = window.parent.document.querySelector('[data-testid="stAppViewContainer"]');
      }
      if (!target) return;

      const doCapture = () => {
        const originalPadding = target.style.padding;
        const originalBackground = target.style.backgroundColor;
        const originalBorderRadius = target.style.borderRadius;
        const appBg = window.parent.getComputedStyle(window.parent.document.body).backgroundColor || '#0f172a';

        // Add breathing room so left edge does not feel cramped in snapshot.
        target.style.padding = '18px 22px 18px 30px';
        target.style.backgroundColor = appBg;
        target.style.borderRadius = '12px';

        window.parent.html2canvas(target, {useCORS: true, scale: 2, backgroundColor: appBg})
          .then((canvas) => {
            target.style.padding = originalPadding;
            target.style.backgroundColor = originalBackground;
            target.style.borderRadius = originalBorderRadius;
            const a = window.parent.document.createElement('a');
            a.download = 'dashboard_snapshot.png';
            a.href = canvas.toDataURL('image/png');
            a.click();
          })
          .catch(() => {
            target.style.padding = originalPadding;
            target.style.backgroundColor = originalBackground;
            target.style.borderRadius = originalBorderRadius;
          });
      };

      if (!window.parent.html2canvas) {
        const script = window.parent.document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
        script.onload = doCapture;
        window.parent.document.head.appendChild(script);
      } else {
        doCapture();
      }
    }
    </script>
    """.replace("__MARKER__", marker_id)
    components.html(html_code, height=44)


# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FEEDBACK_DIR = os.path.join(DATA_DIR, "feedback")
INCOMING_DIR = os.path.join(DATA_DIR, "incoming")
from app_modules.ui_config import DEFAULT_GSHEET_URL
os.makedirs(FEEDBACK_DIR, exist_ok=True)
os.makedirs(INCOMING_DIR, exist_ok=True)


def log_system_event(event_type, details):
    """Logs errors or system events to a JSON file for further analysis."""
    log_file = os.path.join(FEEDBACK_DIR, "system_logs.json")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_entry = {"timestamp": timestamp, "type": event_type, "details": details}

    try:
        logs = []
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)

        logs.append(log_entry)
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4)
    except Exception as e:
        print(f"Logging failed: {e}")


def save_user_feedback(comment):
    """Saves user comments to a feedback file."""
    feedback_file = os.path.join(FEEDBACK_DIR, "user_feedback.json")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    feedback_entry = {"timestamp": timestamp, "comment": comment}

    try:
        data = []
        if os.path.exists(feedback_file):
            with open(feedback_file, "r", encoding="utf-8") as f:
                data = json.load(f)

        data.append(feedback_entry)
        with open(feedback_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception:
        return False


def get_setting(key, default=None):
    """Reads setting from Streamlit secrets first, then env var."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


def get_gcp_service_account_info():
    """Returns service account info from st.secrets or env JSON."""
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass

    raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except Exception as e:
            raise ValueError(f"Invalid GCP_SERVICE_ACCOUNT_JSON: {e}")

    return None


# v9.5 Expert Rules - Professional Categorization Patterns
SPECIFIC_CATS = {
    "Tank Top": ["tank top"],
    "Boxer": ["boxer"],
    "Jeans": ["jeans"],
    "Denim Shirt": ["denim"],
    "Flannel Shirt": ["flannel"],
    "Polo Shirt": ["polo"],
    "Panjabi": ["panjabi", "punjabi"],
    "Trousers": ["trousers", "trouser"],
    "Joggers": ["joggers", "jogger", "track pant"],
    "Twill Chino": ["twill chino", "chino", "twill"],
    "Mask": ["mask"],
    "Leather Bag": ["bag", "backpack"],
    "Water Bottle": ["water bottle"],
    "Contrast Shirt": ["contrast"],
    "Turtleneck": ["turtleneck", "mock neck"],
    "Drop Shoulder": ["drop", "shoulder"],
    "Wallet": ["wallet"],
    "Kaftan Shirt": ["kaftan"],
    "Active Wear": ["active wear"],
    "Jersy": ["jersy"],
    "Sweatshirt": ["sweatshirt", "hoodie", "pullover"],
    "Jacket": ["jacket", "outerwear", "coat"],
    "Belt": ["belt"],
    "Sweater": ["sweater", "cardigan", "knitwear"],
    "Passport Holder": ["passport holder"],
    "Card Holder": ["card holder"],
    "Cap": ["cap"],
}

# Pre-compile patterns for maximum speed
CAT_PATTERNS = {
    cat: [re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE) for kw in keywords]
    for cat, keywords in SPECIFIC_CATS.items()
}
FS_KEYWORDS = [re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE) for kw in ["full sleeve", "long sleeve", "fs", "l/s"]]
TSHIRT_KEYWORDS = [re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE) for kw in ["t-shirt", "t shirt", "tee"]]
SHIRT_KEYWORDS = [re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE) for kw in ["shirt"]]

@functools.lru_cache(maxsize=1024)
def get_category(name):
    """Categorizes products based on keywords in their names (Optimized v9.5)."""
    if not name: return "Others"
    name_str = str(name).lower()

    for cat, patterns in CAT_PATTERNS.items():
        if any(p.search(name_str) for p in patterns):
            return cat

    is_fs = any(p.search(name_str) for p in FS_KEYWORDS)
    if any(p.search(name_str) for p in TSHIRT_KEYWORDS):
        return "FS T-Shirt" if is_fs else "T-Shirt"

    if any(p.search(name_str) for p in SHIRT_KEYWORDS):
        return "FS Shirt" if is_fs else "HS Shirt"

    return "Others"

    return "Others"


@st.cache_data(show_spinner=False)
def find_columns(df):
    """Detects primary columns using exact and then partial matching."""
    mapping = {
        "name": [
            "item name",
            "product name",
            "product",
            "item",
            "title",
            "description",
            "name",
        ],
        "cost": [
            "item cost",
            "price",
            "unit price",
            "cost",
            "rate",
            "mrp",
            "selling price",
        ],
        "qty": ["quantity", "qty", "units", "sold", "count", "total quantity"],
        "date": ["date", "order date", "month", "time", "created at"],
        "order_id": [
            "order id",
            "order #",
            "invoice number",
            "invoice #",
            "order number",
            "transaction id",
            "id",
        ],
        "phone": [
            "phone",
            "contact",
            "mobile",
            "cell",
            "phone number",
            "customer phone",
        ],
    }

    found = {}
    actual_cols = [c.strip() for c in df.columns]
    lower_cols = [c.lower() for c in actual_cols]

    for key, aliases in mapping.items():
        for alias in aliases:
            if alias in lower_cols:
                idx = lower_cols.index(alias)
                found[key] = actual_cols[idx]
                break

    for key, aliases in mapping.items():
        if key not in found:
            for col, l_col in zip(actual_cols, lower_cols):
                if any(alias in l_col for alias in aliases):
                    found[key] = col
                    break

    return found


@st.cache_data(show_spinner=False)
def scrub_raw_dataframe(df):
    """Filters out dashboard analytics, empty rows, and summary tables from raw exports."""
    if df is None or df.empty:
        return df

    # 1. Drop completely empty rows
    df = df.dropna(how="all")

    # 2. Heuristic: Sparsity Check
    # Keep rows that have at least 30% of the columns filled
    min_threshold = max(1, int(len(df.columns) * 0.3))
    df = df.dropna(thresh=min_threshold)

    # 3. Optimized Summary Filter (Avoid stacking)
    # Target common text columns instead of the entire dataframe
    summary_keywords = ["total", "grand total", "summary", "analytics", "chart", "metric"]
    pattern = "|".join(summary_keywords)
    
    # Check specifically for Order Number or ID being 'Total' or similar
    # If we find a column that looks like an ID, use it as a primary filter
    id_cols = [c for c in df.columns if any(k in c.lower() for k in ["id", "number", "invoice", "#"])]
    if id_cols:
        col = id_cols[0]
        df = df[~df[col].astype(str).str.lower().str.contains(pattern, na=False)]
    
    return df


def process_data(df, selected_cols):
    """Processed data using validated user-selected or auto-detected columns."""
    try:
        df = df.copy()

        # Scrub dashboard analytics, pivot tables, and empty totals from live exports
        df = scrub_raw_dataframe(df)

        if df.empty:
            raise ValueError("Dataset is empty after stripping metrics/analytics rows.")

        df["Internal_Name"] = (
            df[selected_cols["name"]].fillna("Unknown Product").astype(str)
        )
        df = df[~df["Internal_Name"].str.contains("Choose Any", case=False, na=False)]

        df["Internal_Cost"] = pd.to_numeric(
            df[selected_cols["cost"]], errors="coerce"
        ).fillna(0)
        df["Internal_Qty"] = pd.to_numeric(
            df[selected_cols["qty"]], errors="coerce"
        ).fillna(0)

        timeframe_suffix = ""
        if "date" in selected_cols and selected_cols["date"] in df.columns:
            try:
                dates = pd.to_datetime(
                    df[selected_cols["date"]], errors="coerce"
                ).dropna()
                if not dates.empty:
                    if dates.dt.to_period("M").nunique() == 1:
                        timeframe_suffix = dates.iloc[0].strftime("%B_%Y")
                    else:
                        timeframe_suffix = f"{dates.min().strftime('%d%b')}_to_{dates.max().strftime('%d%b_%y')}"
            except Exception:
                non_null = df[selected_cols["date"]].dropna()
                val = str(non_null.iloc[0]) if not non_null.empty else ""
                timeframe_suffix = val.replace("/", "-").replace(" ", "_")[:20]

        if (df["Internal_Qty"] < 0).any():
            log_system_event("DATA_ISSUE", "Found negative quantities, converted to 0.")
            df.loc[df["Internal_Qty"] < 0, "Internal_Qty"] = 0

        # Optimized Categorization: Map unique names to avoid redundant processing
        unique_names = df["Internal_Name"].unique()
        name_cat_map = {name: get_category(name) for name in unique_names}
        df["Category"] = df["Internal_Name"].map(name_cat_map)
        df["Total Amount"] = df["Internal_Cost"] * df["Internal_Qty"]

        others = df[df["Category"] == "Others"]
        if len(others) > 0:
            log_system_event(
                "OTHERS_LOG",
                {
                    "count": len(others),
                    "samples": others["Internal_Name"].head(10).tolist(),
                },
            )

        summary = (
            df.groupby("Category")
            .agg({"Internal_Qty": "sum", "Total Amount": "sum"})
            .reset_index()
        )
        summary.columns = ["Category", "Total Qty", "Total Amount"]

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

        drilldown = (
            df.groupby(["Category", "Internal_Cost"])
            .agg({"Internal_Qty": "sum", "Total Amount": "sum"})
            .reset_index()
        )
        drilldown.columns = ["Category", "Price (TK)", "Total Qty", "Total Amount"]

        top_items = (
            df.groupby("Internal_Name")
            .agg({"Internal_Qty": "sum", "Total Amount": "sum", "Category": "first"})
            .reset_index()
        )
        top_items.columns = ["Product Name", "Total Qty", "Total Amount", "Category"]
        top_items = top_items.sort_values("Total Amount", ascending=False)

        basket_metrics = {"avg_basket_qty": 0, "avg_basket_value": 0, "total_orders": 0}
        group_cols = []
        if "order_id" in selected_cols and selected_cols["order_id"] in df.columns:
            group_cols.append(selected_cols["order_id"])
        if "phone" in selected_cols and selected_cols["phone"] in df.columns:
            group_cols.append(selected_cols["phone"])

        if group_cols:
            order_groups = df.groupby(group_cols).agg(
                {"Internal_Qty": "sum", "Total Amount": "sum"}
            )
            basket_metrics["avg_basket_qty"] = order_groups["Internal_Qty"].mean()
            basket_metrics["avg_basket_value"] = order_groups["Total Amount"].mean()
            basket_metrics["total_orders"] = len(order_groups)

        return drilldown, summary, top_items, timeframe_suffix, basket_metrics
    except Exception as e:
        log_system_event("CRASH", str(e))
        st.error(f"Error in calculation: {e}")
        return None, None, None, "", {}


@st.cache_data(show_spinner=False)
def read_sales_file(file_obj, file_name):
    """Reads CSV/XLSX from uploader, file path, or bytes buffer."""
    if str(file_name).lower().endswith(".csv"):
        return pd.read_csv(file_obj)
    return pd.read_excel(file_obj)


@st.cache_data(ttl=60, show_spinner=False)
def load_from_woocommerce():
    """Loads live data from WooCommerce REST API orders."""
    # Check for nested [woocommerce] in st.secrets (from secrets.toml)
    wc_info = {}
    try:
        wc_info = st.secrets.get("woocommerce", {})
    except Exception:
        pass

    # Support both nested [woocommerce] table and top-level keys/env vars
    wc_url = wc_info.get("store_url") or get_setting("WC_URL")
    wc_key = wc_info.get("consumer_key") or get_setting("WC_KEY")
    wc_secret = wc_info.get("consumer_secret") or get_setting("WC_SECRET")

    if not wc_url or not wc_key or not wc_secret:
        raise ValueError(
            "WooCommerce integration requires WC_URL, WC_KEY, and WC_SECRET (or [woocommerce] table in secrets.toml)."
        )

    # Unified WooCommerce API fetching with multi-page support
    endpoint = f"{wc_url.rstrip('/')}/wp-json/wc/v3/orders"
    rows = []
    
    try:
        from datetime import timezone, timedelta
        tz_bd = timezone(timedelta(hours=6))
        
        # Determine pulling window based on user selection in session state
        sync_mode = st.session_state.get("wc_sync_mode", "Operational Cycle")
        
        params = {
            "per_page": 100,
            "status": "processing,completed,shipped",
            "orderby": "date",
            "order": "desc"
        }

        def get_operational_sync_window(ref_time):
            # Thursday 5:30 PM to Saturday 5:30 PM is the weekend slot (Bangladesh)
            anchor_5_30pm = ref_time.replace(hour=17, minute=30, second=0, microsecond=0)
            
            # RULE: Active shift starts yesterday 5:30 PM and stays active until MIDNIGHT TONIGHT
            start = anchor_5_30pm - timedelta(days=1)
            
            # Weekend adjustment: Friday is covered by the Thu-Sat slot
            if start.weekday() == 4: # Friday
                start -= timedelta(days=1) # Back to Thu 17:30
            
            # The window for fetch needs to be broad enough to capture the entire active shift
            # We set end to TONIGHT 23:59:59 to capture evening orders
            end = ref_time.replace(hour=23, minute=59, second=59, microsecond=0)
            return start, end

        # Specialized Fetching Strategy for Operational Cycle
        if sync_mode == "Operational Cycle":
            now_bd = datetime.now(tz_bd)
            curr_start, curr_end = get_operational_sync_window(now_bd)
            prev_start, prev_end = get_operational_sync_window(curr_start - timedelta(seconds=1))
            
            # Request 1: All relevant statuses within the broad operational window
            # (since prev_start, to catch both current and previous slots)
            # Request: Broad operational pool (From Previous Slot start until NOW)
            # This ensures both yesterday's snapshot and today's active window stay populated.
            params["after"] = prev_start.isoformat()
            params["before"] = now_bd.replace(hour=23, minute=59, second=59).isoformat()
            params["status"] = "processing,completed,shipped,on-hold,pending"
            
            # Fetch Batch 1 (Window based)
            def fetch_batch(p):
                b_rows = []
                page = 1
                while True:
                    r = requests.get(endpoint, params={**p, "page": page}, auth=HTTPBasicAuth(wc_key, wc_secret), timeout=15)
                    r.raise_for_status()
                    batch_data = r.json()
                    if not batch_data: break
                    for order in batch_data:
                        oid, d_val, status = order.get("id"), order.get("date_created"), order.get("status")
                        bill = order.get("billing", {})
                        ship = order.get("shipping", {})
                        c_name = f"{bill.get('first_name','')} {bill.get('last_name','')}".strip()
                        pmt = order.get("payment_method_title", "")
                        for item in order.get("line_items", []):
                            b_rows.append({
                                "Order ID": oid, 
                                "Order Date": d_val, 
                                "Order Status": status, 
                                "Full Name (Billing)": c_name, 
                                "Phone (Billing)": bill.get("phone",""),
                                "Shipping Address 1": ship.get("address_1", ""),
                                "Shipping City": ship.get("city", ""),
                                "State Name (Billing)": bill.get("state", ""),
                                "Item Name": item.get("name"), 
                                "SKU": item.get("sku", ""),
                                "Item Cost": item.get("price"), 
                                "Quantity": item.get("quantity"), 
                                "Order Total Amount": order.get("total"),
                                "Payment Method Title": pmt
                            })
                    if len(batch_data) < 100: break
                    page += 1
                return b_rows

            rows = fetch_batch(params)

            # Request 2: Global Open Orders (On-Hold & Pending/Waiting) Regardless of date
            # To catch "hold order time is from any time" and "waiting orders from any time"
            global_params = {
                "per_page": 100,
                "status": "on-hold,pending",
                "orderby": "date",
                "order": "desc"
            }
            global_rows = fetch_batch(global_params)
            
            # Merge and deduplicate by Order ID + Item Name (to avoid double counting if they overlap in the window)
            # Efficiently merging two lists of dicts
            seen_items = set()
            merged_rows = []
            for r in rows + global_rows:
                key = (r["Order ID"], r["Item Name"])
                if key not in seen_items:
                    merged_rows.append(r)
                    seen_items.add(key)
            rows = merged_rows

        else: # Custom Range mode
            start_date = st.session_state.get("wc_sync_start_date", datetime.now().date())
            start_time = st.session_state.get("wc_sync_start_time", (datetime.now() - timedelta(hours=12)).time())
            end_date = st.session_state.get("wc_sync_end_date", datetime.now().date())
            end_time = st.session_state.get("wc_sync_end_time", datetime.now().time())
            params["after"] = f"{start_date}T{start_time.strftime('%H:%M:%S')}"
            params["before"] = f"{end_date}T{end_time.strftime('%H:%M:%S')}"
            params["status"] = "processing,completed,shipped,on-hold,pending"
            
            page = 1
            while True:
                r = requests.get(endpoint, params={**params, "page": page}, auth=HTTPBasicAuth(wc_key, wc_secret), timeout=15)
                r.raise_for_status()
                batch_data = r.json()
                if not batch_data: break
                for order in batch_data:
                    oid, d_val, status = order.get("id"), order.get("date_created"), order.get("status")
                    bill = order.get("billing", {})
                    ship = order.get("shipping", {})
                    c_name = f"{bill.get('first_name','')} {bill.get('last_name','')}".strip()
                    pmt = order.get("payment_method_title", "")
                    for item in order.get("line_items", []):
                        rows.append({
                            "Order ID": oid, 
                            "Order Date": d_val, 
                            "Order Status": status, 
                            "Full Name (Billing)": c_name, 
                            "Phone (Billing)": bill.get("phone",""),
                            "Shipping Address 1": ship.get("address_1", ""),
                            "Shipping City": ship.get("city", ""),
                            "State Name (Billing)": bill.get("state", ""),
                            "Item Name": item.get("name"), 
                            "SKU": item.get("sku", ""),
                            "Item Cost": item.get("price"), 
                            "Quantity": item.get("quantity"), 
                            "Order Total Amount": order.get("total"),
                            "Payment Method Title": pmt
                        })
                if len(batch_data) < 100: break
                page += 1

        df_full = pd.DataFrame(rows)
        if df_full.empty:
            return pd.DataFrame(), "woocommerce_api", "N/A"

        # Local partitioning for Operational Cycles (v9.8 Refined Rules)
        if sync_mode == "Operational Cycle":
            df_full["dt_parsed"] = pd.to_datetime(df_full["Order Date"], errors="coerce").dt.tz_localize(None)
            
            now_bd = datetime.now(tz_bd)
            ref_now = now_bd.replace(tzinfo=None)
            
            # THE ANCHOR: Today's 17:30 Cutoff
            cutoff_today = ref_now.replace(hour=17, minute=30, second=0, microsecond=0)
            
            # THE START OF THE CURRENT ACTIVE SLOT (Last Day 17:30)
            prev_cutoff = cutoff_today - timedelta(days=1)
            
            # WEEKEND RULE: On Saturday, the active shift started Thursday 17:30
            if now_bd.weekday() == 5: # Saturday
                prev_cutoff = cutoff_today - timedelta(days=2) # Thu 17:30 -> Sat 17:30
                
            # THE PREVIOUS HISTORICAL SLOT (Used for "Prev" tab and deltas)
            day_before_prev = prev_cutoff - timedelta(days=1)
            
            # SUNDAY EXCEPTION: Previous Day Sales is Thursday 5:30 PM to Saturday 5:30 PM
            if now_bd.weekday() == 6: # Sunday
                prev_cutoff = cutoff_today - timedelta(days=1) # Sat 17:30
                day_before_prev = prev_cutoff - timedelta(days=2) # Thu 17:30
            
            # Define Status Categories
            is_shipped = df_full["Order Status"].isin(["completed", "shipped"])
            is_processing = df_full["Order Status"] == "processing"
            is_hold = df_full["Order Status"] == "on-hold"
            is_waiting = df_full["Order Status"] == "pending"
            
            # REFINED CUTOFFS
            shipped_limit = cutoff_today + timedelta(minutes=30)
            proc_limit = cutoff_today + timedelta(minutes=15)
            
            # SNAPSHOT 1: TODAY (Active Shift - Now includes intake)
            df_live = df_full[
                ( (df_full["dt_parsed"] >= prev_cutoff) & (df_full["dt_parsed"] <= shipped_limit) & (is_shipped | is_waiting) ) |
                ( is_processing & (df_full["dt_parsed"] <= proc_limit) )
            ].copy()
            
            # SNAPSHOT 2: YESTERDAY (Historical Performance)
            df_prev = df_full[
                (df_full["dt_parsed"] >= day_before_prev) & 
                (df_full["dt_parsed"] < prev_cutoff) & 
                is_shipped
            ].copy()

            # SNAPSHOT 3: BACKLOG (Hold + Waiting + Late Ops)
            df_backlog = df_full[
                is_hold | is_waiting | 
                (is_processing & (df_full["dt_parsed"] > proc_limit))
            ].copy()
            
            # v9.8 Selective Slot Return
            current_hour = now_bd.hour
            if 0 <= current_hour < 6:
                df_to_return = df_backlog
                slot_label = "Backlog"
            else:
                df_to_return = df_live
                slot_label = "Today"
        else:
            df_to_return = df_full
            slot_label = "Custom"
            df_live, df_prev, df_backlog = None, None, None
            prev_cutoff, cutoff_today, day_before_prev = None, None, None

        df_to_return = scrub_raw_dataframe(df_to_return)
        
        # Package results for caller to handle session state (v9.8 Stateless Cache)
        results = {
            "df_to_return": df_to_return,
            "sync_desc": f"WooCommerce_{slot_label}_API_{len(df_to_return)}_Orders",
            "modified_at": datetime.now(tz_bd).strftime("%Y-%m-%d %H:%M:%S"),
            "partitions": {
                "wc_curr_df": scrub_raw_dataframe(df_live) if df_live is not None else None,
                "wc_prev_df": scrub_raw_dataframe(df_prev) if df_prev is not None else None,
                "wc_backlog_df": scrub_raw_dataframe(df_backlog) if df_backlog is not None else None,
            },
            "slots": {
                "wc_curr_slot": (prev_cutoff, cutoff_today) if prev_cutoff else None,
                "wc_prev_slot": (day_before_prev, prev_cutoff) if day_before_prev else None,
                "wc_backlog_slot": (cutoff_today, cutoff_today + timedelta(days=1)) if cutoff_today else None,
            }
        }
        return results

    except Exception as e:
        log_system_event("WC_API_ERROR", str(e))
        raise RuntimeError(f"Failed to fetch data from WooCommerce: {e}")


def load_live_source():
    """Stateless fetch with stateful session update."""
    results = load_from_woocommerce()
    if results and isinstance(results, dict):
        # 1. Update Partitioned State
        partitions = results.get("partitions", {})
        for key, df in partitions.items():
            if df is not None:
                st.session_state[key] = df
        
        # 2. Update Slot Metadata
        slots = results.get("slots", {})
        for key, val in slots.items():
            if val is not None:
                st.session_state[key] = val
        
        # 3. Update Sync Metadata
        st.session_state.live_sync_time = datetime.now()
        
        # 4. Return tuple for legacy unpacking
        return results["df_to_return"], results["sync_desc"], results["modified_at"]
    
    # Handle legacy return if any (for safety)
    if results:
        st.session_state.live_sync_time = datetime.now()
        return results
        
    raise ValueError("Failed to load WooCommerce live data.")


def get_items_sold_label(last_updated):
    from datetime import datetime, timedelta, timezone

    tz_bd = timezone(timedelta(hours=6))
    try:
        if (
            isinstance(last_updated, str)
            and last_updated != "N/A"
            and "snapshot" not in last_updated.lower()
        ):
            dt = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
            # Assume last updated time string is already in local tz
            if dt.hour < 16:
                return "Items to be sold"
    except Exception:
        pass

    if datetime.now(tz_bd).hour < 16:
        return "Items to be sold"
    return "Item sold"





def render_dashboard_output(
    drill, summ, top, timeframe, basket, source_name, last_updated="N/A"
):
    """Renders common dashboard widgets/charts/tables/export."""
    # Welcome Insights Popup removed as requested

    # v9.6 Unified Metrics Intelligence Engine
    if st.session_state.get("wc_sync_mode") == "Operational Cycle":
        nav_mode = st.session_state.get("wc_nav_mode", "Today")
        
        # Select active datasets
        m_df = None
        c_df = None
        
        if nav_mode == "Prev":
            m_df = st.session_state.get("wc_prev_df")
            c_df = st.session_state.get("wc_curr_df")
        elif nav_mode == "Backlog":
            m_df = st.session_state.get("wc_backlog_df")
            # No comparison for backlog
        else: # Today
            m_df = st.session_state.get("wc_curr_df")
            c_df = st.session_state.get("wc_prev_df")
            
        if m_df is not None:
            # 1. Main Metrics
            m_qty = m_df["Quantity"].sum()
            m_rev = (m_df["Quantity"] * m_df["Item Cost"]).sum()
            m_ord = m_df["Order ID"].nunique()
            m_bv = (m_rev / m_ord) if m_ord > 0 else 0
            
            # 2. Status Drilldown Intelligence
            is_ship = m_df["Order Status"].isin(["completed", "shipped"])
            is_proc = m_df["Order Status"] == "processing"
            is_hold = m_df["Order Status"] == "on-hold"
            is_wait = m_df["Order Status"] == "pending"
            
            ship_count = m_df[is_ship]["Order ID"].nunique()
            proc_count = m_df[is_proc]["Order ID"].nunique()
            hold_count = m_df[is_hold]["Order ID"].nunique()
            wait_count = m_df[is_wait]["Order ID"].nunique()
            
            # 3. Comparison Metrics
            dq_str, dr_str, do_str, db_str = None, None, None, None
            if c_df is not None and not c_df.empty:
                co_q = c_df["Quantity"].sum()
                co_r = (c_df["Quantity"] * c_df["Item Cost"]).sum()
                co_o = c_df["Order ID"].nunique()
                co_b = (co_r / co_o) if co_o > 0 else 0
                
                # Math: if today, Today-Yesterday. if Yesterday, Today-Yesterday.
                # Actually, always compare current view to the alternative
                prefix = "Today " if nav_mode == "Prev" else ""
                suffix = "" if nav_mode == "Prev" else " vs Prev"
                
                dq, dr, d_o, db = (m_qty-co_q), (m_rev-co_r), (m_ord-co_o), (m_bv-co_b)
                if nav_mode == "Prev": # Compare Yesterday to Today (invert for benchmarking)
                    dq, dr, d_o, db = (co_q-m_qty), (co_r-m_rev), (co_o-m_ord), (co_b-m_bv)
                
                dq_str = f"{prefix}{dq:+,.0f}{suffix}"
                dr_str = f"{prefix}{'+' if dr >= 0 else '-'}TK {abs(dr):,.0f}{suffix}"
                do_str = f"{prefix}{d_o:+,.0f}{suffix}"
                db_str = f"{prefix}{'+' if db >= 0 else '-'}TK {abs(db):,.0f}{suffix}"

            # 3. Render
            
            logo_src = "https://logo.clearbit.com/deencommerce.com"
            try:
                logo_jpg = os.path.join("assets", "deen_logo.jpg")
                if os.path.exists(logo_jpg):
                    with open(logo_jpg, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    logo_src = f"data:image/png;base64,{b64}"
            except Exception:
                pass

            curr_s, curr_e = st.session_state.wc_curr_slot
            prev_s, prev_e = st.session_state.wc_prev_slot
            
            nav_mode = st.session_state.get("wc_nav_mode", "Today")
            
            # Global time intelligence for header context
            now_bd = datetime.now(timezone(timedelta(hours=6)))
            now_mins = now_bd.hour * 60 + now_bd.minute
            is_office_hours = 570 <= now_mins < 1050

            if nav_mode == "Prev":
                title_html = "⏪ <strong>ACTIVE: Yesterday</strong>"
                time_html = f"{prev_s.strftime('%a %d %b, %I:%M %p')} - {prev_e.strftime('%a %d %b, %I:%M %p')}"
                status_html = f"📦 {ship_count} Shipped"
            elif nav_mode == "Backlog":
                title_html = "⏩ <strong>ACTIVE: Incoming Backlog</strong>"
                time_html = f"Waiting / On-Hold / Late Ops"
                status_html = f"⏸️ {hold_count} On-Hold"
                # Show incoming intake in backlog only outside office hours
                if not is_office_hours and wait_count > 0:
                    status_html += f" | 🆕 {wait_count} New"
            else:
                title_html = "📍 <strong>ACTIVE: Today</strong>"
                time_html = f"{curr_s.strftime('%a %d %b, %I:%M %p')} - {curr_e.strftime('%a %d %b, %I:%M %p')}"
                
                status_html = f"📦 {ship_count} Shipped"
                if is_office_hours:
                    status_html += f" | ⚙️ {proc_count} Processing"
                

            sync_label = "Pending"
            if st.session_state.get("live_sync_time"):
                diff = datetime.now() - st.session_state.live_sync_time
                mins = int(diff.total_seconds() / 60)
                sync_label = "Just now" if mins < 1 else f"{mins}m ago"

            # v9.8 Compact Operational Header HTML (Returned for global header injection)
            status_banner_html = f"""
                <div style="background: rgba(128, 128, 128, 0.05); border-radius: 8px; padding: 10px 16px; display: flex; gap: 14px; align-items: center; border: 1px solid rgba(128,128,128,0.1);">
                    <div>
                        <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-color);">{title_html}</div>
                        <div style="font-size: 0.75rem; color: var(--text-color); opacity: 0.8; margin-top:2px;">{time_html}</div>
                    </div>
                    <div style="width: 1px; height: 32px; background: rgba(128,128,128,0.2);"></div>
                    <div style="font-size: 0.9rem; font-weight: 600; color: var(--text-color);">
                        {status_html}
                    </div>
                </div>
            """
            
            # v9.8 Unified Operational Controls
            sync_label = "Pending"
            if st.session_state.get("live_sync_time"):
                diff = datetime.now() - st.session_state.live_sync_time
                mins = int(diff.total_seconds() / 60)
                sync_label = "Just now" if mins < 1 else f"{mins}m ago"
            
            nav_mode = st.session_state.get("wc_nav_mode", "Today")
            st.markdown('<div style="font-size: 0.9rem; font-weight: 600; margin-bottom: 8px; color: #475569;">Operation Mode</div>', unsafe_allow_html=True)
            
            c1, c2, c3, c4 = st.columns([1, 1.2, 1, 2.5])
            with c1:
                if st.button("🕒 History", help="Operational Archive (Yesterday)", type="primary" if nav_mode == "Prev" else "secondary", use_container_width=True):
                    st.session_state.wc_nav_mode = "Prev"
                    st.rerun()
            with c2:
                # UNIFIED TODAY + SYNC
                help_txt = f"Active Shift + Force Sync ({sync_label})"
                if st.button(f"🎯 Active ({sync_label})", help=help_txt, type="primary" if nav_mode == "Today" else "secondary", use_container_width=True):
                    st.session_state.wc_nav_mode = "Today"
                    # Trigger Sync logic
                    try:
                        from app_modules.sales_dashboard import load_from_woocommerce, fetch_woocommerce_stock
                        load_from_woocommerce.clear()
                        fetch_woocommerce_stock.clear()
                    except: pass
                    st.rerun()
            with c3:
                if st.button("📥 Queue", help="Incoming/On-Hold Backlog", type="primary" if nav_mode == "Backlog" else "secondary", use_container_width=True):
                    st.session_state.wc_nav_mode = "Backlog"
                    st.rerun()

            with st.container():
                st.markdown('<div id="snapshot-target-main"></div>', unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    l1 = "Backlog Items" if nav_mode == "Backlog" else "Items sold"
                    st.metric(l1, f"{m_qty:,.0f}", delta=dq_str)
                with col2:
                    l2 = "Backlog Rev" if nav_mode == "Backlog" else "Revenue"
                    st.metric(l2, f"TK {m_rev:,.0f}", delta=dr_str)
                with col3:
                    l3 = "Backlog Orders" if nav_mode == "Backlog" else "Orders"
                    st.metric(l3, f"{m_ord:,.0f}", delta=do_str)
                with col4:
                    st.metric("Avg Basket", f"TK {m_bv:,.0f}", delta=db_str)
            st.divider()

    else:
        # Standard Fallback for non-operational modes
        with st.container():
            st.markdown('<div id="snapshot-target-main"></div>', unsafe_allow_html=True)
            st.subheader("Core Metrics")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(get_items_sold_label(last_updated), f"{summ['Total Qty'].sum():,.0f}")
            total_orders = basket.get("total_orders", 0)
            m2.metric("Number of Orders", f"{total_orders:,.0f}" if total_orders else "-")
            m3.metric("Revenue", f"TK {summ['Total Amount'].sum():,.0f}")
            m4.metric("Basket Value (TK)", f"TK {basket.get('avg_basket_value', 0):,.0f}")
            st.divider()

    st.subheader("Performance Outlook")

    sorted_cats = summ.sort_values("Total Amount", ascending=False)[
        "Category"
    ].tolist()
    color_map = {}
    for i, cat in enumerate(sorted_cats):
        val = (
            (i / max(1, len(sorted_cats) - 1)) * 0.85
            if len(sorted_cats) > 1
            else 0.0
        )
        color_map[cat] = px.colors.sample_colorscale("Plasma", [val])[0]

    v1, v2 = st.columns(2)
    with v1:
        fig_pie = px.pie(
            summ,
            values="Total Amount",
            names="Category",
            color="Category",
            hole=0.6,
            title="Revenue Share (TK)",
            color_discrete_map=color_map,
        )

        if (
            hasattr(fig_pie, "data")
            and len(fig_pie.data) > 0
            and getattr(fig_pie.data[0], "values", None) is not None
        ):
            t_val = sum(fig_pie.data[0].values)
            t_val = t_val if t_val > 0 else 1
            pos_array = [
                "inside" if (v / t_val) >= 0.02 else "none"
                for v in fig_pie.data[0].values
            ]
        else:
            pos_array = "inside"

        fig_pie.update_layout(
            margin=dict(l=10, r=10, t=50, b=10),
            showlegend=False,
            uniformtext_minsize=10,
            uniformtext_mode="hide",
        )
        fig_pie.update_traces(
            textposition=pos_array,
            textinfo="label+percent",
            textfont_size=11,
            pull=0.01,
            rotation=270,
            direction="clockwise",
        )
        st.plotly_chart(
            fig_pie,
            use_container_width=True,
            config={"scrollZoom": True, "displayModeBar": False},
        )

    with v2:
        fig_bar = px.bar(
            summ.sort_values("Total Qty", ascending=False),
            x="Category",
            y="Total Qty",
            color="Category",
            title="Volume by Category",
            text_auto=".0f",
            color_discrete_map=color_map,
        )
        fig_bar.update_traces(showlegend=False)
        fig_bar.update_layout(
            margin=dict(l=50, r=10, t=50, b=40),
            xaxis_title="",
            yaxis_title="Quantity Sold",
            showlegend=False,
        )
        st.plotly_chart(
            fig_bar,
            use_container_width=True,
            config={"scrollZoom": True, "displayModeBar": False},
        )

    # Categories custom html legend removed as requested
    render_snapshot_button("snapshot-target-main")
    st.divider()

    st.subheader("Top Products Spotlight")
    spotlight = top.head(10).sort_values("Total Amount", ascending=True)
    fig_top = px.bar(
        spotlight,
        x="Total Amount",
        y="Product Name",
        orientation="h",
        color="Category",
        title="Top 10 products by revenue",
        text_auto=".2s",
        color_discrete_map=color_map,
    )
    fig_top.update_traces(showlegend=False)
    fig_top.update_layout(
        margin=dict(l=12, r=12, t=50, b=12),
        yaxis_title="",
        xaxis_title="Revenue (TK)",
        showlegend=False,
    )
    st.plotly_chart(
        fig_top,
        use_container_width=True,
        config={"scrollZoom": True, "displayModeBar": False},
    )

    st.subheader("Deep Dive Data")

    tabs = st.tabs(["Summary", "Rankings", "Drilldown"])
    with tabs[0]:
        st.dataframe(
            summ.sort_values("Total Amount", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    with tabs[1]:
        st.dataframe(top.head(20), use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(
            drill.sort_values(["Category", "Price (TK)"]),
            use_container_width=True,
            hide_index=True,
        )

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
        summ.to_excel(wr, sheet_name="Summary", index=False)
        top.to_excel(wr, sheet_name="Rankings", index=False)
        drill.to_excel(wr, sheet_name="Details", index=False)

        # Access workbook for premium formatting
        workbook = wr.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D7E4BC", "border": 1})
        currency_fmt = workbook.add_format({"num_format": "#,##0.00"})
        num_fmt = workbook.add_format({"num_format": "#,##0"})

        for sheet_name in wr.sheets:
            ws = wr.sheets[sheet_name]
            ws.freeze_panes(1, 0)
            # Apply consistent column widths
            ws.set_column(0, 5, 20)
            
            if sheet_name == "Summary":
                ws.set_column("B:B", 15, num_fmt)
                ws.set_column("C:C", 18, currency_fmt)
            elif sheet_name == "Details":
                ws.set_column("B:B", 15, currency_fmt)
                ws.set_column("C:C", 15, num_fmt)

    base_name = os.path.splitext(os.path.basename(source_name))[0]
    file_suffix = f"_{timeframe}" if timeframe else ""
    final_filename = f"Report_{base_name}{file_suffix}.xlsx"
    st.download_button("Export Report", data=buf.getvalue(), file_name=final_filename)


def render_manual_tab():
    def _reset_manual_state():
        st.session_state.manual_generate = False
        st.session_state.manual_df = None

    render_reset_confirm("Sales Data Ingestion", "manual", _reset_manual_state)
    
    st.info("💡 Pull precisely filtered historical data from WooCommerce, upload a local file, or pull from a fallback Google Sheet.")
    src_type = st.radio("Source Type", ["Manual File Upload", "WooCommerce Custom Pull", "Google Sheet Pull"], horizontal=True, key="ingestion_src_type")
    
    df = None
    source_name = ""
    
    if src_type == "Manual File Upload":
        uploaded_file = st.file_uploader("Upload Product Sales File", type=["xlsx", "csv"], key="manual_uploader")
        if uploaded_file:
            df = read_sales_file(uploaded_file, uploaded_file.name)
            source_name = uploaded_file.name
    elif src_type == "Google Sheet Pull":
        st.info("Pulls fallback data from the default published Google Sheet.")
        if st.button("📩 Fetch from Google Sheet", use_container_width=True, type="primary"):
            try:
                with st.spinner("Fetching data from Google Sheet..."):
                    df_res = pd.read_csv(DEFAULT_GSHEET_URL)
                    st.session_state.manual_df = df_res
                    st.session_state.manual_source_name = "Google_Sheet_Export"
                    st.success(f"Successfully ingested {len(df_res)} records.")
            except Exception as e:
                st.error(f"Failed to fetch from Google Sheet: {e}")
        
        if st.session_state.get("manual_df") is not None and st.session_state.get("manual_source_name") == "Google_Sheet_Export":
            df = st.session_state.manual_df
            source_name = st.session_state.manual_source_name
    elif src_type == "WooCommerce Custom Pull":
        # WooCommerce Custom Pull Logic (Moved from Live Tab)
        with st.expander("🔍 Filtered Data Acquisition", expanded=True):
            st.caption("Specify the exact time window for the data you wish to ingest.")
            c1, c2 = st.columns(2)
            start_date = c1.date_input("Start Date", value=datetime.now().date(), key="ingest_start_d")
            start_time = c1.time_input("Start Time", value=(datetime.now() - timedelta(hours=24)).time(), key="ingest_start_t")
            end_date = c2.date_input("End Date", value=datetime.now().date(), key="ingest_end_d")
            end_time = c2.time_input("End Time", value=datetime.now().time(), key="ingest_end_t")
            
            if st.button("📩 Fetch & Review Data", use_container_width=True, type="primary"):
                # Temporarily set session state for the fetcher
                st.session_state["wc_sync_mode"] = "Custom Range"
                st.session_state["wc_sync_start_date"] = start_date
                st.session_state["wc_sync_start_time"] = start_time
                st.session_state["wc_sync_end_date"] = end_date
                st.session_state["wc_sync_end_time"] = end_time
                
                try:
                    with st.spinner("Connecting to WooCommerce API..."):
                        # We use load_from_woocommerce directly to get full control
                        df_res, src_res, _ = load_from_woocommerce()
                        if not df_res.empty:
                            st.session_state.manual_df = df_res
                            st.session_state.manual_source_name = src_res
                            st.success(f"Successfully ingested {len(df_res)} records.")
                        else:
                            st.warning("No data found for the selected time range.")
                except Exception as e:
                    st.error(f"Ingestion failed: {e}")
                    st.info("💡 Tip: If WooCommerce is unavailable, switch to 'Google Sheet Pull' to load fallback data.")
        
        if st.session_state.get("manual_df") is not None and st.session_state.get("manual_source_name") != "Google_Sheet_Export":
            df = st.session_state.manual_df
            source_name = st.session_state.get("manual_source_name", "WooCommerce_Custom_Pull")

    if df is None:
        return

    try:
        st.caption(f"Active Data Source: {source_name}")

        auto_cols = find_columns(df)
        all_cols = list(df.columns)

        section_card(
            "Column Mapping",
            "Detected columns are prefilled. Verify before generating dashboard output.",
        )

        def get_col_idx(key):
            if key in auto_cols and auto_cols[key] in all_cols:
                return all_cols.index(auto_cols[key])
            return 0

        mapped_name = st.selectbox(
            "Product Name", all_cols, index=get_col_idx("name"), key="manual_name"
        )
        mapped_cost = st.selectbox(
            "Price/Cost", all_cols, index=get_col_idx("cost"), key="manual_cost"
        )
        mapped_qty = st.selectbox(
            "Quantity", all_cols, index=get_col_idx("qty"), key="manual_qty"
        )
        mapped_date = st.selectbox(
            "Date (Optional)",
            ["None"] + all_cols,
            index=get_col_idx("date") + 1 if "date" in auto_cols else 0,
            key="manual_date",
        )
        mapped_order = st.selectbox(
            "Order ID (Optional)",
            ["None"] + all_cols,
            index=get_col_idx("order_id") + 1 if "order_id" in auto_cols else 0,
            key="manual_order",
        )
        mapped_phone = st.selectbox(
            "Phone (Optional)",
            ["None"] + all_cols,
            index=get_col_idx("phone") + 1 if "phone" in auto_cols else 0,
            key="manual_phone",
        )

        final_mapping = {
            "name": mapped_name,
            "cost": mapped_cost,
            "qty": mapped_qty,
            "date": mapped_date if mapped_date != "None" else None,
            "order_id": mapped_order if mapped_order != "None" else None,
            "phone": mapped_phone if mapped_phone != "None" else None,
        }

        with st.expander("Search Raw Data"):
            search = st.text_input("Product search...", key="manual_search")
            if search:
                st.dataframe(
                    df[
                        df[mapped_name]
                        .astype(str)
                        .str.contains(search, case=False, na=False)
                    ],
                    use_container_width=True,
                )
            else:
                st.dataframe(df.head(10), use_container_width=True)

        generate_clicked, _ = render_action_bar("Generate dashboard", "manual_generate")
        if generate_clicked:
            drill, summ, top, timeframe, basket = process_data(df, final_mapping)
            if drill is not None:
                manual_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                render_dashboard_output(
                    drill,
                    summ,
                    top,
                    timeframe,
                    basket,
                    source_name,
                    manual_updated,
                )

    except Exception as e:
        log_system_event("FILE_ERROR", str(e))
        st.error(f"File error: {e}")


def render_live_tab():
    def _reset_live_state():
        st.session_state.wc_curr_df = None
        st.session_state.wc_prev_df = None
        st.session_state.live_sync_time = None
        st.session_state.wc_view_historical = False
        st.session_state.wc_sync_mode = "Operational Cycle"

    render_reset_confirm("Live Dashboard", "live", _reset_live_state)
    """Always running dashboard from selected source."""
    tz_bd = timezone(timedelta(hours=6))
    current_t = datetime.now(tz_bd).strftime("%B %d, %Y %I:%M %p")
    # logo_src logically moved to render_dashboard_output

    # Use global imports
    tz_bd = timezone(timedelta(hours=6))

    # Force Operational Cycle in live dashboard
    st.session_state["wc_sync_mode"] = "Operational Cycle"

    # Standardize autorefresh for Live Dashboard

    try:
        df_live, source_name, modified_at = load_live_source()

        # Handle v9.5 Multi-Mode Shift Navigation
        nav_mode = st.session_state.get("wc_nav_mode", "Today")
        if nav_mode == "Prev" and "wc_prev_df" in st.session_state:
            df_live = st.session_state.wc_prev_df
            p_s, p_e = st.session_state.get("wc_prev_slot", (datetime.now(), datetime.now()))
            source_name = f"PREV_SLOT_{p_s.strftime('%a_%d%b')}"
            modified_at = "HISTORICAL_SNAPSHOT"
        elif nav_mode == "Backlog" and "wc_backlog_df" in st.session_state:
            df_live = st.session_state.wc_backlog_df
            b_s, b_e = st.session_state.get("wc_backlog_slot", (datetime.now(), datetime.now()))
            source_name = f"INCOMING_BATCH_{b_s.strftime('%H:%M')}"
            modified_at = "BACKLOG_QUEUE"
        elif nav_mode == "Today" and "wc_curr_df" in st.session_state:
            df_live = st.session_state.wc_curr_df
            # default df_live from load_live_source is already the current one
            
        if df_live is None or df_live.empty:
            st.warning(f"No data found for the {nav_mode} slot.")
            # Fallback to Today if we were in another mode
            if nav_mode != "Today":
                st.session_state.wc_nav_mode = "Today"
                st.rerun()

        auto_cols = find_columns(df_live)
        missing_required = [k for k in ["name", "cost", "qty"] if k not in auto_cols]
        if missing_required:
            st.error(f"Cannot auto-map required columns: {', '.join(missing_required)}")
            st.dataframe(df_live.head(20), use_container_width=True)
            return

        live_mapping = {
            "name": auto_cols.get("name"),
            "cost": auto_cols.get("cost"),
            "qty": auto_cols.get("qty"),
            "date": auto_cols.get("date"),
            "order_id": auto_cols.get("order_id"),
            "phone": auto_cols.get("phone"),
        }

        drill, summ, top, timeframe, basket = process_data(df_live, live_mapping)
        if drill is not None:
            render_dashboard_output(
                drill, summ, top, timeframe, basket, source_name, modified_at
            )

    except Exception as e:
        log_system_event("LIVE_FILE_ERROR", str(e))
        st.error(f"Live source error: {e}")
        st.info("💡 Tip: If WooCommerce is down, use the '📥 Sales Data Ingestion' tab to pull fallback data from Google Sheets.")


@st.cache_data(ttl=600)
def fetch_woocommerce_stock(filter_skus=None, filter_titles=None):
    """Fetches real-time stock levels for published items using Expert Rules."""
    wc_info = st.secrets.get("woocommerce", {})
    wc_url = wc_info.get("store_url") or os.environ.get("WC_URL")
    wc_key = wc_info.get("consumer_key") or os.environ.get("WC_KEY")
    wc_secret = wc_info.get("consumer_secret") or os.environ.get("WC_SECRET")

    if not wc_url or not wc_key or not wc_secret:
        st.error("WooCommerce credentials missing.")
        return None

    auth = HTTPBasicAuth(wc_key, wc_secret)
    base_endpoint = f"{wc_url.rstrip('/')}/wp-json/wc/v3/products"
    stock_data = []

    def fetch_variations(p_id, p_name):
        try:
            v_r = requests.get(f"{base_endpoint}/{p_id}/variations", params={"per_page": 100, "status": "publish"}, auth=auth, timeout=15)
            if v_r.status_code == 200:
                results = []
                for v in v_r.json():
                    if v.get("status", "publish") != "publish":
                        continue
                    full_name = f"{p_name} - {v.get('attributes',[{}])[0].get('option','N/A')}"
                    results.append({
                        "Category": get_category(p_name),
                        "Product": full_name,
                        "SKU": v.get("sku") or f"P{p_id}-V{v.get('id')}",
                        "Stock": v.get("stock_quantity") if v.get("manage_stock") else 0,
                        "Price": v.get("price", "0"),
                        "Status": v.get("stock_status", "unknown").title()
                    })
                return results
        except Exception:
            pass
        return []

    try:
        page = 1
        all_products = []
        with st.spinner("📦 Fetching published inventory..."):
            while True:
                r = requests.get(
                    base_endpoint,
                    params={
                        "per_page": 100, 
                        "page": page, 
                        "status": "publish"
                    },
                    auth=auth,
                    timeout=25
                )
                r.raise_for_status()
                products = r.json()
                if not products: break
                all_products.extend(products)
                if len(products) < 100: break
                page += 1

        # Identify variable products for parallel processing
        variable_tasks = []
        for p in all_products:
            p_id, p_name = p.get("id"), p.get("name")
            p_type = p.get("type", "simple")
            
            if p_type == "variable":
                # Apply filter logic if provided
                if filter_skus or filter_titles:
                    p_sku_norm = (p.get("sku") or "").strip().lower()
                    p_name_norm = p.get("name", "").strip().lower()
                    is_relevant = False
                    if filter_skus and (p_sku_norm in filter_skus): is_relevant = True
                    if filter_titles and (p_name_norm in filter_titles): is_relevant = True
                    if not is_relevant and filter_skus and p_sku_norm:
                        for ts in filter_skus:
                            if ts.lower().startswith(p_sku_norm):
                                is_relevant = True
                                break
                    if not is_relevant: continue
                variable_tasks.append((p_id, p_name))
            else:
                stock_data.append({
                    "Category": get_category(p_name),
                    "Product": p_name,
                    "SKU": p.get("sku") or f"P{p_id}",
                    "Stock": p.get("stock_quantity") if p.get("manage_stock") else 0,
                    "Price": p.get("price", "0"),
                    "Status": p.get("stock_status", "unknown").title()
                })

        # Concurrent Variation Fetching
        if variable_tasks:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(fetch_variations, tid, tname): (tid, tname) for tid, tname in variable_tasks}
                for future in as_completed(futures):
                    res = future.result()
                    if res:
                        stock_data.extend(res)

        df = pd.DataFrame(stock_data)
        if not df.empty:
            df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").fillna(0).astype(int)
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0)
            # User requested "Just Pull Published Items", so we show all regardless of stock level
        return df

    except Exception as e:
        log_system_event("STOCK_SYNC_ERROR", str(e))
        st.error(f"Stock fetch failed: {e}")
        return None



def render_stock_analytics_tab():
    """Renders the category-wise stock monitoring interface."""
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📦 Current Stock Analytics")
    
    col_sync, col_info = st.columns([1, 4])
    with col_sync:
        if st.button("🔄 Force Re-Sync", use_container_width=True, type="primary"):
            st.session_state.wc_stock_df = fetch_woocommerce_stock()
            st.session_state.stock_sync_time = datetime.now()
            st.rerun()

    # Automatically trigger fetch on first load if missing
    if "wc_stock_df" not in st.session_state or st.session_state.wc_stock_df is None:
        st.session_state.wc_stock_df = fetch_woocommerce_stock()
        st.session_state.stock_sync_time = datetime.now()
        if st.session_state.wc_stock_df is not None:
            st.rerun()

    if "wc_stock_df" not in st.session_state or st.session_state.wc_stock_df is None:
        st.info("Directly pull real-time inventory levels by Shift-Category rules.")
        return

    df = st.session_state.wc_stock_df
    if df is None or df.empty:
        st.warning("No in-stock items found.")
        return

    # Stock Summary by Shift-Category
    st.divider()
    
    total_qty = df["Stock"].sum()
    low_stock = df[df["Stock"] < 10].shape[0]
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Items in Stock", f"{total_qty:,.0f}")
    k2.metric("Low Stock Alerts", low_stock, delta="Action Needed" if low_stock > 0 else None, delta_color="inverse")
    k3.metric("Mapped Categories", df["Category"][df["Category"] != "Uncategorized"].nunique())

    # Category Volume Table
    st.subheader("Inventory by Product Category")
    cat_summ = df.groupby("Category")["Stock"].sum().reset_index()
    cat_summ = cat_summ.sort_values("Stock", ascending=False)
    
    v1, v2 = st.columns([2, 3])
    with v1:
        st.dataframe(cat_summ, use_container_width=True, hide_index=True, column_config={"Stock": st.column_config.NumberColumn(format="%d")})
    with v2:
        fig = px.bar(cat_summ.head(15), x="Stock", y="Category", orientation="h", title="Top 15 Categories by Volume", color="Stock", color_continuous_scale="Viridis")
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    # Search & Filter
    st.divider()
    st.subheader("Granular Stock Details")
    search = st.text_input("🔍 Filter by Product Name, SKU, or Category", "").strip().lower()
    
    filtered_df = df.copy()
    if search:
        filtered_df = filtered_df[
            filtered_df["Product"].str.lower().str.contains(search) | 
            filtered_df["SKU"].str.lower().str.contains(search) |
            filtered_df["Category"].str.lower().str.contains(search)
        ]

    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Stock": st.column_config.NumberColumn(format="%d"),
            "Price": st.column_config.NumberColumn(format="TK %.0f")
        }
    )
    
    st.caption(f"Database last refreshed: {st.session_state.get('stock_sync_time', datetime.now()).strftime('%I:%M %p')}")
    st.markdown('</div>', unsafe_allow_html=True)
