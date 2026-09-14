import base64
import os
import textwrap
from datetime import timedelta

import streamlit as st

from src.components.ui.clock import get_clock_html
from src.config.constants import bd_now


def render_header(right_slot_callback=None):
    """Modern command-center header with exact user-requested styling."""
    st.markdown(
        """
        <div style="display: flex; align-items: baseline; gap: 12px; margin-bottom: 0px; justify-content: space-between; width: 100%;">
            <h1 class="hub-title" id="deen-ops-terminal-v10-0" aria-labelledby=":r9:" style="margin: 0px;">
                <span id=":r9:">DEEN OPS Terminal <span style="color: rgb(29, 78, 216);">v10.0</span></span>
            </h1>
        </div>
        <p style="color: var(--text-muted); margin-bottom: -10px; font-size: 1rem;">Operational Command & Business Intelligence Center</p>
        """,
        unsafe_allow_html=True,
    )
    if right_slot_callback:
        with st.container():
            right_slot_callback()


def render_app_banner():
    """Renders a premium visual banner for the application with integrated clock, title, and sync status."""
    banner_path = os.path.join("assets", "app_banner.png")
    clock_html = get_clock_html()

    sync_label = "Checking status..."
    last_sync = st.session_state.get("live_sync_time")
    if last_sync:
        now_bd = bd_now().replace(tzinfo=None)
        diff = now_bd - last_sync
        mins = max(0, int(diff.total_seconds() / 60))
        sync_label = "Synced: Just now" if mins < 1 else f"Synced: {mins}m ago"
    elif st.session_state.get("wc_sync_mode") == "Operational Cycle":
        sync_label = "Syncing with WooCommerce..."

    # v15.0: Dynamic Holiday Awareness Logic
    holiday_banner_html = ""

    # Check if we are in Operational Cycle and if a merge is active
    if st.session_state.get("wc_sync_mode") == "Operational Cycle":
        curr_slot = st.session_state.get("wc_curr_slot")
        if curr_slot and len(curr_slot) == 2:
            start, end = curr_slot
            # If the duration is more than 28 hours, it's likely a holiday merge (normal shift is ~24h)
            if (end - start).total_seconds() > 100800:  # 28 hours
                merge_date = (start + timedelta(hours=12)).strftime("%a, %d %b")
                holiday_banner_html = f'<div style="position: absolute; top: 15px; left: 40px; z-index: 10; display: flex; align-items: center; gap: 8px; background: rgba(59,130,246,0.2); backdrop-filter: blur(10px); padding: 6px 14px; border-radius: 20px; border: 1px solid rgba(59,130,246,0.4); animation: banner-pulse 2s infinite;"><span style="font-size: 0.9rem;">🌙</span><span style="color: #60a5fa; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase;">Holiday Merge Active</span><span style="color: white; font-size: 0.7rem; font-weight: 600;">(Incl. {merge_date})</span></div>'

    # ── DEEN-OPS Banner Brand Colors (global, theme-independent) ──────────
    # These are fixed identity colors for the banner — they do NOT change
    # when the user switches the Chart Theme in the sidebar.
    BRAND_PRIMARY = "#10b981"  # emerald green
    BRAND_SECONDARY = "#06b6d4"  # cyan
    # ──────────────────────────────────────────────────────────────────────

    p_color = BRAND_PRIMARY
    s_color = BRAND_SECONDARY
    p_08 = "rgba(16,185,129,0.08)"
    p_20 = "rgba(16,185,129,0.20)"
    p_35 = "rgba(16,185,129,0.35)"
    p_glow = "rgba(16,185,129,0.25)"
    s_15 = "rgba(6,182,212,0.15)"

    img_html = ""
    if os.path.exists(banner_path):
        try:
            with open(banner_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                img_html = f'<img src="data:image/png;base64,{b64}" class="app-banner-img" style="width: 100%; height: 100%; object-fit: cover; object-position: center center; position: absolute; top: 0; left: 0; z-index: 1; opacity: 0.85; filter: saturate(1.4) brightness(1.05);">'
        except Exception:
            pass

    banner_html = textwrap.dedent(
        f"""
<div class="app-banner-wrapper" style="position: relative; width: 100%; height: 170px; border-radius: 18px; overflow: hidden; background: linear-gradient(135deg, rgba(8,15,30,0.97) 0%, rgba(15,25,50,0.93) 50%, rgba(10,20,40,0.97) 100%); border: 1px solid {p_35}; box-shadow: 0 20px 48px -12px rgba(0,0,0,0.7), 0 4px 16px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08); margin-bottom: 16px;">
{img_html}
<div style="position: absolute; inset: 0; z-index: 2; background: linear-gradient(90deg, rgba(8,15,30,0.78) 0%, rgba(8,15,30,0.25) 50%, rgba(8,15,30,0.78) 100%);"></div>
<div style="position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, {p_color}, {s_color}, {p_color}); z-index: 6;"></div>
<div style="position: absolute; top: 0; left: 0; width: 25%; height: 100%; z-index: 4; background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.04) 50%, transparent 100%); animation: banner-shimmer 4s ease-in-out infinite; pointer-events: none;"></div>
{holiday_banner_html}
<div class="app-banner-overlay" style="position: relative; z-index: 5; display: flex; align-items: center; justify-content: space-between; height: 100%; padding: 0 36px;">
<div class="app-banner-title-area">
<div style="display: flex; align-items: center; gap: 14px; margin-bottom: 8px;">
<span style="font-size: 1.9rem; font-weight: 900; letter-spacing: 0.07em; background: linear-gradient(90deg, #ffffff 0%, {p_color} 55%, {s_color} 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">DEEN-OPS Terminal</span>
<span style="background: linear-gradient(135deg, {p_20}, {s_15}); color: {p_color}; font-size: 0.65rem; font-weight: 800; padding: 4px 12px; border-radius: 20px; border: 1px solid {p_35}; text-transform: uppercase; letter-spacing: 0.08em; box-shadow: 0 0 14px {p_glow};">v10.0 LIVE</span>
</div>
<div style="color: rgba(203,213,225,0.80); font-size: 0.85rem; font-weight: 400; letter-spacing: 0.03em; display: flex; align-items: center; gap: 8px;">
<span style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: {p_color}; box-shadow: 0 0 10px {p_color}; animation: banner-pulse 2s ease-in-out infinite; flex-shrink: 0;"></span>
Advanced Operational Command &amp; Strategic Business Intelligence
</div>
</div>
<div class="app-banner-clock-area" style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 6px;">
{clock_html}
<div style="color: {p_color}; font-size: 0.70rem; font-family: 'JetBrains Mono', 'Courier New', monospace; letter-spacing: 0.10em; font-weight: 700; background: {p_08}; padding: 3px 12px; border-radius: 10px; border: 1px solid {p_20};">🟢 {sync_label.upper()}</div>
</div>
</div>
</div>
"""
    ).strip()
    st.markdown(banner_html, unsafe_allow_html=True)
