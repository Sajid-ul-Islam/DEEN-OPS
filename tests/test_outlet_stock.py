import unittest
from unittest.mock import patch, MagicMock

from src.services.woocommerce.outlet_stock import (
    fetch_outlet_stock_from_custom_endpoint,
    _KNOWN_CUSTOM_ENDPOINTS,
)


class TestOutletStock(unittest.TestCase):
    def test_known_endpoints_prioritizes_sip(self):
        self.assertIn("/wp-json/wc/v3/sip/outlet-stock", _KNOWN_CUSTOM_ENDPOINTS)
        self.assertEqual(_KNOWN_CUSTOM_ENDPOINTS[0], "/wp-json/wc/v3/sip/outlet-stock")

    @patch("src.services.woocommerce.outlet_stock._get_auth_and_url")
    @patch("src.services.woocommerce.outlet_stock.request_with_backoff")
    def test_fetch_outlet_stock_pivots_tabular_rows(self, mock_request, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://deencommerce.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps([
            {"product": "Polo A", "size": "M", "sku": "101-M", "outlet": "Mirpur", "stock_qty": 5},
            {"product": "Polo A", "size": "M", "sku": "101-M", "outlet": "Wari", "stock_qty": 2},
            {"product": "Polo A", "size": "L", "sku": "101-L", "outlet": "Mirpur", "stock_qty": 3},
            {"product": "Polo A", "size": "L", "sku": "101-L", "outlet": "Warehouse", "stock_qty": 10},
        ])
        mock_request.return_value = mock_response

        df = fetch_outlet_stock_from_custom_endpoint("https://deencommerce.com/wp-json/wc/v3/sip/outlet-stock")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)
        self.assertIn("Mirpur", df.columns)
        self.assertIn("Wari", df.columns)
        self.assertIn("Warehouse", df.columns)

        # Check Polo A - M
        m_row = df[(df["SKU"] == "101-M")].iloc[0]
        self.assertEqual(m_row["Mirpur"], 5)
        self.assertEqual(m_row["Wari"], 2)
        self.assertEqual(m_row["Warehouse"], 0)

    @patch("src.services.woocommerce.outlet_stock._get_auth_and_url")
    @patch("src.services.woocommerce.outlet_stock.request_with_backoff")
    def test_fetch_outlet_stock_already_pivoted(self, mock_request, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://deencommerce.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps([
            {"SKU": "101-M", "Product": "Polo A - M", "Mirpur": 5, "Wari": 2}
        ])
        mock_request.return_value = mock_response

        df = fetch_outlet_stock_from_custom_endpoint("https://deencommerce.com/wp-json/wc/v3/sip/outlet-stock")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["Mirpur"], 5)


if __name__ == "__main__":
    unittest.main()
