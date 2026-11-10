"""WordPress and WooCommerce authentication service.

Authenticates user credentials against the WordPress REST API (/wp-json/wp/v2/users/me),
verifies user roles and administrative privileges, and supports configured admin credentials
in secrets.toml.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

from src.config.settings import (
    get_secret_section,
    get_woocommerce_config,
)
from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event

DEFAULT_ALLOWED_ROLES = frozenset({"administrator", "shop_manager", "editor", "author"})


@dataclass
class AuthUser:
    """Authenticated user model representing WordPress/WooCommerce identity."""

    username: str
    display_name: str
    email: str
    roles: list[str]
    is_admin: bool
    auth_method: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for session serialization."""
        return asdict(self)


def is_user_authenticated(user_data: Any) -> bool:
    """Check whether a user dictionary or AuthUser instance represents an authenticated session."""
    if not user_data:
        return False
    if isinstance(user_data, dict):
        return bool(user_data.get("username") and user_data.get("auth_method"))
    if isinstance(user_data, AuthUser):
        return bool(user_data.username and user_data.auth_method)
    return False


def authenticate_wordpress_user(
    username: str,
    password: str,
    store_url: str | None = None,
) -> tuple[bool, Optional[AuthUser], str]:
    """Authenticate a user against WordPress / WooCommerce.

    Tries the following verification mechanisms in sequence:
    1. Pre-configured admin or staff credentials in `[auth]` secrets.
    2. WooCommerce REST API Consumer Key & Secret match.
    3. Live WordPress REST API (`/wp-json/wp/v2/users/me`) with Basic Auth / Application Password.
    4. Live WordPress Web Login (`/wp-login.php`) form submission fallback.

    Parameters
    ----------
    username : str
        WordPress username or email.
    password : str
        WordPress account password or Application Password.
    store_url : str, optional
        Base URL of the WordPress / WooCommerce installation.

    Returns
    -------
    tuple[bool, Optional[AuthUser], str]
        (success, user_obj, status_message)
    """
    clean_user = str(username or "").strip()
    clean_pass = str(password or "").strip()

    if not clean_user or not clean_pass:
        return False, None, "Please enter both username and password."

    # ── 1. Check configured admin credentials in secrets.toml (Fast local path) ──
    auth_sec = get_secret_section("auth")
    if auth_sec:
        admin_u = auth_sec.get("admin_username") or auth_sec.get("username")
        admin_p = auth_sec.get("admin_password") or auth_sec.get("password")
        if admin_u and admin_p:
            if clean_user.lower() == str(admin_u).strip().lower() and clean_pass == str(
                admin_p
            ):
                return (
                    True,
                    AuthUser(
                        username=clean_user,
                        display_name=auth_sec.get("display_name", clean_user),
                        email=auth_sec.get("email", ""),
                        roles=["administrator"],
                        is_admin=True,
                        auth_method="configured_admin",
                    ),
                    "Login successful.",
                )

        # Check multi-user dictionary in [auth.users]
        users_map = auth_sec.get("users", {})
        if isinstance(users_map, dict):
            for u_key, u_val in users_map.items():
                if clean_user.lower() == str(u_key).strip().lower():
                    if isinstance(u_val, str) and u_val == clean_pass:
                        return (
                            True,
                            AuthUser(
                                username=clean_user,
                                display_name=clean_user,
                                email="",
                                roles=["administrator"],
                                is_admin=True,
                                auth_method="configured_admin",
                            ),
                            "Login successful.",
                        )
                    if isinstance(u_val, dict) and str(
                        u_val.get("password", "")
                    ) == str(clean_pass):
                        return (
                            True,
                            AuthUser(
                                username=clean_user,
                                display_name=u_val.get("name", clean_user),
                                email=u_val.get("email", ""),
                                roles=u_val.get("roles", ["administrator"]),
                                is_admin="administrator"
                                in u_val.get("roles", ["administrator"]),
                                auth_method="configured_admin",
                            ),
                            "Login successful.",
                        )

    # ── 2. Check WooCommerce Consumer Key & Secret ──────────────────────────────
    wc_cfg = get_woocommerce_config(required=False)
    ck = str(wc_cfg.get("consumer_key", "")).strip()
    cs = str(wc_cfg.get("consumer_secret", "")).strip()
    if ck and cs and clean_user == ck and clean_pass == cs:
        return (
            True,
            AuthUser(
                username="wc_admin",
                display_name="WooCommerce Admin",
                email="",
                roles=["administrator"],
                is_admin=True,
                auth_method="woocommerce_api",
            ),
            "Login successful via WooCommerce API credentials.",
        )

    # Resolve store base URL
    base_url = (store_url or wc_cfg.get("store_url") or "").rstrip("/")
    if not base_url:
        return (
            False,
            None,
            "WooCommerce store URL is not configured. Please check secrets.toml.",
        )

    # ── 3. Live WordPress REST API (/wp-json/wp/v2/users/me) ───────────────────
    api_url = f"{base_url}/wp-json/wp/v2/users/me"
    headers = {
        "User-Agent": "DEEN-OPS/1.0",
        "Accept": "application/json",
    }
    auth = HTTPBasicAuth(clean_user, clean_pass)

    rest_error_msg = ""
    try:
        res = request_with_backoff(
            "GET",
            api_url,
            auth=auth,
            headers=headers,
            timeout=12,
            max_attempts=1,
        )
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict):
                roles = data.get("roles", [])
                caps = data.get("capabilities", {})
                is_admin = (
                    "administrator" in roles
                    or bool(caps.get("administrator"))
                    or bool(caps.get("manage_woocommerce"))
                )
                is_authorized = (
                    is_admin
                    or any(r in DEFAULT_ALLOWED_ROLES for r in roles)
                    or bool(caps.get("manage_woocommerce"))
                )

                if roles and not is_authorized:
                    return (
                        False,
                        None,
                        f"User '{clean_user}' does not have administrative access to DEEN-OPS.",
                    )

                display_name = (
                    data.get("name")
                    or data.get("slug")
                    or data.get("username")
                    or clean_user
                )
                email = data.get("email") or ""
                return (
                    True,
                    AuthUser(
                        username=data.get("slug") or clean_user,
                        display_name=display_name,
                        email=email,
                        roles=roles if roles else ["administrator"],
                        is_admin=bool(is_admin),
                        auth_method="wordpress_rest",
                    ),
                    "Login successful.",
                )
    except requests.HTTPError as http_err:
        res = getattr(http_err, "response", None)
        if res is not None:
            try:
                err_json = res.json()
                rest_error_msg = err_json.get("message", "")
            except Exception:
                rest_error_msg = ""
    except Exception as e:
        log_system_event("WP_AUTH_REST_ERROR", str(e))

    # ── 4. Live WordPress Web Login (/wp-login.php) Fallback ───────────────────
    # If standard account password was used without an Application Password
    try:
        login_data = {
            "log": clean_user,
            "pwd": clean_pass,
            "rememberme": "forever",
            "redirect_to": f"{base_url}/wp-admin/",
            "testcookie": "1",
            "wp-submit": "Log In",
        }
        post_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"{base_url}/wp-login.php",
        }
        post_res = request_with_backoff(
            "POST",
            f"{base_url}/wp-login.php",
            data=login_data,
            headers=post_headers,
            allow_redirects=False,
            timeout=12,
            max_attempts=1,
            cookies={"wordpress_test_cookie": "WP+Cookie+check"},
        )

        has_auth_cookie = any(
            "wordpress_logged_in" in c for c in post_res.cookies.keys()
        ) or any("wordpress_sec" in c for c in post_res.cookies.keys())
        is_302 = post_res.status_code == 302
        redirect_url = post_res.headers.get("Location", "")

        if (is_302 and "wp-admin" in redirect_url) or has_auth_cookie:
            return (
                True,
                AuthUser(
                    username=clean_user,
                    display_name=clean_user,
                    email="",
                    roles=["administrator"],
                    is_admin=True,
                    auth_method="wordpress_web",
                ),
                "Login successful.",
            )
    except requests.HTTPError as http_err:
        post_res = getattr(http_err, "response", None)
        if post_res is not None:
            has_auth_cookie = any(
                "wordpress_logged_in" in c for c in post_res.cookies.keys()
            ) or any("wordpress_sec" in c for c in post_res.cookies.keys())
            is_302 = post_res.status_code == 302
            redirect_url = post_res.headers.get("Location", "")
            if (is_302 and "wp-admin" in redirect_url) or has_auth_cookie:
                return (
                    True,
                    AuthUser(
                        username=clean_user,
                        display_name=clean_user,
                        email="",
                        roles=["administrator"],
                        is_admin=True,
                        auth_method="wordpress_web",
                    ),
                    "Login successful.",
                )
    except Exception as e:
        log_system_event("WP_AUTH_WEB_ERROR", str(e))

    final_msg = (
        rest_error_msg
        if rest_error_msg
        else "Invalid WordPress username or password. Check your credentials or use a WordPress Application Password."
    )
    return False, None, final_msg
