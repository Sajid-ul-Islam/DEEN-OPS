# Jakob's Law Compliant Navigation (max 5 tabs)
# Rule 1: Home on far left
# Rule 2: Profile/Settings on far right (moved to sidebar per best practices)
# Rule 3: Core actions only in bottom nav
# Rule 4: Settings NOT in bottom nav (already in sidebar)
PRIMARY_NAV = [
    "📈 Live Dashboard",  # Home - far left
    "📋 Product Listing",  # Product Listing (Outlet Dispatch, Picking & Pathao Bulk)
    "🧩 Data Parser",  # Data Parser (Delivery Parsing & Item Description Helper)
    "📊 Analytics & Insights",  # Core action: Analytics & Insights
]

# Legacy nav items mapped to consolidated structure
LEGACY_NAV_MAPPING = {
    # Section: Live Dashboard
    "📈 Live Dashboard": "📈 Live Dashboard",
    # Section: Orders & Fulfillment (Legacy Fallback)
    "🛒 Orders & Fulfillment": "📈 Live Dashboard",
    "🛒 Order Tracking": "📈 Live Dashboard",
    "🛒 Order tracking": "📈 Live Dashboard",
    # Section: Product Listing (Moved to sidebar)
    "📋 Product Listing": "📋 Product Listing",
    "Product Listing": "📋 Product Listing",
    "🏬 Outlet Dispatch & Product Listing": "📋 Product Listing",
    "Outlet Dispatch & Product Listing": "📋 Product Listing",
    "🏬 Outlet Wise Extractor": "📋 Product Listing",
    "Outlet Wise Extractor": "📋 Product Listing",
    "🏬 SIP Outlet Mapper": "📋 Product Listing",
    "SIP Outlet Mapper": "📋 Product Listing",
    # Section: Data Parser (Moved to sidebar)
    "🧩 Data Parser": "🧩 Data Parser",
    "Data Parser": "🧩 Data Parser",
    "🧩 Delivery Data Parser": "🧩 Data Parser",
    "Delivery Data Parser": "🧩 Data Parser",
    "📦 Pathao Processor": "🧩 Data Parser",
    # Section: Inventory & Stock (Legacy Fallback)
    "📦 Current Stock Analytics": "📈 Live Dashboard",
    "Current Stock Analytics": "📈 Live Dashboard",
    "SIP Stock - Smart Inventory with POS": "📈 Live Dashboard",
    "📦 SIP Stock - Smart Inventory with POS": "📈 Live Dashboard",
    "📦 Inventory & Stock": "📈 Live Dashboard",
    # Section: Analytics & Insights
    "📥 Sales Data Ingestion": "📊 Analytics & Insights",
    "📉 Return Analytics": "📊 Analytics & Insights",
    "📊 Analytics & Insights": "📊 Analytics & Insights",
}

LEGACY_SUBFEATURE_MAPPING = {
    "📥 Sales Data Ingestion": ("analytics_sub_feature", "Sales Data Ingestion"),
    "📉 Return Analytics": ("analytics_sub_feature", "Returns"),
    "🔎 Return Orders Extractor": ("analytics_sub_feature", "Returns"),
}


CLOUD_APP_URL = "https://deen-business-intel.streamlit.app/"


INVENTORY_LOCATIONS = ["Ecom", "Mirpur", "Wari", "Cumilla", "Sylhet"]

