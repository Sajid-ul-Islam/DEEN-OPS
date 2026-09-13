"""Application bootstrap module — extracted from app.py for maintainability.

Handles authentication, sidebar rendering, navigation routing,
log rotation, and tool registration.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, Optional

import streamlit as st

from src.config.constants import ERROR_LOG_FILE
from src.config.settings import is_auth_configured as auth_is_configured
from src.config.settings import is_unauthenticated_access_allowed
from src.config.settings import validate_runtime_configuration
from src.config.ui_config import CLOUD_APP_URL, PRIMARY_NAV
from src.state.persistence import STATE_FILE, init_state, save_state
from src.utils.logging import get_logs
from src.utils.safe_ops import safe_render

# ── Log rotation helper (non-critical, fails silently) ──────────────────────


def _rotate_error_logs() -> None:
    """Auto-truncate error_logs.json if it exceeds 1MB."""
    try:
        import json

        LOG_MAX_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB
        LOGS_TO_KEEP = 200

        if (
            os.path.exists(ERROR_LOG_FILE)
            and os.path.getsize(ERROR_LOG_FILE) > LOG_MAX_SIZE_BYTES
        ):
            with open(ERROR_LOG_FILE, "r+", encoding="utf-8") as f:
                logs = json.load(f)
                if len(logs) > LOGS_TO_KEEP:
                    truncated_logs = logs[-LOGS_TO_KEEP:]
                    rotation_log_entry = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "context": "LOG_ROTATION",
                        "error": f"Log file exceeded {LOG_MAX_SIZE_BYTES / 1024 / 1024:.1f}MB; truncated to last {LOGS_TO_KEEP} entries.",
                    }
                    final_logs = truncated_logs + [rotation_log_entry]
                    f.seek(0)
                    json.dump(final_logs, f, indent=4)
                    f.truncate()
    except Exception:
        pass  # Non-critical maintenance task, fail silently.


# ── Authentication guard ────────────────────────────────────────────────────


def _render_auth_gate() -> None:
    """Show the Google login screen when auth is enabled but user is not logged in."""
    from src.components.ui.styles import inject_base_styles

    inject_base_styles()
    st.markdown("<div style='margin-top:100px;'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("assets/deen_logo.jpg", width=120)
        st.title("\U0001f6e1\ufe0f DEEN OPS Terminal")
        st.markdown("### Secure Operational Access")
        st.info("Identity verification required for Business Intelligence access.")
        if st.button("Log in with Google", use_container_width=True, type="primary"):
            st.login()
    st.stop()


# ── Navigation helpers ──────────────────────────────────────────────────────


def _format_nav_item(item: str) -> str:
    """Map a nav key to a Material-icon-labelled display string."""
    nav_icons = {
        "📈 Live Dashboard": ":material/dashboard: Live Dashboard",
        "🛒 Order Tracking": ":material/shopping_cart: Order Tracking",
        "🛒 Order tracking": ":material/shopping_cart: Order Tracking",
        "📋 Product Listing": ":material/receipt_long: Product Listing",
        "📦 Pathao Processor": ":material/local_shipping: Pathao Processor",
        "💬 WhatsApp Messaging": ":material/chat: WhatsApp Messaging",
        "📊 Inventory Distribution": ":material/inventory_2: Inventory Distribution",
        "📦 Current Stock Analytics": ":material/analytics: Stock Analytics",
        "🧩 Delivery Data Parser": ":material/data_object: Delivery Parser",
        "📥 Sales Data Ingestion": ":material/cloud_download: Sales Ingestion",
        "📉 Return Analytics": ":material/keyboard_return: Return Analytics",
        "🚀 Data Pilot": ":material/smart_toy: Data Pilot",
    }
    return nav_icons.get(item, item)


def _render_nav_pills(
    nav_items: list[str],
    default: str,
    key: str = "sidebar_nav",
    on_change: Optional[Callable[[], None]] = None,
) -> str:
    """Render sidebar navigation pills (or radio fallback)."""
    if key not in st.session_state:
        st.session_state[key] = default

    if hasattr(st, "pills"):
        selected = st.sidebar.pills(
            "Select Workspace",
            options=nav_items,
            selection_mode="single",
            format_func=_format_nav_item,
            label_visibility="collapsed",
            key=key,
            on_change=on_change,
        )
        return selected or st.session_state.get(key, default)
    current_val = st.session_state.get(key, default)
    idx = nav_items.index(current_val) if current_val in nav_items else 0
    return st.sidebar.radio(
        "Select Workspace",
        nav_items,
        label_visibility="collapsed",
        format_func=_format_nav_item,
        index=idx,
        key=key,
        on_change=on_change,
    )


# ── Sidebar sections ────────────────────────────────────────────────────────


def _render_sidebar_branding() -> None:
    """Render the DEEN-OPS logo, title, and version badge in the sidebar."""
    import base64
    import os

    logo_jpg = os.path.join("assets", "deen_logo.jpg")
    logo_img_html = '<div style="font-size: 28px; line-height: 1; filter: drop-shadow(0 0 8px rgba(16, 185, 129, 0.5));">🛡️</div>'
    if os.path.exists(logo_jpg):
        try:
            with open(logo_jpg, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                logo_img_html = f'<img src="data:image/jpeg;base64,{b64}" style="width: 36px; height: 36px; border-radius: 8px; object-fit: cover; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">'
        except Exception:
            pass

    st.markdown(
        f"""
        <div class="sidebar-logo-container">
            {logo_img_html}
            <div style="flex: 1; min-width: 0;">
                <div class="sidebar-logo-text">DEEN-OPS</div>
                <div class="sidebar-logo-sub">Command Terminal</div>
                <div class="sidebar-version-badge">v10.0</div>
            </div>
            <div class="sidebar-status-dot" title="System Online"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_user_context(is_auth_on: bool) -> None:
    """Show the logged-in user expander when auth is enabled."""
    if is_auth_on and st.user.is_logged_in:
        with st.sidebar.expander(f"\U0001f464 {st.user.name}", expanded=False):
            st.caption(f"\U0001f4e7 {st.user.email}")
            if st.button("Logout", use_container_width=True, type="secondary"):
                st.logout()
        st.divider()


