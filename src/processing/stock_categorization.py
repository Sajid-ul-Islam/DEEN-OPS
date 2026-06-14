"""
Shared stock categorization logic for the Outlet Stock Compiler.

This module provides map_to_csv_category(), which maps product names to display
categories used in the outlet stock summary reports. It is used by both
stock_analytics.py and inventory_distribution.py.
"""
from functools import lru_cache


_MAPPING_RULES = {
    'active wear': 'Active Wear T-Shirt',
    'drop shoulder': 'Drop Shoulder',
    'oversized': 'Drop Shoulder',
    'tank top': 'Tank Top',
    'turtle': 'Turtelneck',
    'polo': 'Polo Shirt',
    'cuban': 'Cuban Shirt',
    'denim': 'Denim Shirt',
    'flannel': 'Flannel Shirt',
    'oxford': 'Formal Shirt',
    'kaftan': 'Kaftan Shirt',
    'contrast': 'Contrast Shirt',
    'jeans': 'Jeans Pant',
    'chino': 'Twill Pant',
    'twill': 'Twill Pant',
    'trouser': 'Trouser',
    'jogger': 'Trouser',
    'panjabi': 'Panjabi',
    'punjabi': 'Panjabi',
    'sweatshirt': 'Sweatshirt',
    'hoodie': 'Sweatshirt',
    'boxer': 'Boxers',
    'belt': 'Belt',
    'wallet': 'Wallet',
    'card holder': 'Card Holder',
    'passport': 'Passport Holder',
    'bag': 'Leather Bag',
    'backpack': 'Leather Bag',
    'mask': 'Mask',
    'bottle': 'Water Bottle',
    'formal': 'Formal Shirt',
    'executive': 'Formal Shirt',
}

_TSHIRT_KEYWORDS = ['t-shirt', 't shirt', 'tee']
_FULL_SLEEVE_KEYWORDS = ['full', 'fs', 'l/s', 'long', 'ls']
_HALF_SLEEVE_SHIRT_KEYWORDS = ['half', 'hs', 'short sleeve', 'short-sleeve', 'shortsleeve']


@lru_cache(maxsize=4096)
def map_to_csv_category(product_name: str) -> str:
    """
    Map a product name string to a display category for the outlet stock report.

    Priority order:
    1. Keyword-rule dict (drop shoulder, denim, etc.)
    2. T-Shirt (half/full sleeve)
    3. Shirt (half/full sleeve)
    4. Others (fallback)
    """
    name_lower = str(product_name).lower()

    for keyword, category in _MAPPING_RULES.items():
        if keyword in name_lower:
            return category

    is_tshirt = any(kw in name_lower for kw in _TSHIRT_KEYWORDS)
    if is_tshirt:
        if any(kw in name_lower for kw in _FULL_SLEEVE_KEYWORDS):
            return 'T-Shirt - Full Sleeve'
        return 'T-shirt - Half Sleeve'

    if 'shirt' in name_lower:
        if any(kw in name_lower for kw in _HALF_SLEEVE_SHIRT_KEYWORDS):
            return 'Casual Shirt - Half Sleeve'
        return 'Casual Shirt - Full Sleeve'

    return 'Others'
