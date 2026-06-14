import streamlit as st

st.set_page_config(
    page_title="DEEN OPS Terminal",
    page_icon="AH",
    layout="wide",
    initial_sidebar_state="expanded",
)


def run_app():
    # ========== AUTHENTICATION LAYER ==========
    # Native Streamlit OIDC Auth (requires secrets.toml configuration)
    from src.config.settings import (
        is_auth_configured as auth_is_configured,
        validate_runtime_configuration,
    )

    is_auth_configured = auth_is_configured()
    config_issues = validate_runtime_configuration()

    if is_auth_configured:
        if not st.user.is_logged_in:
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

    # Ensure Pathao Processor is in the nav — check by exact substring to avoid emoji prefix mismatch
    if not any("Pathao Processor" in item for item in PRIMARY_NAV):
        PRIMARY_NAV.append("📦 Pathao Processor")

    # Remove Excel Merger / Product Listing in-place (mutate the list, don't rebind the name)
    # Rebinding would create a local variable and leave the module-level list unchanged on next rerun.
    PRIMARY_NAV[:] = [item for item in PRIMARY_NAV if "Excel Merger" not in item and "Product Listing" not in item]

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
        # --- Prominent Sidebar Branding ---
        st.markdown(
            """
            <div class="sidebar-logo-container">
                <div style="font-size: 28px; line-height: 1; filter: drop-shadow(0 0 8px rgba(16, 185, 129, 0.5));">🛡️</div>
                <div style="flex: 1; min-width: 0;">
                    <div class="sidebar-logo-text">DEEN-OPS</div>
                    <div class="sidebar-logo-sub">Command Terminal</div>
                    <div class="sidebar-version-badge">v10.0</div>
                </div>
                <div class="sidebar-status-dot" title="System Online"></div>
            </div>
            """, 
            unsafe_allow_html=True
        )

        # User Authentication Context
        if is_auth_configured and st.user.is_logged_in:
            with st.sidebar.expander(f"👤 {st.user.name}", expanded=False):
                st.caption(f"📧 {st.user.email}")
                if st.button("Logout", use_container_width=True, type="secondary"):
                    st.logout()
            st.divider()

        st.link_button("🌐 Launch DEEN BI", CLOUD_APP_URL, use_container_width=True, type="primary")
        st.divider()

        st.markdown('<div class="command-nav-header"><span style="opacity:0.5;">⬡</span> Navigation</div>', unsafe_allow_html=True)
        
        default_nav = "📈 Live Dashboard" if "📈 Live Dashboard" in PRIMARY_NAV else PRIMARY_NAV[0]
        
        def format_nav(item):
            nav_icons = {
                "📈 Live Dashboard": ":material/dashboard: Live Dashboard",
                "📦 Pathao Processor": ":material/local_shipping: Pathao Processor",
                "📦 Bulk Order Processor": ":material/local_shipping: Pathao Processor",
                "💬 WhatsApp Messaging": ":material/chat: WhatsApp Messaging",
                "📊 Inventory Distribution": ":material/inventory_2: Inventory Distribution",
                "📦 Current Stock Analytics": ":material/analytics: Stock Analytics",
                "🧩 Delivery Data Parser": ":material/data_object: Delivery Parser",
                "📥 Sales Data Ingestion": ":material/cloud_download: Sales Ingestion",
                "📉 Return Analytics": ":material/keyboard_return: Return Analytics",
                "🚀 Data Pilot": ":material/smart_toy: Data Pilot",
                "🛒 WooCommerce Orders": ":material/shopping_cart: WooCommerce Orders"
            }
            return nav_icons.get(item, item)

        if hasattr(st, "pills"):
            selected_nav = st.sidebar.pills(
                "Select Workspace",
                options=PRIMARY_NAV,
                default=default_nav,
                selection_mode="single",
                format_func=format_nav,
                label_visibility="collapsed"
            )
            if not selected_nav:
                selected_nav = default_nav
        else:
            selected_nav = st.sidebar.radio(
                "Select Workspace",
                PRIMARY_NAV,
                label_visibility="collapsed",
                format_func=format_nav,
                index=PRIMARY_NAV.index(default_nav)
            )

        with st.sidebar.expander(":material/event: Operational Slots", expanded=False):
            from src.components.calendar_slots import render_operational_slots_calendar
            render_operational_slots_calendar()

        st.divider()
        with st.sidebar.expander(":material/build: Maintenance & Settings", expanded=False):
            st.caption("Configuration Health")
            if config_issues:
                st.warning("Some integrations are partially configured.")
                for issue in config_issues:
                    st.caption(f"- {issue}")
                st.caption("Schema reference: src/config/secrets_schema.json")
            else:
                st.success("Configuration validation passed.")

            st.divider()
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

    # Handle nav override from sidebar shortcut buttons
    if st.session_state.get("_nav_override"):
        selected_nav = st.session_state.pop("_nav_override")

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
        dist_tab, merge_tab = st.tabs([":material/inventory_2: Distribution Matrix", ":material/list_alt: Product Listing"])
        with dist_tab:
            safe_render(lambda: render_distribution_tab(search_q=st.session_state.get("inv_matrix_search", "")), fallback_msg="Inventory Distribution unavailable.")
        with merge_tab:
            from src.pages.excel_merger import render_excel_merger_tab
            safe_render(render_excel_merger_tab, fallback_msg="Product Listing unavailable.")
    elif selected_nav == "📦 Current Stock Analytics":
        safe_render(render_stock_analytics_tab, fallback_msg="Stock Analytics unavailable.")
    elif selected_nav == "🧩 Delivery Data Parser":
        safe_render(render_fuzzy_parser_tab, fallback_msg="Delivery Data Parser unavailable.")
    elif selected_nav == "📥 Sales Data Ingestion":
        safe_render(render_manual_tab, fallback_msg="Sales Data Ingestion unavailable.")
    elif selected_nav == "📉 Return Analytics":
        from src.pages.return_analytics import render_return_analytics_tab
        safe_render(render_return_analytics_tab, fallback_msg="Return Analytics unavailable.")
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

            # Show dynamic clock only on pages without the app banner
            if selected_nav != "📈 Live Dashboard":
                render_dynamic_clock(st.session_state.get("live_sync_time"))

            # Show tool-specific banners
            banner = st.session_state.get("header_status_banner", "")
            if banner:
                st.markdown(f'<div style="margin-top:8px;">{banner}</div>', unsafe_allow_html=True)

        # On Live Dashboard the banner already contains the title — skip the title row
        # to avoid a double header. On all other pages render the full header.
        if selected_nav != "📈 Live Dashboard":
            render_header(render_header_right)
        else:
            render_header_right()

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
