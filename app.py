import streamlit as st

_original_dataframe = st.dataframe


def _numbered_dataframe(data, *args, **kwargs):
    try:
        import pandas as pd

        if isinstance(data, pd.DataFrame) or isinstance(data, pd.Series):
            d = data.copy()
            if len(d) > 0:
                d.index = range(1, len(d) + 1)
            return _original_dataframe(d, *args, **kwargs)
    except Exception:
        pass
    return _original_dataframe(data, *args, **kwargs)


st.dataframe = _numbered_dataframe

st.set_page_config(
    page_title="DEEN BI OPS",
    page_icon="AH",
    layout="wide",
    initial_sidebar_state="expanded",
)


def run_app():
    # Lazy imports keep bootstrap resilient on cloud when a module has runtime incompatibilities.
    from app_modules.bike_animation import render_bike_animation
    from app_modules.distribution_tab import render_distribution_tab
    from app_modules.error_handler import get_logs, log_error
    from app_modules.fuzzy_parser_tab import render_fuzzy_parser_tab
    from app_modules.pathao_tab import render_pathao_tab
    from app_modules.persistence import init_state, save_state
    from app_modules.sales_dashboard import render_live_tab, render_manual_tab, render_stock_analytics_tab
    from app_modules.ui_components import (
        inject_base_styles,
        render_header,
        render_footer,
        render_sidebar_branding,
        section_card,
    )
    from app_modules.ui_config import PRIMARY_NAV, CLOUD_APP_URL
    from app_modules.error_handler import ERROR_LOG_FILE
    import os
    from app_modules.wp_tab import render_wp_tab

    init_state()
    inject_base_styles()

    with st.sidebar:
        render_sidebar_branding()
        
        st.subheader("🚀 Navigation")
        selected_nav = st.sidebar.radio(
            "Select Workspace", 
            PRIMARY_NAV, 
            label_visibility="collapsed",
            index=PRIMARY_NAV.index("📈 Live Dashboard") if "📈 Live Dashboard" in PRIMARY_NAV else 0
        )
        st.divider()

        st.subheader("Global Settings")
        
        st.session_state.show_animation = st.toggle(
            "Show motion effects",
            value=st.session_state.get("show_animation", True),
        )

        if st.button("Save session state", use_container_width=True):
            save_state()
            st.success("Session state saved.")

        # Unified Workspace Control Hub
        st.divider()
        st.subheader("Workspace Control")
        with st.expander("Reset Active Tool Data", expanded=True):
            registered = st.session_state.get("registered_resets", {})
            if not registered:
                st.info("No active tool data found.")
            else:
                tool_to_wipe = st.selectbox("Select tool", list(registered.keys()))
                if st.button(
                    "Reset Tool Now", use_container_width=True, type="primary"
                ):
                    registered[tool_to_wipe]["fn"]()
                    st.session_state.confirm_tool_reset = False
                    st.success("Cleaned!")
                    st.rerun()

        st.divider()
        if st.button("Full System Reset", use_container_width=True, type="secondary"):
            st.session_state.confirm_app_reset = True

        if st.session_state.get("confirm_app_reset"):
            st.warning("⚠️ Wipe EVERYTHING?")
            c1, c2 = st.columns(2)
            if c1.button("Yes", type="primary", use_container_width=True):
                from app_modules.persistence import STATE_FILE

                if os.path.exists(STATE_FILE):
                    os.remove(STATE_FILE)
                st.session_state.clear()
                st.rerun()
            if c2.button("No", use_container_width=True):
                st.session_state.confirm_app_reset = False
                st.rerun()

        with st.expander("System Logs", expanded=False):
            logs = get_logs()
            if not logs:
                st.info("No system events logged.")
            else:
                for log in reversed(logs[-20:]):
                    st.caption(f"**{log.get('timestamp')}** | {log.get('context')}")
                    st.text(log.get("error"))
                    st.divider()
                if st.button("Clear logs", use_container_width=True):
                    if os.path.exists(ERROR_LOG_FILE):
                        os.remove(ERROR_LOG_FILE)
                    st.rerun()

    render_header()
    if st.session_state.get("show_animation"):
        render_bike_animation()

    # Main content rendering based on sidebar selection
    if selected_nav == "📈 Live Dashboard":
        render_live_tab()
    elif selected_nav == "📦 Bulk Order Processer":
        render_pathao_tab()
    elif selected_nav == "💬 WhatsApp Messaging":
        render_wp_tab()
    elif selected_nav == "📊 Inventory Distribution":
        render_distribution_tab(search_q=st.session_state.get("inv_matrix_search", ""))
    elif selected_nav == "📦 Current Stock Analytics":
        render_stock_analytics_tab()
    elif selected_nav == "🧩 Delivery Data Parser":
        render_fuzzy_parser_tab()
    elif selected_nav == "📥 Sales Data Ingestion":
        render_manual_tab()
    elif selected_nav == "🌐 Cloud BI":
        st.subheader("🌐 Cloud Business Intelligence")
        st.info("Experience real-time cross-platform analytics on the Cloud Dashboard.")
        st.link_button("Launch Cloud BI (New Tab)", CLOUD_APP_URL, use_container_width=True, type="primary")
        st.caption("A new tab should have opened automatically. If not, please click the button above.")
        
        # Immediate auto-open script
        st.markdown(f'<script>window.open("{CLOUD_APP_URL}", "_blank");</script>', unsafe_allow_html=True)

    render_footer()


try:
    run_app()
except Exception as exc:
    # Failsafe to prevent full redacted crash pages on Streamlit Cloud.
    from app_modules.error_handler import log_error

    log_error(exc, context="App Bootstrap")
    st.error(
        "Application failed to render. Check 'More Tools -> System Logs' for details."
    )
    st.code(str(exc))
