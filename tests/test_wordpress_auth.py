"""Unit tests for WordPress and WooCommerce authentication services."""

from unittest.mock import MagicMock, patch

from src.services.auth.wordpress_auth import (
    AuthUser,
    authenticate_wordpress_user,
    is_user_authenticated,
)


def test_auth_user_model():
    user = AuthUser(
        username="sajid",
        display_name="Sajid Ul Islam",
        email="sajid@deencommerce.com",
        roles=["administrator"],
        is_admin=True,
        auth_method="wordpress_rest",
    )
    d = user.to_dict()
    assert d["username"] == "sajid"
    assert d["is_admin"] is True
    assert is_user_authenticated(user) is True
    assert is_user_authenticated(d) is True
    assert is_user_authenticated(None) is False
    assert is_user_authenticated({}) is False


def test_authenticate_empty_credentials():
    success, user, msg = authenticate_wordpress_user("", "")
    assert success is False
    assert user is None
    assert "enter both" in msg.lower()


def test_authenticate_configured_admin_credentials():
    mock_auth_sec = {
        "admin_username": "ops_admin",
        "admin_password": "SuperSecretPassword123!",
        "display_name": "Operations Lead",
        "email": "ops@deencommerce.com",
    }
    with patch(
        "src.services.auth.wordpress_auth.get_secret_section",
        return_value=mock_auth_sec,
    ):
        success, user, msg = authenticate_wordpress_user(
            "ops_admin", "SuperSecretPassword123!"
        )
        assert success is True
        assert user is not None
        assert user.username == "ops_admin"
        assert user.display_name == "Operations Lead"
        assert user.is_admin is True
        assert user.auth_method == "configured_admin"


def test_authenticate_configured_users_map():
    mock_auth_sec = {
        "users": {
            "manager": "Pass123!",
            "lead": {
                "password": "LeadPass456!",
                "name": "Team Lead",
                "roles": ["shop_manager"],
            },
        }
    }
    with patch(
        "src.services.auth.wordpress_auth.get_secret_section",
        return_value=mock_auth_sec,
    ):
        # Plain string password
        ok1, user1, _ = authenticate_wordpress_user("manager", "Pass123!")
        assert ok1 is True
        assert user1.username == "manager"

        # Dict-based user
        ok2, user2, _ = authenticate_wordpress_user("lead", "LeadPass456!")
        assert ok2 is True
        assert user2.display_name == "Team Lead"
        assert "shop_manager" in user2.roles

        # Wrong password
        ok3, user3, _ = authenticate_wordpress_user("lead", "WrongPass")
        assert ok3 is False


def test_authenticate_woocommerce_api_keys():
    wc_cfg = {
        "store_url": "https://deencommerce.com",
        "consumer_key": "ck_test_12345",
        "consumer_secret": "cs_test_67890",
    }
    with (
        patch("src.services.auth.wordpress_auth.get_secret_section", return_value={}),
        patch(
            "src.services.auth.wordpress_auth.get_woocommerce_config",
            return_value=wc_cfg,
        ),
    ):
        success, user, msg = authenticate_wordpress_user(
            "ck_test_12345", "cs_test_67890"
        )
        assert success is True
        assert user is not None
        assert user.auth_method == "woocommerce_api"


def test_authenticate_wordpress_rest_api_success():
    wc_cfg = {"store_url": "https://deencommerce.com"}
    mock_wp_response = MagicMock()
    mock_wp_response.status_code = 200
    mock_wp_response.json.return_value = {
        "id": 1,
        "name": "Deen Admin",
        "slug": "deenadmin",
        "email": "admin@deencommerce.com",
        "roles": ["administrator"],
        "capabilities": {"administrator": True, "manage_woocommerce": True},
    }

    with (
        patch("src.services.auth.wordpress_auth.get_secret_section", return_value={}),
        patch(
            "src.services.auth.wordpress_auth.get_woocommerce_config",
            return_value=wc_cfg,
        ),
        patch(
            "src.services.auth.wordpress_auth.request_with_backoff",
            return_value=mock_wp_response,
        ),
    ):
        success, user, msg = authenticate_wordpress_user("deenadmin", "MyPassword!123")
        assert success is True
        assert user is not None
        assert user.display_name == "Deen Admin"
        assert user.is_admin is True
        assert user.auth_method == "wordpress_rest"


def test_authenticate_wordpress_rest_api_insufficient_role():
    wc_cfg = {"store_url": "https://deencommerce.com"}
    mock_wp_response = MagicMock()
    mock_wp_response.status_code = 200
    mock_wp_response.json.return_value = {
        "id": 42,
        "name": "Customer Account",
        "slug": "customer",
        "email": "customer@gmail.com",
        "roles": ["customer"],
        "capabilities": {},
    }

    with (
        patch("src.services.auth.wordpress_auth.get_secret_section", return_value={}),
        patch(
            "src.services.auth.wordpress_auth.get_woocommerce_config",
            return_value=wc_cfg,
        ),
        patch(
            "src.services.auth.wordpress_auth.request_with_backoff",
            return_value=mock_wp_response,
        ),
    ):
        success, user, msg = authenticate_wordpress_user("customer", "MyPassword!123")
        assert success is False
        assert user is None
        assert "administrative access" in msg


def test_authenticate_wordpress_web_login_fallback():
    import requests

    wc_cfg = {"store_url": "https://deencommerce.com"}
    # REST API fails with 401 HTTPError
    mock_rest_response = MagicMock()
    mock_rest_response.status_code = 401
    mock_rest_response.json.return_value = {"message": "Invalid password"}
    rest_err = requests.HTTPError(response=mock_rest_response)

    # Web login succeeds with 302 redirect
    mock_post_res = MagicMock()
    mock_post_res.status_code = 302
    mock_post_res.headers = {"Location": "https://deencommerce.com/wp-admin/"}
    mock_post_res.cookies = {"wordpress_logged_in_abc123": "token_val"}

    with (
        patch("src.services.auth.wordpress_auth.get_secret_section", return_value={}),
        patch(
            "src.services.auth.wordpress_auth.get_woocommerce_config",
            return_value=wc_cfg,
        ),
        patch(
            "src.services.auth.wordpress_auth.request_with_backoff",
            side_effect=[rest_err, mock_post_res],
        ),
    ):
        success, user, msg = authenticate_wordpress_user("webadmin", "RegularPassword")
        assert success is True
        assert user is not None
        assert user.auth_method == "wordpress_web"


def test_render_login_gate_already_authenticated():
    from src.components.auth.login_view import render_login_gate

    # If auth_user is already present, render_login_gate returns early
    with patch(
        "streamlit.session_state",
        {"auth_user": {"username": "admin", "auth_method": "test"}},
    ):
        render_login_gate()