def _render_sidebar_maintenance(is_auth_on: bool, config_issues: list[str]) -> None:
    """Render the Maintenance & Settings expander in the sidebar."""
    with st.sidebar.expander(":material/build: Maintenance & Settings", expanded=False):
        # ── Chart theme (compact pills — moved out of the sidebar body) ─────
        from src.config.ui_config import CHART_THEMES

        _theme_names = list(CHART_THEMES.keys())
        _current_theme = st.session_state.get("chart_theme", "✨ Emerald Cyberpunk")
        _chosen_theme = st.pills(
            "🎨 Chart theme",
            options=_theme_names,
            selection_mode="single",
            default=_current_theme if _current_theme in _theme_names else None,
            key="sidebar_theme_pills",
        )
        if _chosen_theme and _chosen_theme != _current_theme:
            st.session_state["chart_theme"] = _chosen_theme
            st.rerun()

        with st.expander("📅 Operational Shift Slots", expanded=False):
            from src.components.ui.calendar_slots import (
                render_operational_slots_calendar,
            )

            render_operational_slots_calendar()

        st.divider()
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
            value=st.session_state.get("show_animation", False),
        )

        from src.components.react_kpi import is_react_kpi_available

        if is_react_kpi_available():
            st.session_state.use_react_kpi = st.toggle(
                "⚡ React UI (Modern Toolbar)",
                value=st.session_state.get("use_react_kpi", True),
                help="Interactive React-powered KPI cards and view switcher",
            )

        # ── Auto-refresh interval ──────────────────────────────────────────
        st.caption("Data Sync")
        refresh_opts = {
            "15s": 15,
            "30s": 30,
            "60s": 60,
            "2m": 120,
            "5m": 300,
            "Manual": 0,
        }
        current_val = st.session_state.get("wc_refresh_interval", 30)
        current_label = next(
            (k for k, v in refresh_opts.items() if v == current_val), "30s"
        )
        chosen_label = st.selectbox(
            "Auto-refresh interval",
            options=list(refresh_opts.keys()),
            index=list(refresh_opts.keys()).index(current_label),
            help="How often to fetch fresh data from WooCommerce. 'Manual' requires clicking Refresh.",
            key="refresh_interval_selector",
        )
        new_interval = refresh_opts[chosen_label]
        if new_interval != current_val:
            st.session_state["wc_refresh_interval"] = new_interval
            # Clear cache immediately so new interval takes effect
            from src.services.woocommerce.client import load_from_woocommerce

            load_from_woocommerce.clear()
            st.rerun()

        # ── Force refresh button ───────────────────────────────────────────
        last_sync = st.session_state.get("live_sync_time")
        if last_sync:
            elapsed_m = int((datetime.now() - last_sync).total_seconds() / 60)
            sync_label = (
                f"Last sync: {elapsed_m}m ago"
                if elapsed_m > 0
                else "Last sync: Just now"
            )
        else:
            sync_label = "Not synced yet"
        st.caption(sync_label)

        if st.button("🔄 Refresh Now", use_container_width=True, type="primary"):
            from src.services.woocommerce.client import load_live_source

            try:
                load_live_source(force_refresh=True)
                st.toast("⚡ Live data refreshed!")
            except Exception as e:
                st.error(f"Refresh failed: {e}")
            st.rerun()

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
            if st.button("Reset Tool Now", use_container_width=True, type="primary"):
                registered[tool_to_wipe]["fn"]()
                st.session_state.confirm_tool_reset = False
                st.success("Cleaned!")
                st.rerun()

        if st.button("Full System Reset", use_container_width=True, type="secondary"):
            st.session_state.confirm_app_reset = True

        if st.session_state.get("confirm_app_reset"):
            st.warning("⚠️ Reset All Workspace Data?")
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


