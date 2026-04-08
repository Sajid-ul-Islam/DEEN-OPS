import re
import functools


# Pre-compiled Operational Patterns for Shared Utils
UTILS_CAT_RULES = {
    "Boxer": ["boxer"],
    "Jeans": ["jeans"],
    "Denim": ["denim"],
    "Flannel": ["flannel"],
    "Polo": ["polo"],
    "Panjabi": ["panjabi"],
    "Trousers": ["trouser"],
    "Twill": ["twill", "chino"],
    "Sweatshirt": ["sweatshirt"],
    "Tank Top": ["tank top"],
    "Drop Shoulder": ["drop shoulder"],
    "Pants": ["gabardine", "pant"],
    "Contrast": ["contrast"],
    "Turtleneck": ["turtleneck"],
    "Wallet": ["wallet"],
    "Kaftan": ["kaftan"],
    "Active": ["Active"],
    "1 Pack Mask": ["mask"],
    "Bag": ["Bag"],
    "Bottle": ["bottle"],
}

# Pre-compile for bulk speed
UTILS_PATTERNS = {
    cat: [re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE) for kw in keywords]
    for cat, keywords in UTILS_CAT_RULES.items()
}
UTILS_FS_KW = re.compile(rf"\b{re.escape('full sleeve')}\b", re.IGNORECASE)
UTILS_TSHIRT_KW = re.compile(rf"\b(t-shirt|t shirt)\b", re.IGNORECASE)
UTILS_SHIRT_KW = re.compile(rf"\bshirt\b", re.IGNORECASE)

@functools.lru_cache(maxsize=1024)
def get_category_from_name(name):
    """Determines the category of an item based on its name using optimized matching."""
    if not name: return "Items"
    name_str = str(name).lower()

    # 1. Match Specific Categories
    for cat, patterns in UTILS_PATTERNS.items():
        if any(p.search(name_str) for p in patterns):
            return cat

    # 2. Logic-based Categories (Shirts/T-Shirts)
    is_fs = bool(UTILS_FS_KW.search(name_str))
    
    if UTILS_TSHIRT_KW.search(name_str):
        return "FS T-Shirt" if is_fs else "T-Shirt"
    
    if UTILS_SHIRT_KW.search(name_str):
        return "FS Shirt" if is_fs else "HS Shirt"

    # 3. Fallback: Dynamic grouping
    words = name_str.split()
    if len(words) >= 2:
        return f"{words[0].title()} {words[1].title()}"
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


def peek_zone_from_address(address: str, current_city: str = "") -> str:
    """
    Scans the address string for common Thanas/Zones to avoid duplication.
    """
    if not address or str(address).lower() == "nan":
        return ""

    addr = str(address).lower()
    
    # Priority Zones (Common Pathao targets)
    zones = [
        "Mirpur", "Uttara", "Gulshan", "Banani", "Dhanmondi", "Mohammadpur",
        "Badda", "Rampura", "Khilgaon", "Jatrabari", "Demra", "Hazaribagh",
        "Kamrangirchar", "Kotwali", "Lalbagh", "Motijheel", "Paltan", "Ramna",
        "Sabujbagh", "Shahbagh", "Sher-E-Bangla Nagar", "Sutrapur", "Tejgaon",
        "Tejgaon Industrial Area", "Uttara West", "Uttara East", "Pallabi",
        "Kafrul", "Cantonment", "Basundhara", "Baridhara", "Nikunja", "Khilkhet",
        "Bashundhara R/A", "Mohakhali", "Malibagh", "Moghbazar", "Farmgate",
        "Savar", "Gazipur", "Narayanganj", "Keraniganj", "Tongi", "Ashulia",
        "Pahartali", "Halishahar", "Patenga", "Bakalia", "Panchlaish", "Bayezid",
        "Chandgaon", "Double Mooring", "Khulshi"
    ]
    
    for zone in zones:
        if re.search(rf"\b{re.escape(zone.lower())}\b", addr):
            return zone

    return ""
