"""Pathao Order Status and Credential Verification Module."""

import requests
import streamlit as st


def get_pathao_credentials() -> dict | None:
    """Extract Pathao credentials from Streamlit secrets."""
    try:
        return st.secrets["pathao"]
    except (FileNotFoundError, KeyError):
        return None


def verify_pathao_connection() -> tuple[bool, str]:
    """
    Verify if the Pathao credentials are working by requesting an access token.
    
    Returns:
        Tuple of (is_successful, status_message).
    """
    creds = get_pathao_credentials()
    if not creds:
        return False, "Pathao credentials not found in .streamlit/secrets.toml. Please add a [pathao] section."
    
    base_url = creds.get("base_url", "https://api-hermes.pathao.com")
    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")
    username = creds.get("username")
    password = creds.get("password")
    
    if not all([client_id, client_secret, username, password]):
        return False, "Missing one or more required credentials (client_id, client_secret, username, password)."
        
    auth_url = f"{base_url.rstrip('/')}/aladdin/api/v1/issue-token"
    
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": password,
        "grant_type": "password"
    }
    
    try:
        response = requests.post(auth_url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "access_token" in data:
                return True, "✅ Successfully authenticated with Pathao API. Credentials are working!"
        
        return False, f"❌ Authentication failed: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"❌ Connection error: {str(e)}"


def get_pathao_order_status(consignment_id: str) -> dict:
    """
    Fetch the live status of a specific Pathao order.
    
    Args:
        consignment_id: The Pathao Consignment ID (e.g., starts with 'DD...')
        
    Returns:
        Dictionary containing the order status or an error message.
    """
    success, msg = verify_pathao_connection()
    if not success:
        return {"error": msg}
        
    creds = get_pathao_credentials()
    base_url = creds.get("base_url", "https://api-hermes.pathao.com")
    
    auth_url = f"{base_url.rstrip('/')}/aladdin/api/v1/issue-token"
    payload = {
        "client_id": creds.get("client_id"),
        "client_secret": creds.get("client_secret"),
        "username": creds.get("username"),
        "password": creds.get("password"),
        "grant_type": "password"
    }
    
    try:
        # 1. Get Token
        token_response = requests.post(auth_url, json=payload, timeout=10)
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        
        # 2. Fetch Status
        status_url = f"{base_url.rstrip('/')}/aladdin/api/v1/orders/{consignment_id}/info"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        status_response = requests.get(status_url, headers=headers, timeout=10)
        if status_response.status_code == 200:
            return status_response.json()
            
        return {"error": f"Failed to fetch status: {status_response.status_code} - {status_response.text}"}
        
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}