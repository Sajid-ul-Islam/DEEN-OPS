APP_TITLE = "DEEN Business Intelligence"
APP_VERSION = "v9.6"

PRIMARY_NAV = [
    "📈 Live Dashboard",
    "📥 Sales Data Ingestion",
    "📦 Current Stock Analytics",
    "📦 Bulk Order Processer",
    "📊 Inventory Distribution",
    "💬 WhatsApp Messaging",
    "🧩 Delivery Data Parser",
    "🌐 Cloud BI",
]

CLOUD_APP_URL = "https://deen-business-intel.streamlit.app/"

MORE_TOOLS = [
    "System Logs",
    "Dev Lab",
]

INVENTORY_LOCATIONS = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet"]

STATUS_COLORS = {
    "success": "#15803d",
    "warning": "#b45309",
    "error": "#b91c1c",
    "info": "#1d4ed8",
}

# Fallback Data Sources
DEFAULT_GSHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOiRkybNzMNvEaLxSFsX0nGIiM07BbNVsBbsX1dG8AmGOmSu8baPrVYL0cOqoYN4tRWUj1UjUbH1Ij/pub?gid=2118542421&single=true&output=csv"

# Pathao API Configuration
def get_pathao_config():
    """Load configuration from Streamlit secrets or local fallback."""
    try:
        import streamlit as st
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
