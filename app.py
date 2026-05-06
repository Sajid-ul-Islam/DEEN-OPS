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
    page_title="DEEN OPS Terminal",
    page_icon="AH",
    layout="wide",
    initial_sidebar_state="expanded",
)


def run_app():
    # ========== AUTHENTICATION LAYER ==========
    # Native Streamlit OIDC Auth (requires secrets.toml configuration)
    is_auth_configured = "auth" in st.secrets

    if is_auth_configured:
        if not st.experimental_user.is_logged_in:
            from src.components.styles import inject_base_styles
            inject_base_styles()
            st.markdown("<div style='margin-top:100px;'></div>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.image("assets/deen_logo.jpg", width=120)
                st.title("🛡️ DEEN OPS Terminal")
                st.markdown("### Secure Operational Access")
                st.info("Identity verification required for Business Intelligence access.")
                if st.button("Log in with Google", use_container_width=True, type="primary"):
                    st.login()
            st.stop()
    # ==========================================

    # Lazy imports keep bootstrap resilient on cloud when a module has runtime incompatibilities.
    from src.components.bike_animation import render_bike_animation
    from src.pages.inventory_distribution import render_distribution_tab
    from src.utils.logging import get_logs
    from src.config.constants import ERROR_LOG_FILE
    from src.pages.delivery_parser import render_fuzzy_parser_tab
    from src.pages.pathao_orders import render_pathao_tab
    from src.state.persistence import init_state, save_state, STATE_FILE
    from src.pages.live_dashboard import render_live_tab
    from src.pages.sales_ingestion import render_manual_tab
    from src.pages.stock_analytics import render_stock_analytics_tab
    from src.components.styles import inject_base_styles
    from src.components.header import render_header, render_app_banner
    from src.components.footer import render_footer
    from src.config.ui_config import PRIMARY_NAV, CLOUD_APP_URL
    import os
    from src.pages.whatsapp_messaging import render_wp_tab

    # Ensure Pathao Processor is available in the nav menu
    if not any("Pathao" in item or "Bulk Order" in item for item in PRIMARY_NAV):
        PRIMARY_NAV.append("📦 Pathao Processor")

    init_state()
    inject_base_styles()

    # Automated Log Rotation
    try:
        import json
        from datetime import datetime

        LOG_MAX_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB
        LOGS_TO_KEEP = 200

        if os.path.exists(ERROR_LOG_FILE) and os.path.getsize(ERROR_LOG_FILE) > LOG_MAX_SIZE_BYTES:
            with open(ERROR_LOG_FILE, "r+", encoding="utf-8") as f:
                logs = json.load(f)
                if len(logs) > LOGS_TO_KEEP:
                    truncated_logs = logs[-LOGS_TO_KEEP:]
                    rotation_log_entry = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "context": "LOG_ROTATION",
                        "error": f"Log file exceeded {LOG_MAX_SIZE_BYTES / 1024 / 1024:.1f}MB; truncated to last {LOGS_TO_KEEP} entries."
                    }
                    final_logs = truncated_logs + [rotation_log_entry]
                    f.seek(0)
                    json.dump(final_logs, f, indent=4)
                    f.truncate()
    except Exception:
        pass # Non-critical maintenance task, fail silently.

    # Clear previous header banner to ensure tool-specific display
    if "header_status_banner" not in st.session_state:
        st.session_state.header_status_banner = ""
    else:
        # We don't clear it immediately because it might be set by the tool *during* this run
        pass

    with st.sidebar:
        # User Authentication Context
        if is_auth_configured and st.experimental_user.is_logged_in:
            with st.sidebar.expander(f"👤 {st.experimental_user.name}", expanded=False):
                st.caption(f"📧 {st.experimental_user.email}")
                if st.button("Logout", use_container_width=True, type="secondary"):
                    st.logout()
            st.divider()

        st.link_button("🌐 Launch DEEN BI", CLOUD_APP_URL, use_container_width=True, type="primary")
        st.divider()

        st.subheader("🚀 COMMAND NAV")
        selected_nav = st.sidebar.radio(
            "Select Workspace",
            PRIMARY_NAV,
            label_visibility="collapsed",
            index=PRIMARY_NAV.index("📈 Live Dashboard") if "📈 Live Dashboard" in PRIMARY_NAV else 0
        )

        with st.sidebar.expander("📅 Operational Slots", expanded=False):
            from src.components.calendar_slots import render_operational_slots_calendar
            render_operational_slots_calendar()

        st.divider()
        with st.sidebar.expander("🛠️ Maintenance & Settings", expanded=False):
            st.session_state.show_animation = st.toggle(
                "Show motion effects",
                value=st.session_state.get("show_animation", True),
            )

            if st.button("Save session state", use_container_width=True):
                save_state()
                st.success("Session state saved.")

            st.divider()
            st.caption("Workspace Control")
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

            if st.button("Full System Reset", use_container_width=True, type="secondary"):
                st.session_state.confirm_app_reset = True

            if st.session_state.get("confirm_app_reset"):
                st.warning("⚠️ Wipe EVERYTHING?")
                c1, c2 = st.columns(2)
                if c1.button("Yes", type="primary", use_container_width=True):
                    if os.path.exists(STATE_FILE):
                        os.remove(STATE_FILE)
                    st.session_state.clear()
                    st.rerun()
                if c2.button("No", use_container_width=True):
                    st.session_state.confirm_app_reset = False
                    st.rerun()

            st.divider()
            st.caption("System Logs")
            logs = get_logs()
            if not logs:
                st.info("No system events logged.")
            else:
                for log in reversed(logs[-10:]):
                    st.caption(f"**{log.get('timestamp')}** | {log.get('context')}")
                    st.text(log.get("error"))
                if st.button("Clear logs", use_container_width=True):
                    if os.path.exists(ERROR_LOG_FILE):
                        os.remove(ERROR_LOG_FILE)
                    st.rerun()

    # Placeholder for Unified Header
    header_container = st.empty()

    if st.session_state.get("show_animation"):
        render_bike_animation()

    from src.utils.safe_ops import safe_render
    
    # Main content rendering based on sidebar selection
    if selected_nav == "📈 Live Dashboard":
        from src.components.header import render_banner_mode_controls
        safe_render(render_app_banner, fallback_msg="App banner unavailable.")
        safe_render(render_banner_mode_controls, fallback_msg="Mode controls unavailable.")
        safe_render(render_live_tab, fallback_msg="Live Dashboard unavailable.")
    elif selected_nav in ["📦 Bulk Order Processer", "📦 Bulk Order Processor", "📦 Pathao Processor"]:
        safe_render(render_pathao_tab, fallback_msg="Pathao Processor unavailable.")
    elif selected_nav == "💬 WhatsApp Messaging":
        safe_render(render_wp_tab, fallback_msg="WhatsApp Messaging unavailable.")
    elif selected_nav == "📊 Inventory Distribution":
        safe_render(lambda: render_distribution_tab(search_q=st.session_state.get("inv_matrix_search", "")), fallback_msg="Inventory Distribution unavailable.")
    elif selected_nav == "📦 Current Stock Analytics":
        safe_render(render_stock_analytics_tab, fallback_msg="Stock Analytics unavailable.")
    elif selected_nav == "🧩 Delivery Data Parser":
        safe_render(render_fuzzy_parser_tab, fallback_msg="Delivery Data Parser unavailable.")
    elif selected_nav == "📥 Sales Data Ingestion":
        safe_render(render_manual_tab, fallback_msg="Sales Data Ingestion unavailable.")
    elif selected_nav == "🚀 Data Pilot":
        from src.pages.data_pilot import render_ai_pilot_page
        safe_render(render_ai_pilot_page, fallback_msg="Data Pilot unavailable.")
    elif selected_nav == "🛒 WooCommerce Orders":
        from src.pages.woocommerce_orders import render_woocommerce_orders_tab
        safe_render(render_woocommerce_orders_tab, fallback_msg="WooCommerce Orders unavailable.")
    # After tool execution, re-render the header with any injected content
    with header_container:
        def render_header_right():
            from src.components.clock import render_dynamic_clock

            # 1. Live banner — passive stats on all pages
            # Removed as requested

            # 2. Show dynamic clock only on pages without the app banner
            if selected_nav != "📈 Live Dashboard":
                render_dynamic_clock(st.session_state.get("live_sync_time"))

            # 3. Show tool-specific banners
            banner = st.session_state.get("header_status_banner", "")
            if banner:
                st.markdown(f'<div style="margin-top:8px;">{banner}</div>', unsafe_allow_html=True)

        render_header(render_header_right)

    # Reset banner for next run to avoid bleeding into other pages
    st.session_state.header_status_banner = ""

    render_footer()


try:
    run_app()
except Exception as exc:
    # Failsafe to prevent full redacted crash pages on Streamlit Cloud.
    from src.utils.logging import log_error

    log_error(exc, context="App Bootstrap")
    st.error(
        "Application failed to render. Check 'More Tools -> System Logs' for details."
    )
    st.code(str(exc))
