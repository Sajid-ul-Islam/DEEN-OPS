import re
import pandas as pd

def _normalize(name):
    """Normalizes names for matching."""
    if not name: return ""
    return str(name).lower().strip()

def _has_any(keywords, text):
    """Checks if any keyword is in the text."""
    return any(kw in text for kw in keywords)

def get_category_for_sales(name) -> str:
    """Categorizes products based on keywords in their names (Unified v16.0 Rules)."""
    name_str = _normalize(name)
    if not name_str: return "Others"

    # 1. HIGH PRIORITY SPECIAL CATEGORIES
    if _has_any(["sweatshirt", "hoodie", "pullover"], name_str): return "Sweatshirt"
    if "polo" in name_str: return "Polo Shirt"
    if _has_any(["turtleneck", "turtle-neck", "mock neck"], name_str): return "Turtle-Neck"
    if "bundle" in name_str: return "Bundles"

    # 2. MAIN CLUSTERS
    if _has_any(["jeans"], name_str): return "Jeans"
    
    if _has_any(["t-shirt", "t shirt", "tee"], name_str):
        return "T-Shirt"

    fs_keywords = ["full sleeve", "long sleeve", "fs", "l/s", "fullsleeve", "full-sleeve"]
    is_shirt = _has_any(["shirt"], name_str)
    
    if is_shirt:
        if _has_any(fs_keywords, name_str) or _has_any(["denim", "flannel", "oxford", "kaftan"], name_str):
            return "FS Shirt"
        return "HS Shirt"

    specific_cats = {
        "Boxer": ["boxer"],
        "Panjabi": ["panjabi", "punjabi"],
        "Twill": ["twill", "chino"],
        "Trousers": ["trousers", "trouser", "jogger", "pants", "gabardine"],
        "Mask": ["mask"],
        "Leather Bag": ["bag", "backpack", "tote"],
        "Water Bottle": ["water bottle", "bottle"],
        "Wallet": ["wallet", "card holder", "passport holder"],
        "Belt": ["belt"],
        "Jacket": ["jacket", "outerwear", "coat"],
        "Sweater": ["sweater", "cardigan", "knitwear"],
        "Cap": ["cap"],
    }

    for cat, keywords in specific_cats.items():
        if _has_any(keywords, name_str):
            return cat

    return "Others"

def get_sub_category_for_sales(name, category) -> str:
    """Extracts sub-category based on Unified v16.0 Hierarchical Rules."""
    name_str = _normalize(name)
    if not name_str: return category

    if category == "Jeans":
        if "regular" in name_str: return "Regular Fit Jeans"
        if "slim" in name_str: return "Slim Fit Jeans"
        if "straight" in name_str: return "Straight Fit Jeans"

    elif category == "T-Shirt":
        if "drop shoulder" in name_str: return "Drop Shoulder"
        if _has_any(["tank top"], name_str): return "Tank Top"
        if _has_any(["active wear", "activewear"], name_str): return "Active Wear"
        if _has_any(["jersy", "jersey"], name_str): return "Jersy"
        if _has_any(["full sleeve", "long sleeve", "fs"], name_str): return "FS-T-Shirt"
        return "HS T-Shirt"

    elif category == "FS Shirt":
        if "flannel" in name_str: return "Flannel Shirt"
        if "denim" in name_str: return "Denim Shirt"
        if "oxford" in name_str: return "Oxford Shirt"
        if "kaftan" in name_str: return "Kaftan Shirt"
        if "casual" in name_str: return "FS Casual Shirt"
        return "FS Shirt"

    elif category == "HS Shirt":
        if "contrast" in name_str: return "Contrast Shirt"
        if "casual" in name_str: return "HS Casual Shirt"
        return "HS Shirt"

    elif category == "Wallet":
        if "passport" in name_str: return "Passport Holder"
        if "card holder" in name_str: return "Card Holder"
        if "long" in name_str: return "Long Wallet"
        if "bifold" in name_str: return "Bifold Wallet"
        if "trifold" in name_str: return "Trifold Wallet"
        return "Wallet"

    elif category == "Panjabi":
        if _has_any(["embroidered cotton"], name_str): return "Embroidered Cotton Panjabi"
        return "Panjabi"

    elif category == "Sweatshirt":
        if "cotton terry" in name_str: return "Cotton Terry Sweatshirt"
        if "french terry" in name_str: return "French Terry Sweatshirt"
        return "Sweatshirt"

    elif category == "Twill":
        if "joggers" in name_str: return "Twill Joggers"
        if _has_any(["five pocket", "5 pocket", "5-pocket"], name_str): return "Twill Five Pockets"
        return "Twill Chino"

    elif category == "Trousers":
        if "joggers" in name_str: return "Joggers"
        if "regular fit" in name_str: return "Regular Fit Trousers"
        return "Trousers"

    return category