CHART_THEMES = {
    "✨ Emerald Cyberpunk": {
        "scale": "Viridis",
        "primary": "#10b981",
        "secondary": "#06b6d4",
        "accent": "#3b82f6",
        "spark_qty": "#06b6d4",
        "spark_rev": "#10b981",
        "spark_ord": "#3b82f6",
        "spark_bv": "#f59e0b",
        "colors": [
            "#10b981",
            "#06b6d4",
            "#3b82f6",
            "#8b5cf6",
            "#f59e0b",
            "#ec4899",
            "#14b8a6",
            "#6366f1",
        ],
    },
    "🌌 Neon Indigo": {
        "scale": "Viridis",
        "primary": "#6366f1",
        "secondary": "#a855f7",
        "accent": "#ec4899",
        "spark_qty": "#3b82f6",
        "spark_rev": "#6366f1",
        "spark_ord": "#a855f7",
        "spark_bv": "#ec4899",
        "colors": [
            "#6366f1",
            "#a855f7",
            "#ec4899",
            "#0284c7",
            "#10b981",
            "#f59e0b",
            "#8b5cf6",
            "#06b6d4",
        ],
    },
    "🌅 Sunset Ember": {
        "scale": "Magma",
        "primary": "#f43f5e",
        "secondary": "#fb923c",
        "accent": "#facc15",
        "spark_qty": "#fb923c",
        "spark_rev": "#f43f5e",
        "spark_ord": "#818cf8",
        "spark_bv": "#facc15",
        "colors": [
            "#f43f5e",
            "#fb923c",
            "#facc15",
            "#818cf8",
            "#2dd4bf",
            "#e11d48",
            "#f59e0b",
            "#a855f7",
        ],
    },
    "🫐 Midnight Sapphire": {
        "scale": "Blues",
        "primary": "#2563eb",
        "secondary": "#0284c7",
        "accent": "#0d9488",
        "spark_qty": "#0284c7",
        "spark_rev": "#2563eb",
        "spark_ord": "#0d9488",
        "spark_bv": "#f59e0b",
        "colors": [
            "#2563eb",
            "#0284c7",
            "#0d9488",
            "#64748b",
            "#f59e0b",
            "#3b82f6",
            "#06b6d4",
            "#475569",
        ],
    },
    "⚡ Solar Flare": {
        "scale": "YlOrRd",
        "primary": "#eab308",
        "secondary": "#f97316",
        "accent": "#ef4444",
        "spark_qty": "#f97316",
        "spark_rev": "#eab308",
        "spark_ord": "#ef4444",
        "spark_bv": "#84cc16",
        "colors": [
            "#eab308",
            "#f97316",
            "#ef4444",
            "#84cc16",
            "#3b82f6",
            "#a855f7",
            "#ec4899",
            "#06b6d4",
        ],
    },
    "🍃 Forest Jade": {
        "scale": "Greens",
        "primary": "#059669",
        "secondary": "#10b981",
        "accent": "#84cc16",
        "spark_qty": "#10b981",
        "spark_rev": "#059669",
        "spark_ord": "#84cc16",
        "spark_bv": "#06b6d4",
        "colors": [
            "#059669",
            "#10b981",
            "#84cc16",
            "#06b6d4",
            "#3b82f6",
            "#f59e0b",
            "#14b8a6",
            "#64748b",
        ],
    },
    "🌸 Cherry Blossom": {
        "scale": "RdPu",
        "primary": "#ec4899",
        "secondary": "#f472b6",
        "accent": "#c084fc",
        "spark_qty": "#f472b6",
        "spark_rev": "#ec4899",
        "spark_ord": "#c084fc",
        "spark_bv": "#fb923c",
        "colors": [
            "#ec4899",
            "#f472b6",
            "#c084fc",
            "#fb923c",
            "#38bdf8",
            "#a7f3d0",
            "#818cf8",
            "#f43f5e",
        ],
    },
    "🏛️ Obsidian Gold": {
        "scale": "Cividis",
        "primary": "#d97706",
        "secondary": "#b45309",
        "accent": "#f59e0b",
        "spark_qty": "#b45309",
        "spark_rev": "#d97706",
        "spark_ord": "#f59e0b",
        "spark_bv": "#64748b",
        "colors": [
            "#d97706",
            "#b45309",
            "#f59e0b",
            "#64748b",
            "#334155",
            "#0284c7",
            "#10b981",
            "#8b5cf6",
        ],
    },
}
