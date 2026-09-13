import io
import unittest
import pandas as pd

from src.inventory import core as inv_core


SAMPLE_UNIFIED_CSV = """Product,Size,SKU,Outlet,"Stock Qty",Price,"Last Updated"
"DEEN High-End Light Blue Jeans – Regular Fit","Size: 36",101-0200-150,Warehouse,0,0.00,"2026-09-13 08:29:32"
"Springfield Polo Shirt","Size: 2XL",103-0100-114,Cumilla,3,0.00,"2026-09-13 08:22:35"
"Springfield Polo Shirt","Size: 2XL",103-0100-115,Warehouse,1,0.00,"2026-09-13 08:22:35"
"Springfield Polo Shirt","Size: 2XL",103-0100-119,Warehouse,8,0.00,"2026-09-13 08:22:35"
"Springfield Polo Shirt","Size: 2XL",103-0100-119,Cumilla,4,0.00,"2026-09-13 08:22:35"
"DEEN High-End Raw Washed Jeans - Slim Fit","Size: 30",101-0100-149,"Mirpur 12",1,0.00,"2026-09-13 07:25:29"
"DEEN High-End Raw Washed Jeans - Slim Fit","Size: 30",101-0100-149,Warehouse,0,0.00,"2026-09-13 06:01:21"
"DEEN Essential White T-shirt","Size: 3XL",105-0101-379,Wari,1,0.00,"2026-09-13 05:44:54"
"DEEN White Beige Embroidered Panjabi","Size: 42",106-0101-135,Sylhet,1,0.00,"2026-09-13 04:40:13"
"DEEN Compact Genuine Leather Card Holder",,109-0104-002,Warehouse,1,0.00,"2026-09-13 06:13:35"
"DEEN Non-Existent Item","Size: M",999-9999-999,Warehouse,0,0.00,"2026-09-13 06:00:00"
"""


class TestUnifiedStockMatching(unittest.TestCase):
    def test_normalize_size_cleans_prefixes(self):
        self.assertEqual(inv_core.normalize_size("Size: 36"), "36")
        self.assertEqual(inv_core.normalize_size("Size: 2XL"), "2XL")
        self.assertEqual(inv_core.normalize_size("Size: L"), "L")
        self.assertEqual(inv_core.normalize_size("size-M"), "M")
        self.assertEqual(inv_core.normalize_size("Sz: 32"), "32")
        self.assertEqual(inv_core.normalize_size("34"), "34")
        self.assertEqual(inv_core.normalize_size(""), "NO_SIZE")
        self.assertEqual(inv_core.normalize_size(None), "NO_SIZE")

    def test_is_unified_stock_file_detection(self):
        df_unified = pd.read_csv(io.StringIO(SAMPLE_UNIFIED_CSV))
        self.assertTrue(inv_core.is_unified_stock_file(df_unified))

        df_orders = pd.DataFrame({
            "Order Number": ["1001"],
            "Item Name": ["Shirt"],
            "Quantity": [1],
            "Phone": ["01711111111"],
        })
        self.assertFalse(inv_core.is_unified_stock_file(df_orders))

    def test_load_inventory_from_unified_stock_file(self):
        inv_map, warnings, enriched_dfs, sku_map, pivoted_df = (
            inv_core.load_inventory_from_unified_stock_file(io.StringIO(SAMPLE_UNIFIED_CSV))
        )
        self.assertFalse(warnings)
        self.assertFalse(pivoted_df.empty)

        # Check pivoted table columns
        self.assertIn("Warehouse", pivoted_df.columns)
        self.assertIn("Cumilla", pivoted_df.columns)
        self.assertIn("Mirpur 12", pivoted_df.columns)
        self.assertIn("Wari", pivoted_df.columns)
        self.assertIn("Sylhet", pivoted_df.columns)
        self.assertIn("Total Stock", pivoted_df.columns)

        # Springfield Polo Shirt - 2XL has 8 in Warehouse and 4 in Cumilla
        sku_sz_key = "SKU:1030100119_SZ:2XL"
        self.assertIn(sku_sz_key, inv_map)
        self.assertEqual(inv_map[sku_sz_key]["Warehouse"], 8)
        self.assertEqual(inv_map[sku_sz_key]["Cumilla"], 4)

    def test_order_to_stock_matching_allocates_correct_outlet(self):
        inv_map, _, _, sku_map, _ = (
            inv_core.load_inventory_from_unified_stock_file(io.StringIO(SAMPLE_UNIFIED_CSV))
        )

        orders_df = pd.DataFrame([
            {
                "Order Number": "ORD-1",
                "Item Name": "Springfield Polo Shirt - 2XL",
                "SKU": "103-0100-119",
                "Quantity": 1,
            },
            {
                "Order Number": "ORD-2",
                "Item Name": "DEEN High-End Raw Washed Jeans - Slim Fit - 30",
                "SKU": "101-0100-149",
                "Quantity": 1,
            },
            {
                "Order Number": "ORD-3",
                "Item Name": "DEEN Non-Existent Item - M",
                "SKU": "999-9999-999",
                "Quantity": 1,
            },
        ])

        target_locations = ["Warehouse", "Mirpur 12", "Wari", "Cumilla", "Sylhet"]
        result_df, matched_count = inv_core.add_stock_columns_from_inventory(
            orders_df,
            item_name_col="Item Name",
            inventory=inv_map,
            locations=target_locations,
            sku_col="SKU",
            sku_to_title_size=sku_map,
            priority_locations=["Warehouse", "Mirpur 12", "Wari", "Cumilla", "Sylhet"],
        )

        self.assertEqual(matched_count, 3)

        # ORD-1: Stock is in Warehouse (8) and Cumilla (4) -> allocated to Warehouse
        ord1 = result_df[result_df["Order Number"].str.startswith("ORD-1")].iloc[0]
        self.assertEqual(ord1["Warehouse"], 8)
        self.assertEqual(ord1["Cumilla"], 4)
        self.assertEqual(ord1["Dispatch Suggestion"], "Warehouse")

        # ORD-2: Stock is in Mirpur 12 (1) (Warehouse has 0) -> allocated to Mirpur 12
        ord2 = result_df[result_df["Order Number"].str.startswith("ORD-2")].iloc[0]
        self.assertEqual(ord2["Warehouse"], 0)
        self.assertEqual(ord2["Mirpur 12"], 1)
        self.assertEqual(ord2["Dispatch Suggestion"], "Mirpur 12")

        # ORD-3: 0 stock in all locations -> OOS / Unfulfillable
        ord3 = result_df[result_df["Order Number"].str.startswith("ORD-3")].iloc[0]
        self.assertEqual(ord3["Dispatch Suggestion"], "OOS / Unfulfillable")


if __name__ == "__main__":
    unittest.main()