def _render_sidebar(
    is_auth_on: bool,
    config_issues: list[str],
    nav_items: list[str],
    default_nav: str,
    on_change: Optional[Callable[[], None]] = None,
) -> str:
    """Render a clean, streamlined, and intuitive sidebar."""
    with st.sidebar:
        _render_sidebar_branding()
        _render_sidebar_user_context(is_auth_on)

        st.link_button(
            "🌐 Launch DEEN BI", CLOUD_APP_URL, use_container_width=True, type="primary"
        )

        st.divider()

        st.caption("🧭 WORKSPACE NAVIGATION")

        selected_nav = _render_nav_pills(
            nav_items, default_nav, key="sidebar_nav", on_change=on_change
        )

        st.divider()

        _render_sidebar_maintenance(is_auth_on, config_issues)
        return selected_nav


# ── Header rendering ────────────────────────────────────────────────────────


def _render_header(selected_nav: str) -> None:
    """Render the top header with clock and status banners."""
    from src.components.ui.clock import render_dynamic_clock

    # Show dynamic clock only on pages without the app banner
    if selected_nav != "\U0001f4c8 Live Dashboard":
        render_dynamic_clock(st.session_state.get("live_sync_time"))

    banner = st.session_state.get("header_status_banner", "")
    if banner:
        st.markdown(
            f'<div style="margin-top:8px;">{banner}</div>', unsafe_allow_html=True
        )


# ── Page routing ────────────────────────────────────────────────────────────


