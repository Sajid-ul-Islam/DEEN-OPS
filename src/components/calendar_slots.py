import streamlit as st
from datetime import datetime, date, time, timedelta
from src.state.persistence import save_state

# Default shift cutoff: 18:00 (6:00 PM Bangladesh time)
DEFAULT_SHIFT_HOUR = 18
DEFAULT_SHIFT_MINUTE = 0


def get_shift_cutoff_time() -> time:
    """Returns the user-configured shift cutoff time, falling back to 17:30."""
    h = st.session_state.get("shift_cutoff_hour", DEFAULT_SHIFT_HOUR)
    m = st.session_state.get("shift_cutoff_minute", DEFAULT_SHIFT_MINUTE)
    return time(h, m)


def render_operational_slots_calendar():
    """
    Modern Date Range Selector UI for operational holiday management.
    Replacing the tile-based calendar for better bulk operation efficiency.
    """
    if "operational_holidays" not in st.session_state:
        st.session_state.operational_holidays = []
    
    hols = st.session_state.operational_holidays

    # ── Custom Shift Cutoff ──────────────────────────────────────────────────
    st.markdown(
        """<div class="op-slots-tooltip">⏰ Shift Cutoff Time
            <span class="op-slots-tooltip-text">Orders processed after this time are automatically rolled into the next operational shift.</span>
        </div>""",
        unsafe_allow_html=True
    )
    st.caption("Orders are split into Active / History slots at this time each day (BD time).")

    current_hour = st.session_state.get("shift_cutoff_hour", DEFAULT_SHIFT_HOUR)
    current_minute = st.session_state.get("shift_cutoff_minute", DEFAULT_SHIFT_MINUTE)

    col_h, col_m, col_apply = st.columns([2, 2, 2])
    with col_h:
        new_hour = st.number_input(
            "Hour (0–23)",
            min_value=0,
            max_value=23,
            value=current_hour,
            step=1,
            key="shift_cutoff_hour_input",
            label_visibility="collapsed",
            help="Hour in 24h format (BD time)",
        )
        st.caption(f"Hour: **{new_hour:02d}**")
    with col_m:
        new_minute = st.selectbox(
            "Minute",
            options=[0, 15, 30, 45],
            index=[0, 15, 30, 45].index(current_minute) if current_minute in [0, 15, 30, 45] else 2,
            key="shift_cutoff_minute_input",
            label_visibility="collapsed",
            format_func=lambda x: f":{x:02d}",
        )
        st.caption(f"Min: **:{new_minute:02d}**")
    with col_apply:
        st.markdown("<div style='margin-top:4px;'></div>", unsafe_allow_html=True)
        if st.button("✅ Apply", use_container_width=True, key="apply_shift_cutoff"):
            changed = (
                new_hour != current_hour or new_minute != current_minute
            )
            st.session_state.shift_cutoff_hour = new_hour
            st.session_state.shift_cutoff_minute = new_minute
            if changed:
                # Invalidate cached data so next sync uses the new cutoff
                st.session_state.wc_curr_df = None
                st.session_state.wc_prev_df = None
                save_state()
                st.toast(
                    f"✅ Shift cutoff set to {new_hour:02d}:{new_minute:02d} BD time. "
                    "Next sync will use the new boundary.",
                    icon="⏰",
                )
                st.rerun()

    # Show current active cutoff
    active_cutoff = get_shift_cutoff_time()
    st.info(f"Active cutoff: **{active_cutoff.strftime('%I:%M %p')}** BD time")

    st.divider()

    # ── Operational Holidays ─────────────────────────────────────────────────
    st.markdown(
        """<div class="op-slots-tooltip">📅 Operational Holidays
            <span class="op-slots-tooltip-text">Mark non-working days here. Operations metrics will bridge across these days without penalizing your lead times.</span>
        </div>""",
        unsafe_allow_html=True
    )
    
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

    st.divider()

    st.markdown("**📦 Order Limit Options**")
    order_limit_opt = st.selectbox(
        "Fetch Limit",
        ["Last 10", "Last 20", "Custom Order"],
        key="operational_slot_order_limit"
    )
    if order_limit_opt == "Custom Order":
        st.number_input("Custom Order Count", min_value=1, value=50, key="operational_slot_custom_order_count")

    st.info("💡 Fridays are marked as holidays by default.")
