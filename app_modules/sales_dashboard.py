import re
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
DEFAULT_GSHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOiRkybNzMNvEaLxSFsX0nGIiM07BbNVsBbsX1dG8AmGOmSu8baPrVYL0cOqoYN4tRWUj1UjUbH1Ij/pub?gid=2118542421&single=true&output=csv"
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


def get_category(name):
    """Categorizes products based on keywords in their names (v9.5 Expert Rules)."""
    name_str = str(name).lower()

    def has_any(keywords, text):
        return any(
            re.search(rf"\b{re.escape(kw.lower())}\b", text, re.IGNORECASE)
            for kw in keywords
        )

    specific_cats = {
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

    for cat, keywords in specific_cats.items():
        if has_any(keywords, name_str):
            return cat

    fs_keywords = ["full sleeve", "long sleeve", "fs", "l/s"]
    if has_any(["t-shirt", "t shirt", "tee"], name_str):
        return "FS T-Shirt" if has_any(fs_keywords, name_str) else "HS T-Shirt"

    if has_any(["shirt"], name_str):
        return "FS Shirt" if has_any(fs_keywords, name_str) else "HS Shirt"

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

    # 2. Heuristic: If a row has extremely few non-null values compared to the max, it's likely a summary or title
    # We'll keep rows that have at least 30% of the columns filled
    min_threshold = max(1, int(len(df.columns) * 0.3))
    df = df.dropna(thresh=min_threshold)

    # 3. Filter out rows containing common summary keywords in any column
    summary_keywords = [
        "total",
        "grand total",
        "summary",
        "analytics",
        "chart",
        "metric",
    ]
    mask = (
        df.stack()
        .astype(str)
        .str.lower()
        .str.contains("|".join(summary_keywords))
        .unstack()
        .any(axis=1)
    )
    # Only drop if the row is mostly text (summary rows) - be careful not to drop product names with "total"
    # Actually, a better indicator of summary rows is that they are sparse.
    # Let's stick to sparsity and dropping based on ID if we have it later.

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

        df["Category"] = df["Internal_Name"].apply(get_category)
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
            # Thursday 5 PM to Saturday 5 PM is the weekend slot (Bangladesh)
            anchor_5pm = ref_time.replace(hour=17, minute=0, second=0, microsecond=0)
            
            # RULE: Active shift starts yesterday 5 PM and stays active until MIDNIGHT TONIGHT
            start = anchor_5pm - timedelta(days=1)
            
            # Weekend adjustment: Friday is covered by the Thu-Sat slot
            if start.weekday() == 4: # Friday
                start -= timedelta(days=1) # Back to Thu 17:00
            
            # The window for fetch needs to be broad enough to capture the entire active shift
            # We set end to TONIGHT 23:59:59 to capture evening orders
            end = ref_time.replace(hour=23, minute=59, second=59, microsecond=0)
            return start, end

        # Specialized Fetching Strategy for Operational Cycle
        if sync_mode == "Operational Cycle":
            now_bd = datetime.now(tz_bd)
            curr_start, curr_end = get_operational_sync_window(now_bd)
            prev_start, prev_end = get_operational_sync_window(curr_start - timedelta(seconds=1))
            st.session_state.wc_curr_slot = (curr_start, curr_end)
            st.session_state.wc_prev_slot = (prev_start, prev_end)
            
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
                        c_name = f"{bill.get('first_name','')} {bill.get('last_name','')}".strip()
                        for item in order.get("line_items", []):
                            b_rows.append({"Order ID": oid, "Order Date": d_val, "Order Status": status, "Full Name (Billing)": c_name, "Phone (Billing)": bill.get("phone",""), "Item Name": item.get("name"), "Item Cost": item.get("price"), "Quantity": item.get("quantity"), "Order Total Amount": item.get("total")})
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
                    c_name = f"{bill.get('first_name','')} {bill.get('last_name','')}".strip()
                    for item in order.get("line_items", []):
                        rows.append({"Order ID": oid, "Order Date": d_val, "Order Status": status, "Full Name (Billing)": c_name, "Phone (Billing)": bill.get("phone",""), "Item Name": item.get("name"), "Item Cost": item.get("price"), "Quantity": item.get("quantity"), "Order Total Amount": item.get("total")})
                if len(batch_data) < 100: break
                page += 1

        df_full = pd.DataFrame(rows)
        if df_full.empty:
            return pd.DataFrame(), "woocommerce_api", "N/A"

        # Local partitioning for Operational Cycles (v9.5 Rule Set)
        if sync_mode == "Operational Cycle":
            df_full["dt_parsed"] = pd.to_datetime(df_full["Order Date"], errors="coerce").dt.tz_localize(None)
            
            # Classification based on 17:00 CUTOFF
            now_dt = datetime.now()
            cutoff_today = now_dt.replace(hour=17, minute=0, second=0, microsecond=0)
            cutoff_prev = cutoff_today - timedelta(days=1)
            cutoff_day_before = cutoff_prev - timedelta(days=1)
            
            # Define Status Categories
            is_shipped = df_full["Order Status"].isin(["completed", "shipped"])
            is_processing = df_full["Order Status"] == "processing"
            is_hold = df_full["Order Status"] == "on-hold"
            is_waiting = df_full["Order Status"] == "pending"
            
            # SNAPSHOT 1: TODAY (Active Shift - v9.6 Standard)
            # Rule: ALL Waiting (Pending) & Confirmed (Processing) + Recent Shipped
            df_live = df_full[
                (is_waiting | is_processing) | # All Waiting/Confirmed
                ( (df_full["dt_parsed"] >= cutoff_prev.replace(tzinfo=None)) & is_shipped ) | # Shipped in current window
                ( (df_full["dt_parsed"] >= cutoff_today.replace(tzinfo=None)) & is_shipped ) # Shipped post-cutoff today
            ].copy()
            st.session_state.wc_curr_df = scrub_raw_dataframe(df_live)
            
            # SNAPSHOT 2: YESTERDAY (Historical Performance)
            # Status: Shipped orders from Day-before-Yesterday 5 PM to Yesterday 5 PM
            df_prev = df_full[
                (df_full["dt_parsed"] >= cutoff_day_before) & 
                (df_full["dt_parsed"] < cutoff_prev) & 
                is_shipped
            ].copy()
            st.session_state.wc_prev_df = scrub_raw_dataframe(df_prev)

            # SNAPSHOT 3: BACKLOG (Tomorrow's Intake - v9.6 Standard)
            # Rule: ALL Hold orders exclusively
            df_backlog = df_full[
                is_hold
            ].copy()
            st.session_state.wc_backlog_df = scrub_raw_dataframe(df_backlog)
            
            # Persist slots for label indexing
            st.session_state.wc_curr_slot = (cutoff_prev, cutoff_today)
            st.session_state.wc_prev_slot = (cutoff_day_before, cutoff_prev)
            st.session_state.wc_backlog_slot = (cutoff_today, cutoff_today + timedelta(days=1))
        else:
            df_live = df_full
            st.session_state.wc_curr_df = None # Not used

        df_live = scrub_raw_dataframe(df_live)
        
        sync_desc = f"WooCommerce_API_{len(df_live)}_Orders"
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return df_live, sync_desc, modified_at

    except Exception as e:
        log_system_event("WC_API_ERROR", str(e))
        raise RuntimeError(f"Failed to fetch data from WooCommerce: {e}")


def load_live_source():
    """Always use WooCommerce as live source."""
    res = load_from_woocommerce()
    if res:
        st.session_state.live_sync_time = datetime.now()
        return res
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
            
            # 2. Comparison Metrics
            dq_str, dr_str, do_str, db_str = None, None, None, None
            if c_df is not None and not c_df.empty:
                co_q = c_df["Quantity"].sum()
                co_r = (c_df["Quantity"] * c_df["Item Cost"]).sum()
                co_o = c_df["Order ID"].nunique()
                co_b = (co_r / co_o) if co_o > 0 else 0
                
                # Deltas
                prefix = "Today " if nav_mode == "Prev" else ""
                suffix = "" if nav_mode == "Prev" else " vs Prev"
                
                # Math: if today, Today-Yesterday. if Yesterday, Today-Yesterday.
                # Actually, always compare current view to the alternative
                dq, dr, d_o, db = (m_qty-co_q), (m_rev-co_r), (m_ord-co_o), (m_bv-co_b)
                if nav_mode == "Prev": # Compare Yesterday to Today (invert for benchmarking)
                    dq, dr, d_o, db = (co_q-m_qty), (co_r-m_rev), (co_o-m_ord), (co_b-m_bv)
                
                dq_str = f"{prefix}{dq:+,.0f}{suffix}"
                dr_str = f"{prefix}{'+' if dr >= 0 else '-'}TK {abs(dr):,.0f}{suffix}"
                do_str = f"{prefix}{d_o:+,.0f}{suffix}"
                db_str = f"{prefix}{'+' if db >= 0 else '-'}TK {abs(db):,.0f}{suffix}"

            # 3. Render
            with st.container():
                st.markdown('<div id="snapshot-target-main"></div>', unsafe_allow_html=True)
                col1, col2, col3, col4, col5 = st.columns([1, 1.3, 1, 1.2, 1.8])
                
                with col1:
                    l1 = "Incoming Items" if nav_mode == "Backlog" else "Items sold"
                    st.metric(l1, f"{m_qty:,.0f}", delta=dq_str)
                with col2:
                    l2 = "Potential Rev" if nav_mode == "Backlog" else "Revenue"
                    st.metric(l2, f"TK {m_rev:,.0f}", delta=dr_str)
                with col3:
                    l3 = "Queue Orders" if nav_mode == "Backlog" else "Orders"
                    st.metric(l3, f"{m_ord:,.0f}", delta=do_str)
                with col4:
                    st.metric("Avg Basket", f"TK {m_bv:,.0f}", delta=db_str)
                
                with col5:
                    curr_s, curr_e = st.session_state.wc_curr_slot
                    prev_s, prev_e = st.session_state.wc_prev_slot
                    # Labeling based on v9.5 nav_mode
                    nav_mode = st.session_state.get("wc_nav_mode", "Today")
                    if nav_mode == "Prev":
                        st.caption(f"⏪ **ACTIVE: Yesterday**")
                        st.caption(f"{prev_s.strftime('%a %d %b, %I%p')} - {prev_e.strftime('%a %d %b, %I%p')}")
                    elif nav_mode == "Backlog":
                        st.caption(f"⏩ **ACTIVE: Incoming Backlog**")
                        st.caption(f"Waiting / On-Hold Stock")
                    else:
                        st.caption(f"📍 **ACTIVE: Today**")
                        st.caption(f"{curr_s.strftime('%a %d %b, %I%p')} - {curr_e.strftime('%a %d %b, %I%p')}")
                    st.markdown('<div style="margin-top:2px;"></div>', unsafe_allow_html=True)
                    nav_mode = st.session_state.get("wc_nav_mode", "Today")
                    btn_prev, btn_curr, btn_back = st.columns(3)
                    with btn_prev:
                        if st.button("⏪", help="Yesterday - Operational Recall", type="primary" if nav_mode == "Prev" else "secondary"):
                            st.session_state.wc_nav_mode = "Prev"
                            st.rerun()
                    with btn_curr:
                        if st.button("🏠", help="Today - Active Shift", type="primary" if nav_mode == "Today" else "secondary"):
                            st.session_state.wc_nav_mode = "Today"
                            st.rerun()
                    with btn_back:
                        if st.button("⏩", help="Next - Incoming Backlog", type="primary" if nav_mode == "Backlog" else "secondary"):
                            st.session_state.wc_nav_mode = "Backlog"
                            st.rerun()
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
            title="Revenue Share",
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
            margin=dict(l=80, r=160, t=40, b=40),
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.05,
                font=dict(size=11),
            ),
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
        fig_bar.update_layout(
            margin=dict(l=12, r=12, t=50, b=12),
            xaxis_title="",
            yaxis_title="Quantity Sold",
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                borderwidth=1,
            ),
        )
        st.plotly_chart(
            fig_bar,
            use_container_width=True,
            config={"scrollZoom": True, "displayModeBar": False},
        )

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
    )
    fig_top.update_layout(
        margin=dict(l=12, r=12, t=50, b=12),
        yaxis_title="",
        xaxis_title="Revenue (TK)",
        legend_title="Category",
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
    
    st.info("💡 Pull precisely filtered historical data from WooCommerce or upload a local file for analysis.")
    src_type = st.radio("Source Type", ["Manual File Upload", "WooCommerce Custom Pull"], horizontal=True, key="ingestion_src_type")
    
    df = None
    source_name = ""
    
    if src_type == "Manual File Upload":
        uploaded_file = st.file_uploader("Upload Product Sales File", type=["xlsx", "csv"], key="manual_uploader")
        if uploaded_file:
            df = read_sales_file(uploaded_file, uploaded_file.name)
            source_name = uploaded_file.name
    else:
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
        
        if st.session_state.get("manual_df") is not None:
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
                    uploaded_file.name,
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
    logo_src = "https://logo.clearbit.com/deencommerce.com"
    try:
        logo_jpg = os.path.join("assets", "deen_logo.jpg")
        if os.path.exists(logo_jpg):
            with open(logo_jpg, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            logo_src = f"data:image/png;base64,{b64}"
    except Exception:
        pass

    # Use global imports
    tz_bd = timezone(timedelta(hours=6))

    st.markdown(
        f"""
        <div>
            <div id="dynamic-clock-live" style="font-size: 0.8rem; color: #64748b; margin-bottom: 4px;">Current time: {datetime.now(tz_bd).strftime('%B %d, %Y %I:%M %p')}</div>
            <script>
                (function() {{
                    function update() {{
                        const options = {{ month: 'long', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }};
                        const now = new Date();
                        const timeStr = now.toLocaleString('en-US', options);
                        const el = document.getElementById('dynamic-clock-live');
                        if (el) el.innerHTML = "Current time: " + timeStr;
                    }}
                    setInterval(update, 1000);
                    update();
                }})();
            </script>
        </div>
        """,
        unsafe_allow_html=True,
    )
    welcome_html = f"""
    <div class="hub-welcome-banner">
        <div style="font-weight: 700; font-size: 1.15rem; margin-bottom: 4px;">Welcome! Today's Actionable Insights</div>
        <div style="font-size: 0.85rem; opacity: 0.9;">
            Powered by <a href="https://deencommerce.com/" target="_blank" style="text-decoration:none;">
                <img src="{logo_src}" width="16" style="vertical-align:middle; margin: 0 3px; border-radius:2px;" onerror="this.style.display='none'">
                <b>DEEN commerce</b>
            </a>
        </div>
    </div>
    """
    st.markdown(welcome_html, unsafe_allow_html=True)
    
    # Force Operational Cycle in live dashboard
    st.session_state["wc_sync_mode"] = "Operational Cycle"

    # Freshness & Direct Action Row
    c_f1, c_f2 = st.columns([6, 1])
    with c_f1:
        if st.session_state.get("live_sync_time"):
            diff = datetime.now() - st.session_state.live_sync_time
            mins = int(diff.total_seconds() / 60)
            sync_label = "Just now" if mins < 1 else f"{mins}m ago"
            st.caption(f"🔄 Last Synced: {sync_label}")
    with c_f2:
        if st.button("🔄 Sync", help="Force Operational Re-sync", use_container_width=True):
            st.rerun()

    if hasattr(st, "autorefresh"):
        st.autorefresh(interval=30000, key="live_autorefresh")

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


def fetch_woocommerce_stock():
    """Fetches real-time stock levels for published items using Expert Rules."""
    wc_info = st.secrets.get("woocommerce", {})
    wc_url = wc_info.get("store_url") or os.environ.get("WC_URL")
    wc_key = wc_info.get("consumer_key") or os.environ.get("WC_KEY")
    wc_secret = wc_info.get("consumer_secret") or os.environ.get("WC_SECRET")

    if not wc_url or not wc_key or not wc_secret:
        st.error("WooCommerce credentials missing.")
        return None

    endpoint = f"{wc_url.rstrip('/')}/wp-json/wc/v3/products"
    stock_data = []
    
    try:
        page = 1
        with st.spinner("📦 Fetching live inventory (~Published & In-Stock)..."):
            while True:
                r = requests.get(
                    endpoint,
                    params={
                        "per_page": 100, 
                        "page": page, 
                        "status": "publish",
                        "stock_status": "instock" # Native in-stock only filter
                    },
                    auth=HTTPBasicAuth(wc_key, wc_secret),
                    timeout=25
                )
                r.raise_for_status()
                products = r.json()
                if not products: break
                
                for p in products:
                    p_id, p_name = p.get("id"), p.get("name")
                    p_type = p.get("type", "simple")
                    
                    if p_type == "variable":
                        v_r = requests.get(f"{endpoint}/{p_id}/variations", params={"per_page": 100}, auth=HTTPBasicAuth(wc_key, wc_secret), timeout=15)
                        if v_r.status_code == 200:
                            for v in v_r.json():
                                full_name = f"{p_name} - {v.get('attributes',[{}])[0].get('option','N/A')}"
                                stock_data.append({
                                    "Category": get_category(p_name), # Map by base product name for broad categorization
                                    "Product": full_name,
                                    "SKU": v.get("sku") or f"P{p_id}-V{v.get('id')}",
                                    "Stock": v.get("stock_quantity") if v.get("manage_stock") else 0,
                                    "Price": v.get("price", "0"),
                                    "Status": v.get("stock_status", "unknown").title()
                                })
                    else:
                        stock_data.append({
                            "Category": get_category(p_name),
                            "Product": p_name,
                            "SKU": p.get("sku") or f"P{p_id}",
                            "Stock": p.get("stock_quantity") if p.get("manage_stock") else 0,
                            "Price": p.get("price", "0"),
                            "Status": p.get("stock_status", "unknown").title()
                        })
                if len(products) < 100: break
                page += 1
                
        df = pd.DataFrame(stock_data)
        if not df.empty:
            df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").fillna(0).astype(int)
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0)
            # Default filter: Only show in-stock
            df = df[df["Stock"] > 0]
        return df

    except Exception as e:
        log_system_event("STOCK_SYNC_ERROR", str(e))
        st.error(f"Stock fetch failed: {e}")
        return None


def render_stock_analytics_tab():
    """Renders the category-wise stock monitoring interface."""
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("📦 Current Stock Intelligence")
    
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
