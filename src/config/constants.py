import os

# Project root — resolved once from src/config/ -> src/ -> project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# Data directories
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FEEDBACK_DIR = os.path.join(DATA_DIR, "feedback")
INCOMING_DIR = os.path.join(DATA_DIR, "incoming")
RESOURCES_DIR = os.path.join(PROJECT_ROOT, "resources")

# Snapshot file paths
STOCK_SNAPSHOT_PATH = os.path.join(RESOURCES_DIR, "last_stock.csv")
SALES_SNAPSHOT_PATH = os.path.join(RESOURCES_DIR, "sales_snapshot.csv")
METRIC_SNAPSHOT_DIR = os.path.join(RESOURCES_DIR, "metric_snapshots")

# Unified Shipped Statuses
SHIPPED_STATUSES = ["shipped", "completed", "confirmed"]

# Promotional offer keywords — items containing these are NOT actual stock
OFFER_KEYWORDS = ["combo", "bundle", "buy any"]

# Error log path
ERROR_LOG_FILE = os.path.join(DATA_DIR, "error_logs.json")

# Persistence
STATE_FILE = os.path.join(DATA_DIR, "session_state.json")

# Unified Category Master List (Preserves Hierarchical Order)
# Use ↳ (\u21b3) for sub-categories. 
COMMON_CATS = [
    "Jeans",
    "  \u21b3 Regular Fit Jeans",
    "  \u21b3 Slim Fit Jeans",
    "  \u21b3 Straight Fit Jeans",
    "T-Shirt",
    "  \u21b3 HS T-Shirt",
    "  \u21b3 FS-T-Shirt",
    "  \u21b3 Active Wear T-Shirt",
    "  \u21b3 Jersy",
    "Drop Shoulder",
    "Tank Top",
    "  \u21b3 Tank Top",
    "FS Shirt",
    "  \u21b3 Denim Shirt",
    "  \u21b3 Flannel Shirt",
    "  \u21b3 Oxford Shirt",
    "  \u21b3 Kaftan Shirt",
    "  \u21b3 Casual Shirt - Full Sleeve",
    "  \u21b3 Formal Shirt",
    "HS Shirt",
    "  \u21b3 Contrast Shirt",
    "  \u21b3 Casual Shirt - Half Sleeve",
    "  \u21b3 Cuban Shirt",
    "Panjabi",
    "  \u21b3 Embroidered Cotton Panjabi",
    "  \u21b3 Panjabi",
    "Sweatshirt",
    "  \u21b3 Cotton Terry Sweatshirt",
    "  \u21b3 French Terry Sweatshirt",
    "  \u21b3 Sweatshirt",
    "Polo Shirt",
    "Turtle-Neck",
    "Twill",
    "  \u21b3 Twill Pant",
    "  \u21b3 Twill Joggers",
    "  \u21b3 Twill Five Pockets",
    "Trousers",
    "  \u21b3 Regular Fit Trousers",
    "  \u21b3 Joggers",
    "Wallet",
    "  \u21b3 Bifold Wallet",
    "  \u21b3 Card Holder",
    "  \u21b3 Long Wallet",
    "  \u21b3 Passport Holder",
    "  \u21b3 Trifold Wallet",
    "  \u21b3 Wallet",
    "Boxer",
    "Leather Bag",
    "  \u21b3 Leather Bag",
    "Belt",
    "Mask",
    "Water Bottle",
    "Bundles",
    "Others"
]

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FEEDBACK_DIR, exist_ok=True)
os.makedirs(INCOMING_DIR, exist_ok=True)
os.makedirs(RESOURCES_DIR, exist_ok=True)
os.makedirs(METRIC_SNAPSHOT_DIR, exist_ok=True)
