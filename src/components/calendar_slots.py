import streamlit as st
from datetime import datetime, date, timedelta
from src.state.persistence import save_state

def render_operational_slots_calendar():
    """
    Modern Date Range Selector UI for operational holiday management.
    Replacing the tile-based calendar for better bulk operation efficiency.
    """
    if "operational_holidays" not in st.session_state:
        st.session_state.operational_holidays = []
    
    hols = st.session_state.operational_holidays

    st.markdown("**📅 Operational Holidays**")
    
    selected_range = st.date_input(
        "Range Selector",
        value=(), 
        label_visibility="collapsed",
    )

    c1, c2 = st.columns(2)
    
    if len(selected_range) == 2:
        start, end = selected_range
        with c1:
            if st.button("🛑 Mark", use_container_width=True, type="primary"):
                curr = start
                added_count = 0
                while curr <= end:
                    d_str = curr.strftime("%Y-%m-%d")
                    if d_str not in hols:
                        hols.append(d_str)
                        added_count += 1
                    curr += timedelta(days=1)
                
                if added_count > 0:
                    st.toast(f"✅ Marked {added_count} day(s) as holiday!")
                    st.session_state.operational_holidays = sorted(list(set(hols)))
                    save_state()
                    st.session_state.wc_curr_df = None
                    st.session_state.wc_prev_df = None
                    st.rerun()
        
        with c2:
            if st.button("⚪ Clear", use_container_width=True):
                curr = start
                removed_count = 0
                while curr <= end:
                    d_str = curr.strftime("%Y-%m-%d")
                    if d_str in hols:
                        hols.remove(d_str)
                        removed_count += 1
                    curr += timedelta(days=1)
                
                if removed_count > 0:
                    st.toast(f"✅ Cleared {removed_count} day(s) from holidays!")
                    st.session_state.operational_holidays = sorted(hols)
                    save_state()
                    st.session_state.wc_curr_df = None
                    st.session_state.wc_prev_df = None
                    st.rerun()
    else:
        with c1:
            st.button("🛑 Mark", use_container_width=True, type="primary", disabled=True)
        with c2:
            st.button("⚪ Clear", use_container_width=True, disabled=True)
        st.caption("Select start and end date.")

    st.divider()

    # Active Overrides Section
    st.markdown("**⚡ Quick Overrides**")
    
    c_merge = st.toggle("Active Shift (48h)", value=st.session_state.get("override_merge_current", False))
    c_24h = st.toggle("Active Shift (24h)", value=st.session_state.get("override_24h_current", False))
    p_merge = st.toggle("History Shift (48h)", value=st.session_state.get("override_merge_previous", False))
    p_24h = st.toggle("History Shift (24h)", value=st.session_state.get("override_24h_previous", False))
    
    if c_merge != st.session_state.get("override_merge_current", False) or \
       c_24h != st.session_state.get("override_24h_current", False) or \
       p_merge != st.session_state.get("override_merge_previous", False) or \
       p_24h != st.session_state.get("override_24h_previous", False):
        
        st.toast("⚡ Override settings updated!")
        st.session_state.override_merge_current = c_merge
        st.session_state.override_24h_current = c_24h
        st.session_state.override_merge_previous = p_merge
        st.session_state.override_24h_previous = p_24h
        st.session_state.wc_curr_df = None
        st.session_state.wc_prev_df = None
        st.rerun()

    # Manual Holidays List
    if hols:
        with st.expander(f"📋 Manual Holidays ({len(hols)})", expanded=False):
            for h in sorted(hols, reverse=True):
                h_date = datetime.strptime(h, "%Y-%m-%d").date()
                if st.button(f"🗑️ {h_date.strftime('%d %b %y')}", key=f"del_{h}", use_container_width=True):
                    hols.remove(h)
                    st.toast(f"Removed {h}")
                    st.session_state.operational_holidays = hols
                    save_state()
                    st.session_state.wc_curr_df = None
                    st.session_state.wc_prev_df = None
                    st.rerun()

    st.info("💡 Fridays are marked as holidays by default.")
