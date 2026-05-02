import os
import base64
import streamlit as st


from datetime import datetime, timedelta
from src.components.clock import get_clock_html


def render_header(right_slot_callback=None):
    """Modern command-center header with exact user-requested styling."""
    st.markdown(
        f"""
        <div style="display: flex; align-items: baseline; gap: 12px; margin-bottom: 0px; justify-content: space-between; width: 100%;">
            <h1 class="hub-title" id="deen-ops-terminal-v10-0" aria-labelledby=":r9:" style="margin: 0px;">
                <span id=":r9:">DEEN OPS Terminal <span style="color: rgb(29, 78, 216);">v10.0</span></span>
            </h1>
        </div>
        <p style="color: var(--text-muted); margin-bottom: -10px; font-size: 1rem;">Operational Command & Business Intelligence Center</p>
        """,
        unsafe_allow_html=True
    )
    if right_slot_callback:
        with st.container():
            right_slot_callback()


def render_app_banner():
    """Renders a premium visual banner for the application with integrated clock, title, and sync status."""
    banner_path = os.path.join("assets", "app_banner.png")
    clock_html = get_clock_html()
    
    sync_label = "Checking status..."
    if st.session_state.get("live_sync_time"):
        diff = datetime.now() - st.session_state.live_sync_time
        mins = int(diff.total_seconds() / 60)
        sync_label = "Synced: Just now" if mins < 1 else f"Synced: {mins}m ago"
    elif st.session_state.get("wc_sync_mode") == "Operational Cycle":
         sync_label = "Syncing with WooCommerce..."

    # v15.0: Dynamic Holiday Awareness Logic
    holiday_banner_html = ""
    is_holiday_merge = False
    
    # Check if we are in Operational Cycle and if a merge is active
    if st.session_state.get("wc_sync_mode") == "Operational Cycle":
        curr_slot = st.session_state.get("wc_curr_slot")
        if curr_slot and len(curr_slot) == 2:
            start, end = curr_slot
            # If the duration is more than 28 hours, it's likely a holiday merge (normal shift is ~24h)
            if (end - start).total_seconds() > 100800: # 28 hours
                is_holiday_merge = True
                merge_date = (start + timedelta(hours=12)).strftime("%a, %d %b")
                holiday_banner_html = f"""
                    <div style="position: absolute; top: 15px; left: 40px; z-index: 10; display: flex; align-items: center; gap: 8px; background: rgba(59, 130, 246, 0.2); backdrop-filter: blur(10px); padding: 6px 14px; border-radius: 20px; border: 1px solid rgba(59, 130, 246, 0.4); animation: pulse 2s infinite;">
                        <span style="font-size: 0.9rem;">🌙</span>
                        <span style="color: #60a5fa; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase;">Holiday Merge Active</span>
                        <span style="color: white; font-size: 0.7rem; font-weight: 600;">(Incl. {merge_date})</span>
                    </div>
                """

    if os.path.exists(banner_path):
        with open(banner_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        st.markdown(
            f"""
<div class="app-banner-wrapper">
<img src="data:image/png;base64,{b64}" class="app-banner-img" style="width: 100%; height: 100%; object-fit: cover; position: absolute; top: 0; left: 0; z-index: 1;">
{holiday_banner_html}
<div class="app-banner-overlay">
<div class="app-banner-title-area">
<div class="app-banner-title">DEEN OPS Terminal</div>
<div class="app-banner-subtitle">Advanced Operational Analytics & Strategic Data Pilot</div>
</div>
<div class="app-banner-clock-area">
{clock_html}
<div style="margin-top: 6px; color: rgba(255,255,255,0.6); font-size: 0.75rem; font-family: sans-serif; letter-spacing: 0.05em; font-weight: 600;">🔄 {sync_label.upper()}</div>
</div>
</div>
</div>""",
            unsafe_allow_html=True
        )


def render_banner_mode_controls():
    """Renders operational mode radio buttons at the bottom-left of the banner area."""
    nav_mode = st.session_state.get("wc_nav_mode", "Today")
    mode_options = ["Last Day", "Active", "Queue"]
    mode_to_state = {"Last Day": "Prev", "Active": "Today", "Queue": "Backlog"}
    state_to_mode = {v: k for k, v in mode_to_state.items()}
    current_idx = mode_options.index(state_to_mode.get(nav_mode, "Active"))

    with st.container():
        st.markdown('<div class="banner-controls-shelf">', unsafe_allow_html=True)
        
        # Use a narrower column for the radio buttons
        c1, _ = st.columns([1.5, 3])
        with c1:
            selected_mode = st.radio(
                "Op Mode",
                mode_options,
                index=current_idx,
                horizontal=True,
                key="banner_op_mode_radio",
                label_visibility="collapsed"
            )
        
        st.markdown('</div>', unsafe_allow_html=True)

    new_nav = mode_to_state[selected_mode]
    if new_nav != nav_mode:
        st.session_state.wc_nav_mode = new_nav
        st.rerun()
