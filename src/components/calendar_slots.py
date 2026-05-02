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

    # Premium Range Interaction
    st.write("### 📅 Splicing Range")
    st.caption("Select a range to mark or clear operational holidays.")
    
    # Use st.date_input with current date as default to avoid empty selection at start
    default_date = date.today()
    selected_range = st.date_input(
        "Range Selector",
        value=(), # Empty tuple allows for range selection mode in Streamlit
        label_visibility="collapsed",
        help="Pick start and end dates"
    )

    c1, c2 = st.columns(2)
    
    if len(selected_range) == 2:
        start, end = selected_range
        with c1:
            if st.button("🛑 Mark Holiday", use_container_width=True, type="primary"):
                curr = start
                added_count = 0
                while curr <= end:
                    d_str = curr.strftime("%Y-%m-%d")
                    if d_str not in hols:
                        hols.append(d_str)
                        added_count += 1
                    curr += timedelta(days=1)
                
                if added_count > 0:
                    st.session_state.operational_holidays = sorted(list(set(hols)))
                    save_state()
                    st.session_state.wc_curr_df = None
                    st.session_state.wc_prev_df = None
                    st.rerun()
        
        with c2:
            if st.button("⚪ Clear Range", use_container_width=True):
                curr = start
                removed_count = 0
                while curr <= end:
                    d_str = curr.strftime("%Y-%m-%d")
                    if d_str in hols:
                        hols.remove(d_str)
                        removed_count += 1
                    curr += timedelta(days=1)
                
                if removed_count > 0:
                    st.session_state.operational_holidays = sorted(hols)
                    save_state()
                    st.session_state.wc_curr_df = None
                    st.session_state.wc_prev_df = None
                    st.rerun()
    else:
        with c1:
            st.button("🛑 Mark Holiday", use_container_width=True, type="primary", disabled=True)
        with c2:
            st.button("⚪ Clear Range", use_container_width=True, disabled=True)
        if len(selected_range) == 1:
            st.info("👆 Please select the end date to complete the range.")
        else:
            st.caption("Click the calendar to start selecting a range.")

    st.divider()

    # Active Overrides Section
    st.markdown("**⚡ Quick Overrides**")
    c_merge = st.toggle("Force 48h Shift (Active)", value=st.session_state.get("override_merge_current", False))
    p_merge = st.toggle("Force 48h Shift (Historical)", value=st.session_state.get("override_merge_previous", False))
    
    if c_merge != st.session_state.get("override_merge_current", False) or \
       p_merge != st.session_state.get("override_merge_previous", False):
        st.session_state.override_merge_current = c_merge
        st.session_state.override_merge_previous = p_merge
        st.session_state.wc_curr_df = None
        st.session_state.wc_prev_df = None
        st.rerun()

    # Manual Holidays List
    if hols:
        with st.expander(f"📋 Manual Holidays ({len(hols)})", expanded=False):
            st.caption("Click to remove specific dates")
            # Filter hols to keep it reasonable - maybe only show upcoming or recent?
            # For now show all, but in a grid
            col_list = st.columns(1)
            for h in sorted(hols, reverse=True):
                h_date = datetime.strptime(h, "%Y-%m-%d").date()
                label = h_date.strftime("%a, %d %b %Y")
                if st.button(f"🗑️ {label}", key=f"del_{h}", use_container_width=True):
                    hols.remove(h)
                    st.session_state.operational_holidays = hols
                    save_state()
                    st.session_state.wc_curr_df = None
                    st.session_state.wc_prev_df = None
                    st.rerun()

    st.markdown("""
        <div style='background: rgba(59, 130, 246, 0.04); padding: 10px; border-radius: 8px; border: 1px solid rgba(59, 130, 246, 0.1); margin-top: 10px;'>
            <div style='font-size: 0.75rem; color: #475569;'>
                💡 <b>Note:</b> Fridays are marked as holidays by default and don't need manual entry.
            </div>
        </div>
    """, unsafe_allow_html=True)
