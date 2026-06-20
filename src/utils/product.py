
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

