"""Pathao order status and credential verification helpers."""

import requests
import streamlit as st

from src.services.pathao.client import PathaoClient


def get_pathao_credentials() -> dict | None:
    """Extract Pathao credentials from Streamlit secrets."""
    try:
        creds = dict(st.secrets["pathao"])
    except (FileNotFoundError, KeyError, TypeError):
        return None

    required = ("base_url", "client_id", "client_secret", "username", "password")
    if not all(creds.get(key) for key in required):
        return None
    return creds


def _build_pathao_client() -> tuple[PathaoClient | None, str | None]:
    """Create a Pathao client from configured credentials."""
    creds = get_pathao_credentials()
    if not creds:
        return None, (
            "Pathao credentials not found in .streamlit/secrets.toml. "
            "Please add a complete [pathao] section."
        )

    try:
        return PathaoClient(**creds), None
    except Exception as exc:
        return None, f"Failed to initialize Pathao client: {exc}"


def verify_pathao_connection() -> tuple[bool, str]:
    """
    Verify if the Pathao credentials are working by requesting an access token.
    
    Returns:
        Tuple of (is_successful, status_message).
    """
    client, error = _build_pathao_client()
    if error:
        return False, error

    try:
        client.ensure_token()
        if client.access_token:
            return True, "Successfully authenticated with Pathao API. Credentials are working."
        return False, "Authentication failed. Pathao did not return an access token."
    except Exception as exc:
        return False, f"Connection error: {exc}"


def get_pathao_order_status(consignment_id: str) -> dict:
    """
    Fetch the live status of a specific Pathao order.
    
    Args:
        consignment_id: The Pathao Consignment ID (e.g., starts with 'DD...')
        
    Returns:
        Dictionary containing the order status or an error message.
    """
    client, error = _build_pathao_client()
    if error:
        return {"error": error}

    try:
        headers = client._get_headers()
        if not client.access_token:
            return {"error": "Authentication failed. Pathao access token is unavailable."}

        status_url = f"{client.base_url}/aladdin/api/v1/orders/{consignment_id}/info"
        status_response = requests.get(status_url, headers=headers, timeout=10)
        if status_response.status_code == 200:
            return status_response.json()

        return {"error": f"Failed to fetch status: {status_response.status_code} - {status_response.text}"}

    except Exception as exc:
        return {"error": f"Request failed: {exc}"}