def _route_page(selected_nav: str) -> None:
    """Route to the correct page renderer based on sidebar selection.

    Jakob's Law Implementation:
    - 5 consolidated navigation tabs map to sub-feature selectors
    - Each tab uses session state to track which sub-feature to display
    """

    # Lazy imports keep bootstrap resilient on cloud
    # when a module has runtime incompatibilities.

    # === 📈 Live Dashboard (Home) ===
    if selected_nav == "📈 Live Dashboard":
        from src.components.layout.header import render_app_banner
        from src.pages.live_dashboard import render_live_tab

        safe_render(render_app_banner, fallback_msg="App banner unavailable.")
        safe_render(render_live_tab, fallback_msg="Live Dashboard unavailable.")

    # === 🛒 Orders & Fulfillment (Consolidated) ===
    elif selected_nav == "🛒 Orders & Fulfillment":
        # Get sub-feature selection from session state
        sub_feature = st.session_state.get("orders_sub_feature", "Order Tracking")

        # Render sub-feature selector if not already set
        if "orders_sub_feature" not in st.session_state:
            st.session_state.orders_sub_feature = "Order Tracking"

        with st.expander("📂 Select Feature", expanded=False):
            sub_feature = st.radio(
                "Choose a feature:",
                ["Order Tracking", "Pathao Processor", "Delivery Data Parser"],
                index=[
                    "Order Tracking",
                    "Pathao Processor",
                    "Delivery Data Parser",
                ].index(st.session_state.orders_sub_feature),
                label_visibility="collapsed",
                horizontal=True,
            )
            if sub_feature != st.session_state.orders_sub_feature:
                st.session_state.orders_sub_feature = sub_feature
                st.rerun()

        # Route to appropriate sub-feature
        if sub_feature == "Order Tracking":
            from src.pages.woocommerce_orders import render_woocommerce_orders_tab

            safe_render(
                render_woocommerce_orders_tab,
                fallback_msg="Order Tracking unavailable.",
            )
        elif sub_feature == "Pathao Processor":
            from src.pages.pathao_orders import render_pathao_tab

            safe_render(render_pathao_tab, fallback_msg="Pathao Processor unavailable.")
        elif sub_feature == "Delivery Data Parser":
            from src.pages.delivery_parser import render_fuzzy_parser_tab

            safe_render(
                render_fuzzy_parser_tab,
                fallback_msg="Delivery Data Parser unavailable.",
            )

    # === 📦 Inventory & Stock (Consolidated) ===
    elif selected_nav == "📦 Inventory & Stock":
        sub_feature = st.session_state.get("inventory_sub_feature", "Product Listing")

        if "inventory_sub_feature" not in st.session_state:
            st.session_state.inventory_sub_feature = "Product Listing"

        with st.expander("📂 Select Feature", expanded=False):
            sub_feature = st.radio(
                "Choose a feature:",
                [
                    "Product Listing",
                    "Current Stock Analytics",
                    "Inventory Distribution",
                ],
                index=[
                    "Product Listing",
                    "Current Stock Analytics",
                    "Inventory Distribution",
                ].index(st.session_state.inventory_sub_feature),
                label_visibility="collapsed",
                horizontal=True,
            )
            if sub_feature != st.session_state.inventory_sub_feature:
                st.session_state.inventory_sub_feature = sub_feature
                st.rerun()

        if sub_feature == "Product Listing":
            from src.pages.product_listing import render_product_listing_tab

            safe_render(
                render_product_listing_tab, fallback_msg="Product Listing unavailable."
            )
        elif sub_feature == "Current Stock Analytics":
            from src.pages.stock_analytics import render_stock_analytics_tab

            safe_render(
                render_stock_analytics_tab, fallback_msg="Stock Analytics unavailable."
            )
        elif sub_feature == "Inventory Distribution":
            from src.pages.inventory_distribution import render_distribution_tab

            safe_render(
                lambda: render_distribution_tab(
                    search_q=st.session_state.get("inv_matrix_search", "")
                ),
                fallback_msg="Inventory Distribution unavailable.",
            )

    # === 📊 Analytics & Insights (Consolidated) ===
    elif selected_nav == "📊 Analytics & Insights":
        sub_feature = st.session_state.get(
            "analytics_sub_feature", "Sales Data Ingestion"
        )

        if "analytics_sub_feature" not in st.session_state:
            st.session_state.analytics_sub_feature = "Sales Data Ingestion"

        with st.expander("📂 Select Feature", expanded=False):
            sub_feature = st.radio(
                "Choose a feature:",
                ["Sales Data Ingestion", "Return Analytics"],
                index=["Sales Data Ingestion", "Return Analytics"].index(
                    st.session_state.analytics_sub_feature
                ),
                label_visibility="collapsed",
                horizontal=True,
            )
            if sub_feature != st.session_state.analytics_sub_feature:
                st.session_state.analytics_sub_feature = sub_feature
                st.rerun()

        if sub_feature == "Sales Data Ingestion":
            from src.pages.sales_ingestion import render_manual_tab

            safe_render(
                render_manual_tab, fallback_msg="Sales Data Ingestion unavailable."
            )
        elif sub_feature == "Return Analytics":
            from src.pages.return_analytics import render_return_analytics_tab

            safe_render(
                render_return_analytics_tab,
                fallback_msg="Return Analytics unavailable.",
            )

    # === 🤖 Automation Tools (Consolidated) ===
    elif selected_nav == "🤖 Automation Tools":
        sub_feature = st.session_state.get(
            "automation_sub_feature", "WhatsApp Messaging"
        )

        if "automation_sub_feature" not in st.session_state:
            st.session_state.automation_sub_feature = "WhatsApp Messaging"

        with st.expander("📂 Select Feature", expanded=False):
            sub_feature = st.radio(
                "Choose a feature:",
                ["WhatsApp Messaging", "Data Pilot"],
                index=["WhatsApp Messaging", "Data Pilot"].index(
                    st.session_state.automation_sub_feature
                ),
                label_visibility="collapsed",
                horizontal=True,
            )
            if sub_feature != st.session_state.automation_sub_feature:
                st.session_state.automation_sub_feature = sub_feature
                st.rerun()

        if sub_feature == "WhatsApp Messaging":
            from src.pages.whatsapp_messaging import render_wp_tab

            safe_render(render_wp_tab, fallback_msg="WhatsApp Messaging unavailable.")
        elif sub_feature == "Data Pilot":
            from src.pages.data_pilot import render_ai_pilot_page

            safe_render(render_ai_pilot_page, fallback_msg="Data Pilot unavailable.")


