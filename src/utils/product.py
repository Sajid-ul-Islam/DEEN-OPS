
def get_base_product_name(name: str) -> str:
    """Removes the size portion (e.g. ' - XL') from a product name for cleaner filter grouping."""
    if not name or " - " not in name:
        return name
    return str(name).rsplit(" - ", 1)[0]


def get_size_from_name(name: str) -> str:
    """Extracts the size attribute from a product name string."""
    if not name or " - " not in name:
        return "N/A"
    return str(name).rsplit(" - ", 1)[1]


def is_bundle_or_combo(name: str = "", sku: str = "", category: str = "") -> bool:
    """Checks if a product, SKU, or category represents a bundle or combo offer."""
    from src.config.constants import OFFER_KEYWORDS
    if category and str(category).strip().lower() in ["bundles", "bundle", "combo"]:
        return True
    s_name = str(name).lower() if name else ""
    s_sku = str(sku).lower() if sku else ""
    for kw in OFFER_KEYWORDS:
        if kw in s_name or kw in s_sku:
            return True
    return False


