"""
Unit tests for src/processing/stock_categorization.py — the shared outlet stock
category mapping function.
"""
import pytest
from src.processing.stock_categorization import map_to_csv_category


class TestMapToCsvCategory:
    """Tests for map_to_csv_category."""

    # ── T-Shirts ─────────────────────────────────────────────────────────────
    def test_tshirt_half_sleeve_plain(self):
        assert map_to_csv_category("Basic T-Shirt") == "T-shirt - Half Sleeve"

    def test_tshirt_half_sleeve_tshirt_keyword(self):
        assert map_to_csv_category("Deen T Shirt White") == "T-shirt - Half Sleeve"

    def test_tshirt_full_sleeve(self):
        assert map_to_csv_category("Deen T-Shirt Full Sleeve Navy") == "T-Shirt - Full Sleeve"

    def test_tshirt_full_sleeve_fs(self):
        assert map_to_csv_category("FS T-Shirt Black") == "T-Shirt - Full Sleeve"

    # ── Drop Shoulder / Tank Top (NOT T-Shirt) ───────────────────────────────
    def test_drop_shoulder_is_not_tshirt(self):
        result = map_to_csv_category("Drop Shoulder T-Shirt Oversized")
        assert result == "Drop Shoulder"

    def test_tank_top_is_not_tshirt(self):
        result = map_to_csv_category("Tank Top White")
        assert result == "Tank Top"

    def test_oversized_maps_to_drop_shoulder(self):
        assert map_to_csv_category("Oversized Tee Beige") == "Drop Shoulder"

    # ── Shirts ───────────────────────────────────────────────────────────────
    def test_casual_shirt_half_sleeve(self):
        assert map_to_csv_category("Casual Shirt Half Sleeve") == "Casual Shirt - Half Sleeve"

    def test_casual_shirt_hs_abbrev(self):
        assert map_to_csv_category("HS Casual Shirt Blue") == "Casual Shirt - Half Sleeve"

    def test_casual_shirt_full_sleeve_default(self):
        assert map_to_csv_category("Deen Premium Shirt") == "Casual Shirt - Full Sleeve"

    def test_denim_shirt(self):
        assert map_to_csv_category("Denim Shirt Dark Blue") == "Denim Shirt"

    def test_flannel_shirt(self):
        assert map_to_csv_category("Flannel Shirt Red Check") == "Flannel Shirt"

    def test_formal_shirt(self):
        assert map_to_csv_category("Executive Formal Shirt White") == "Formal Shirt"

    # ── Bottoms ──────────────────────────────────────────────────────────────
    def test_jeans(self):
        assert map_to_csv_category("Slim Fit Jeans Black") == "Jeans Pant"

    def test_trouser(self):
        assert map_to_csv_category("Casual Trouser Grey") == "Trouser"

    def test_jogger(self):
        assert map_to_csv_category("Jogger Pants Olive") == "Trouser"

    def test_chino(self):
        assert map_to_csv_category("Twill Chino Beige") == "Twill Pant"

    # ── Panjabi / Sweatshirt ─────────────────────────────────────────────────
    def test_panjabi(self):
        assert map_to_csv_category("Cotton Panjabi White") == "Panjabi"

    def test_punjabi_alternate_spelling(self):
        assert map_to_csv_category("Embroidered Punjabi Cream") == "Panjabi"

    def test_sweatshirt(self):
        assert map_to_csv_category("French Terry Sweatshirt Grey") == "Sweatshirt"

    def test_hoodie(self):
        assert map_to_csv_category("Pullover Hoodie Black") == "Sweatshirt"

    # ── Accessories ──────────────────────────────────────────────────────────
    def test_wallet(self):
        assert map_to_csv_category("Bifold Leather Wallet Brown") == "Wallet"

    def test_belt(self):
        assert map_to_csv_category("Genuine Leather Belt Black") == "Belt"

    def test_bag(self):
        assert map_to_csv_category("Canvas Bag Grey") == "Leather Bag"

    # ── Fallback ─────────────────────────────────────────────────────────────
    def test_unknown_falls_back_to_others(self):
        assert map_to_csv_category("Random Product XYZ") == "Others"

    def test_empty_string_falls_back_to_others(self):
        assert map_to_csv_category("") == "Others"

    def test_case_insensitive(self):
        assert map_to_csv_category("DROP SHOULDER T-SHIRT") == "Drop Shoulder"
        assert map_to_csv_category("drop shoulder t-shirt") == "Drop Shoulder"
