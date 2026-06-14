import pytest
from src.processing.categorization import get_category_for_sales, get_sub_category_for_sales


class TestGetCategoryForSales:
    def test_sweatshirt(self):
        assert get_category_for_sales("Cotton Terry Sweatshirt - XL") == "Sweatshirt"
        assert get_category_for_sales("Hoodie Black") == "Sweatshirt"
        assert get_category_for_sales("Pullover Navy") == "Sweatshirt"

    def test_polo(self):
        assert get_category_for_sales("Polo Shirt Blue - M") == "Polo Shirt"

    def test_turtleneck(self):
        assert get_category_for_sales("Turtleneck Sweater") == "Turtle-Neck"
        assert get_category_for_sales("Mock Neck Top") == "Turtle-Neck"

    def test_bundle(self):
        assert get_category_for_sales("Bundle Pack Jeans + Shirt") == "Bundles"

    def test_tshirt_redirects(self):
        assert get_category_for_sales("Active Wear Tee") == "T-Shirt"
        assert get_category_for_sales("Jersey Sport") == "T-Shirt"

    def test_drop_shoulder(self):
        assert get_category_for_sales("Drop Shoulder Tee - M") == "Drop Shoulder"
        assert get_category_for_sales("Urban Stripe Drop Shoulder T-Shirt - 3XL") == "Drop Shoulder"

    def test_tank_top(self):
        assert get_category_for_sales("Tank Top White") == "Tank Top"

    def test_tshirt(self):
        assert get_category_for_sales("Premium T-Shirt - L") == "T-Shirt"

    def test_shirts(self):
        assert get_category_for_sales("Full Sleeve Shirt Blue") == "FS Shirt"
        assert get_category_for_sales("Casual Shirt - M") == "HS Shirt"

    def test_jeans(self):
        assert get_category_for_sales("Slim Fit Jeans Black") == "Jeans"

    def test_specific_categories(self):
        assert get_category_for_sales("Classic Boxer - L") == "Boxer"
        assert get_category_for_sales("Twill Chino Pant") == "Twill Chino"
        assert get_category_for_sales("Leather Belt Brown") == "Belt"
        assert get_category_for_sales("Bifold Wallet") == "Wallet"

    def test_empty_and_none(self):
        assert get_category_for_sales("") == "Others"
        assert get_category_for_sales(None) == "Others"

    def test_unknown(self):
        assert get_category_for_sales("Random Gadget XYZ") == "Others"


class TestGetSubCategoryForSales:
    def test_jeans_subcategories(self):
        assert get_sub_category_for_sales("Regular Fit Jeans", "Jeans") == "Regular Fit Jeans"
        assert get_sub_category_for_sales("Slim Fit Jeans", "Jeans") == "Slim Fit Jeans"

    def test_tshirt_subcategories(self):
        # Drop Shoulder and Tank Top are routed as top-level categories before reaching T-Shirt
        # so sub-category only needs to handle actual T-Shirt variants
        assert get_sub_category_for_sales("Basic T-Shirt", "T-Shirt") == "HS T-Shirt"
        assert get_sub_category_for_sales("FS T-Shirt Black", "T-Shirt") == "FS-T-Shirt"
        assert get_sub_category_for_sales("Active Wear T-Shirt", "T-Shirt") == "Active Wear"
        assert get_sub_category_for_sales("Jersey Tee", "T-Shirt") == "Jersy"

    def test_fs_shirt_subcategories(self):
        assert get_sub_category_for_sales("Flannel Shirt Red", "FS Shirt") == "Flannel Shirt"
        assert get_sub_category_for_sales("Oxford Shirt Blue", "FS Shirt") == "Oxford Shirt"

    def test_wallet_subcategories(self):
        assert get_sub_category_for_sales("Passport Holder Leather", "Wallet") == "Passport Holder"
        assert get_sub_category_for_sales("Bifold Wallet Brown", "Wallet") == "Bifold Wallet"

    def test_fallback_to_category(self):
        assert get_sub_category_for_sales("Unknown Item", "Belt") == "Belt"
