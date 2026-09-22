import streamlit as st


def section_card(title: str, help_text: str = ""):
    st.markdown(
        f"""
        <div class="hub-card">
          <div style="font-weight:600;">{title}</div>
          <div style="color:var(--text-muted); margin-top:4px;">{help_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_action_bar(
    primary_label: str,
    primary_key: str,
    secondary_label: str | None = None,
    secondary_key: str | None = None,
):
    if secondary_label and secondary_key:
        c1, c2 = st.columns([2, 1])
        primary_clicked = c1.button(
            primary_label, type="primary", use_container_width=True, key=primary_key
        )
        secondary_clicked = c2.button(
            secondary_label, use_container_width=True, key=secondary_key
        )
    else:
        primary_clicked = st.button(
            primary_label, type="primary", use_container_width=True, key=primary_key
        )
        secondary_clicked = False
    return primary_clicked, secondary_clicked


def render_sticky_action_bar(
    primary_label: str,
    primary_key: str,
    secondary_label: str | None = None,
    secondary_key: str | None = None,
):
    """Like render_action_bar but wrapped in a sticky-bottom container."""
    st.markdown('<div class="sticky-action-bar">', unsafe_allow_html=True)
    result = render_action_bar(
        primary_label, primary_key, secondary_label, secondary_key
    )
    st.markdown("</div>", unsafe_allow_html=True)
    return result


def render_reset_confirm(label: str, state_key: str, reset_fn):
    """
    Registers a tool's reset function for the unified sidebar.
    Doesn't render anything in the sidebar immediately to avoid duplicates.
    """
    if "registered_resets" not in st.session_state:
        st.session_state.registered_resets = {}

    st.session_state.registered_resets[label] = {"fn": reset_fn, "key": state_key}
