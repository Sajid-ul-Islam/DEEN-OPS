import streamlit as st

APP_TITLE = "DEEN OPS Terminal"
APP_VERSION = "v10.0"

PRIMARY_NAV = [
    "📈 Live Dashboard",
    "📥 Sales Data Ingestion",
    "📦 Current Stock Analytics",
    "📦 Pathao Processor",
    "📊 Inventory Distribution",
    "💬 WhatsApp Messaging",
    "🧩 Delivery Data Parser",
    "🚀 Data Pilot",
    "🛒 WooCommerce Orders",
]

CLOUD_APP_URL = "https://deen-business-intel.streamlit.app/"


INVENTORY_LOCATIONS = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet"]

STATUS_COLORS = {
    "success": "#15803d",
    "warning": "#b45309",
    "error": "#b91c1c",
    "info": "#1d4ed8",
}

# Pathao API Configuration
def get_pathao_config():
    """Load configuration from Streamlit secrets or local fallback."""
    try:
        if "pathao" in st.secrets:
            return dict(st.secrets["pathao"])
    except:
        pass

    # Fallback: Load from .streamlit/secrets.toml if running locally/offline
    try:
        import os
        import toml
        secrets_path = os.path.join(".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                data = toml.load(f)
                if "pathao" in data:
                    return data["pathao"]
    except:
        pass

    # Ultimate hardcoded fallback
    return {
        "base_url": "https://courier-api-sandbox.pathao.com",
        "client_id": "7N1aMJQbWm",
        "client_secret": "wRcaibZkUdSNz2EI9ZyuXLlNrnAv0TdPUPXMnD39",
        "username": "",
        "password": "lovePathao"
    }

PATHAO_CONFIG = get_pathao_config()
