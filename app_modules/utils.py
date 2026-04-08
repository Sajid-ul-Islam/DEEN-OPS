import re


# --- Category Logic ---
def get_category_from_name(name):
    """
    Determines the category of an item based on its name using keyword matching.
    """
    name_str = str(name)

    def has_keyword(sub, text):
        return bool(re.search(rf"\b{re.escape(sub.lower())}\b", text, re.IGNORECASE))

    # --- Category Rules ---
    # Specific items
    if has_keyword("boxer", name_str):
        return "Boxer"
    if has_keyword("jeans", name_str):
        return "Jeans"
    if has_keyword("denim", name_str):
        return "Denim"
    if has_keyword("flannel", name_str):
        return "Flannel"
    if has_keyword("polo", name_str):
        return "Polo"
    if has_keyword("panjabi", name_str):
        return "Panjabi"
    if has_keyword("trouser", name_str):
        return "Trousers"
    if has_keyword("twill", name_str) or has_keyword("chino", name_str):
        return "Twill"
    if has_keyword("sweatshirt", name_str):
        return "Sweatshirt"
    if has_keyword("tank top", name_str):
        return "Tank Top"
    if has_keyword("drop shoulder", name_str):
        return "Drop Shoulder"
    if has_keyword("gabardine", name_str) or has_keyword("pant", name_str):
        return "Pants"

    # Accessories & Misc
    if has_keyword("contrast", name_str):
        return "Contrast"
    if has_keyword("turtleneck", name_str):
        return "Turtleneck"
    if has_keyword("wallet", name_str):
        return "Wallet"
    if has_keyword("kaftan", name_str):
        return "Kaftan"
    if has_keyword("Active", name_str):
        return "Active"
    if has_keyword("mask", name_str):
        return "1 Pack Mask"
    if has_keyword("Bag", name_str):
        return "Bag"
    if has_keyword("bottle", name_str):
        return "Bottle"

    # Common Attributes
    is_full_sleeve = has_keyword("full sleeve", name_str)

    # T-Shirts
    is_tshirt = has_keyword("t-shirt", name_str) or has_keyword("t shirt", name_str)
    if is_full_sleeve and is_tshirt:
        return "FS T-Shirt"
    if is_tshirt and not is_full_sleeve:
        return "T-Shirt"

    # Shirts
    is_shirt = has_keyword("shirt", name_str)

    if is_full_sleeve and is_shirt:
        return "FS Shirt"
    if is_shirt and not is_full_sleeve:
        return "HS Shirt"

    # Fallback: Use first two words
    words = name_str.split()
    if len(words) >= 2:
        return f"{words[0]} {words[1]}"
    return "Items"


# --- Address Logic ---
def normalize_city_name(city_name):
    """
    Standardizes city/district names to match Pathao specific formats or correct spelling.
    """
    if not city_name:
        return ""

    c = city_name.strip()
    c_lower = c.lower()

    # ISO 3166-2:BD District Mappings (standard for WooCommerce BD)
    # ISO 3166-2:BD District Mappings (standard for WooCommerce BD)
    bd_states = {
        "BD-01": "Bandarban",
        "BD-02": "Barguna",
        "BD-03": "Bogura",           # Corrected from "Bogra"
        "BD-04": "Brahmanbaria",
        "BD-05": "Bagerhat",
        "BD-06": "Barishal",         # Corrected from "Barisal"
        "BD-07": "Bhola",
        "BD-08": "Cumilla",          # Updated official spelling
        "BD-09": "Chandpur",
        "BD-10": "Chattogram",       # Official name (was Chittagong)
        "BD-11": "Cox's Bazar",
        "BD-12": "Chuadanga",
        "BD-13": "Dhaka",
        "BD-14": "Dinajpur",
        "BD-15": "Faridpur",
        "BD-16": "Feni",
        "BD-17": "Gopalganj",
        "BD-18": "Gazipur",
        "BD-19": "Gaibandha",
        "BD-20": "Habiganj",
        "BD-21": "Jamalpur",
        "BD-22": "Jashore",          # Updated official spelling
        "BD-23": "Jhenaidah",
        "BD-24": "Joypurhat",
        "BD-25": "Jhalokathi",
        "BD-26": "Kishoreganj",
        "BD-27": "Khulna",
        "BD-28": "Kurigram",
        "BD-29": "Khagrachhari",
        "BD-30": "Kushtia",
        "BD-31": "Lakshmipur",
        "BD-32": "Lalmonirhat",
        "BD-33": "Manikganj",
        "BD-34": "Mymensingh",
        "BD-35": "Munshiganj",
        "BD-36": "Madaripur",
        "BD-37": "Magura",
        "BD-38": "Moulvibazar",
        "BD-39": "Meherpur",
        "BD-40": "Narayanganj",
        "BD-41": "Netrakona",
        "BD-42": "Narsingdi",
        "BD-43": "Narail",
        "BD-44": "Natore",
        "BD-45": "Chapai Nawabganj",  # Fixed: This is the official district name
        "BD-46": "Nilphamari",
        "BD-47": "Noakhali",
        "BD-48": "Naogaon",
        "BD-49": "Pabna",
        "BD-50": "Pirojpur",
        "BD-51": "Patuakhali",
        "BD-52": "Panchagarh",
        "BD-53": "Rajbari",
        "BD-54": "Rajshahi",
        "BD-55": "Rangpur",
        "BD-56": "Rangamati",
        "BD-57": "Sherpur",
        "BD-58": "Satkhira",
        "BD-59": "Sirajganj",
        "BD-60": "Sylhet",
        "BD-61": "Sunamganj",
        "BD-62": "Shariatpur",
        "BD-63": "Tangail",
        "BD-64": "Thakurgaon"
    }

    c_upper = c.upper()
    if c_upper in bd_states:
        return bd_states[c_upper]
    
    # Generic prefix match (e.g. BD13)
    c_clean = c_upper.replace("-", "").strip()
    if c_clean.startswith("BD") and c_clean in [k.replace("-", "") for k in bd_states]:
        # Map cleaned code to state
        for k, v in bd_states.items():
            if k.replace("-", "") == c_clean:
                return v

    # User requested mappings
    if "brahmanbaria" in c_lower:
        return "B. Baria"
    if "narsingdi" in c_lower or "narsinghdi" in c_lower:
        return "Narshingdi"
    if "bagura" in c_lower or "bogura" in c_lower:
        return "Bogra"

    # Other common corrections
    if "chattogram" in c_lower:
        return "Chittagong"
    if "cox" in c_lower and "bazar" in c_lower:
        return "Cox's Bazar"
    if "chapainawabganj" in c_lower:
        return "Chapainawabganj"

    # Default: Title Case
    return c.title()
