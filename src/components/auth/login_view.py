"""WordPress / WooCommerce login gate UI component.

Provides an enterprise-styled, responsive authentication screen allowing
administrators and shop managers to log in using WordPress credentials,
WordPress Application Passwords, or WooCommerce API credentials.
"""

from __future__ import annotations

import base64
import os
import streamlit as st

from src.components.ui.styles import inject_base_styles
from src.config.settings import get_secret_section
from src.services.auth.wordpress_auth import (
    authenticate_wordpress_user,
    is_user_authenticated,
)


def render_login_gate() -> None:
    """Render the full-page WordPress & WooCommerce authentication screen."""
    # If already authenticated, do nothing
    if is_user_authenticated(st.session_state.get("auth_user")):
        return

    inject_base_styles()

    # Custom styling for the login card
    st.markdown(
        """
        <style>
        .login-card {
            background: #ffffff;
            border-radius: 16px;
            padding: 32px 28px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.04);
            border: 1px solid #e5e7eb;
            max-width: 440px;
            margin: 40px auto 20px auto;
        }
        .login-header {
            text-align: center;
            margin-bottom: 24px;
        }
        .login-title {
            font-size: 22px;
            font-weight: 800;
            color: #111827;
            margin-top: 12px;
            letter-spacing: -0.02em;
        }
        .login-sub {
            font-size: 13px;
            color: #6b7280;
            margin-top: 4px;
        }
        .login-badge {
            display: inline-block;
            background: #ecfdf5;
            color: #065f46;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 10px;
            border-radius: 9999px;
            margin-top: 8px;
            border: 1px solid #a7f3d0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    logo_path = os.path.join("assets", "deen_logo.jpg")
    logo_html = ""
    if os.path.exists(logo_path):
        try:
            with open(logo_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                logo_html = (
                    f'<img src="data:image/jpeg;base64,{b64}" '
                    f'style="width: 72px; height: 72px; border-radius: 14px; object-fit: cover; box-shadow: 0 4px 12px rgba(0,0,0,0.12);">'
                )
        except Exception:
            logo_html = '<div style="font-size: 48px;">🛡️</div>'
    else:
        logo_html = '<div style="font-size: 48px;">🛡️</div>'

    _, col_center, _ = st.columns([1, 1.8, 1])

    with col_center:
        st.markdown(
            f"""
            <div class="login-card">
                <div class="login-header">
                    {logo_html}
                    <div class="login-title">DEEN-OPS Terminal</div>
                    <div class="login-sub">AI-Assisted Operations & Dispatch Workspace</div>
                    <div class="login-badge">🔐 WordPress & WooCommerce Admin</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("wp_admin_login_form", clear_on_submit=False):
            username = st.text_input(
                "Username or Email",
                placeholder="e.g. admin or ops@deencommerce.com",
                key="wp_auth_user_input",
                help="Your WordPress administrator or shop manager username",
            ).strip()

            password = st.text_input(
                "Password",
                type="password",
                placeholder="WordPress account or Application Password",
                key="wp_auth_pass_input",
                help="Your WordPress password or generated Application Password",
            ).strip()

            submitted = st.form_submit_button(
                "🔓 Sign In to DEEN-OPS",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not username or not password:
                st.error("Please enter both username and password.")
            else:
                with st.spinner("Verifying WordPress administrator credentials..."):
                    success, auth_user, msg = authenticate_wordpress_user(
                        username=username,
                        password=password,
                    )

                if success and auth_user:
                    st.session_state["auth_user"] = auth_user.to_dict()
                    st.toast(f"✅ Welcome, {auth_user.display_name}!")
                    st.success(f"Authenticated as **{auth_user.display_name}**.")
                    st.rerun()
                else:
                    st.error(f"❌ Authentication failed: {msg}")

        # Helpful guidance expander
        with st.expander(
            "ℹ️ Login Instructions & Application Passwords", expanded=False
        ):
            st.markdown(
                """
                **Authentication Options:**
                1. **Standard WordPress Password**: Enter your regular WordPress admin username and password.
                2. **WordPress Application Password** *(Recommended)*:
                   - Log into **WordPress Admin** (`/wp-admin`).
                   - Go to **Users > Profile**.
                   - Scroll down to **Application Passwords**.
                   - Enter `DEEN OPS` as the new name and click **Add New Application Password**.
                   - Use your WordPress username with the generated 24-character code.
                3. **WooCommerce API Key**: You can also use your WooCommerce `Consumer Key` as the username and `Consumer Secret` as the password.
                """
            )

        # Check if Google OIDC is also configured as an alternative
        auth_sec = get_secret_section("auth")
        if (
            auth_sec
            and auth_sec.get("google")
            and hasattr(st, "login")
            and callable(st.login)
        ):
            st.divider()
            st.caption("Or authenticate with company Google workspace:")
            if st.button(
                "Log in with Google", use_container_width=True, type="secondary"
            ):
                st.login()

        from src.config.settings import is_unauthenticated_access_allowed

        if is_unauthenticated_access_allowed():
            st.divider()
            if st.button(
                "🔓 Continue as Guest (Development Bypass)",
                use_container_width=True,
                type="secondary",
            ):
                st.session_state["_bypass_auth"] = True
                st.rerun()

    st.stop()