# ── Public entry point ──────────────────────────────────────────────────────


def run_app() -> None:
    """Main application bootstrap — orchestrates auth, sidebar, routing, and footer."""
    # ── Authentication ──────────────────────────────────────────────────────
    is_auth_on = auth_is_configured()
    config_issues = validate_runtime_configuration()

    if not is_auth_on and not is_unauthenticated_access_allowed():
        st.error("Authentication is not configured. Access is disabled by default.")
        st.info(
            "Configure the [auth] secrets block. For local development only, set "
            "DEEN_OPS_ALLOW_UNAUTHENTICATED=true."
        )
        st.stop()

    if is_auth_on and not st.user.is_logged_in:
        _render_auth_gate()

    # ── Lazy imports (kept inside function for cloud resilience) ────────────
    from src.components.layout.footer import render_footer
    from src.components.layout.header import render_header
    from src.components.ui.bike_animation import render_bike_animation
    from src.components.ui.styles import inject_base_styles

    # Jakob's Law: Navigation already consolidated to 5 tabs in ui_config.py
    # No runtime modifications needed - navigation is statically defined

    # Prevent duplicate entries (defensive check)
    PRIMARY_NAV[:] = list(dict.fromkeys(PRIMARY_NAV))

    # ── State & styles ──────────────────────────────────────────────────────
    init_state()
    # Streamlit Cloud uses ephemeral disk, so the committed customer registry is
    # the baseline after every restart. Merge the last persisted sales snapshot
    # (the app's own recent-order cache) into the full registry at startup so the
    # new/returning metric is as fresh as the last sync, not just the git baseline.
    # Seeded in a background thread once per session to eliminate cold-start lag.
    if not st.session_state.get("_customer_registry_seeded"):
        st.session_state["_customer_registry_seeded"] = True

        def _seed_registry_bg():
            try:
                from src.utils.customer_registry_full import (
                    update_full_registry_from_df,
                )
                from src.utils.snapshots import load_sales_snapshot

                _snap = load_sales_snapshot()
                if _snap is not None and not _snap.empty:
                    update_full_registry_from_df(_snap)
            except Exception:
                pass

        import threading

        threading.Thread(
            target=_seed_registry_bg, daemon=True, name="CustomerRegistrySeed"
        ).start()
    inject_base_styles()
    _rotate_error_logs()

    # Clear previous header banner to ensure tool-specific display
    if "header_status_banner" not in st.session_state:
        st.session_state.header_status_banner = ""

    # ── Sidebar & Mobile Navigation State ───────────────────────────────────
    default_nav = (
        "\U0001f4c8 Live Dashboard"
        if "\U0001f4c8 Live Dashboard" in PRIMARY_NAV
        else PRIMARY_NAV[0]
    )

    if "selected_nav" not in st.session_state:
        st.session_state["selected_nav"] = default_nav
    if "sidebar_nav" not in st.session_state:
        st.session_state["sidebar_nav"] = st.session_state["selected_nav"]
    if "mobile_bottom_nav" not in st.session_state:
        st.session_state["mobile_bottom_nav"] = st.session_state["selected_nav"]

    def _sync_from_sidebar() -> None:
        chosen = st.session_state.get("sidebar_nav")
        if chosen:
            st.session_state["selected_nav"] = chosen
            st.session_state["mobile_bottom_nav"] = chosen

    def _sync_from_mobile() -> None:
        chosen = st.session_state.get("mobile_bottom_nav")
        if chosen:
            st.session_state["selected_nav"] = chosen
            st.session_state["sidebar_nav"] = chosen

    # Handle nav override from sidebar shortcut buttons or pages
    if st.session_state.get("_nav_override"):
        override_target = st.session_state.pop("_nav_override")
        from src.config.ui_config import LEGACY_NAV_MAPPING

        mapped_target = LEGACY_NAV_MAPPING.get(override_target, override_target)
        if mapped_target in PRIMARY_NAV:
            st.session_state["selected_nav"] = mapped_target
            st.session_state["sidebar_nav"] = mapped_target
            st.session_state["mobile_bottom_nav"] = mapped_target

    selected_nav = _render_sidebar(
        is_auth_on,
        config_issues,
        PRIMARY_NAV,
        st.session_state["selected_nav"],
        on_change=_sync_from_sidebar,
    )
    if selected_nav:
        st.session_state["selected_nav"] = selected_nav
        st.session_state["mobile_bottom_nav"] = selected_nav

    # ── Header placeholder ──────────────────────────────────────────────────
    header_container = st.empty()

    if st.session_state.get("show_animation"):
        render_bike_animation()

    # ── Page routing with smooth transition wrapper ──────────────────────
    current_page = st.session_state["selected_nav"]
    st.markdown(
        f'<div class="page-view-wrapper page-nav-{abs(hash(current_page))}">',
        unsafe_allow_html=True,
    )
    _route_page(current_page)
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Re-render header with any injected content ─────────────────────────
    with header_container:
        # On Live Dashboard the banner already contains the title — skip full header
        if current_page != "\U0001f4c8 Live Dashboard":
            render_header(lambda: _render_header(current_page))
        else:
            _render_header(current_page)

    # Reset banner for next run to avoid bleeding into other pages
    st.session_state.header_status_banner = ""

    # ── Mobile Bottom Navigation Bar (Fixed on mobile viewports) ───────────
    from src.components.ui.mobile_navbar import render_mobile_navbar

    render_mobile_navbar(
        PRIMARY_NAV,
        current_nav=current_page,
        on_change=_sync_from_mobile,
    )

    # ── Footer ──────────────────────────────────────────────────────────────
    render_footer()
