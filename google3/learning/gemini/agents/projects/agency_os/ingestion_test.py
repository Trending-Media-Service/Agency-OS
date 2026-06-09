import hashlib
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import ingestion

class IngestionTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.tenant_id = "test-tenant-123"
        self.adapter = ingestion.OmnichannelIngestionAdapter(
            tenant_id=self.tenant_id
        )

    def test_shopify_normalization(self):
        # Mock Shopify payload
        shopify_payload = {
            "id": 450789498,
            "total_tax": "10.00",
            "total_price": "115.00",
            "total_discounts": "5.00",
            "subtotal_price": "100.00",
            "shipping_lines": [
                {"price": "5.00", "title": "Standard Shipping"}
            ],
            "refunds": [],
            "line_items": [
                {
                    "sku": "SWG-COZY-01",
                    "quantity": 1,
                    "price": "100.00"
                }
            ],
            "customer": {
                "email": "customer@example.com",
                "phone": "+1234567890"
            },
            "created_at": "2026-06-08T20:00:00Z"
        }

        normalized = self.adapter.normalize_shopify(shopify_payload)

        self.assertEqual(normalized.order_id, "450789498")
        self.assertEqual(normalized.tenant_id, self.tenant_id)
        # Gross revenue before discount, net of tax
        # Shopify subtotal_price (100.0) + total_discounts (5.0) = 105.0
        self.assertEqual(normalized.gross_revenue, 105.0)
        self.assertEqual(normalized.discounts, 5.0)
        self.assertEqual(normalized.shipping, 5.0)
        self.assertEqual(normalized.tax, 10.0)
        self.assertEqual(normalized.refunds, 0.0)
        self.assertLen(normalized.line_items, 1)
        self.assertEqual(normalized.line_items[0].sku, "SWG-COZY-01")
        expected_email = hashlib.sha256(b"customer@example.comdefault_salt").hexdigest()
        expected_phone = hashlib.sha256(b"+1234567890default_salt").hexdigest()
        self.assertEqual(normalized.customer_email, expected_email)
        self.assertEqual(normalized.customer_phone, expected_phone)

    def test_woocommerce_normalization(self):
        # Mock WooCommerce payload
        woo_payload = {
            "id": 9876,
            "total_tax": "8.00",
            "discount_total": "12.00",
            "shipping_total": "4.00",
            "line_items": [
                {
                    "sku": "TSHIRT-BLUE-L",
                    "quantity": 2,
                    "subtotal": "40.00", # Price before discounts
                    "total": "28.00"      # Price after discounts
                }
            ],
            "refunds": [],
            "billing": {
                "email": "woo_user@example.com",
                "phone": "+9876543210"
            },
            "date_created": "2026-06-08T21:00:00"
        }

        normalized = self.adapter.normalize_woocommerce(woo_payload)

        self.assertEqual(normalized.order_id, "9876")
        self.assertEqual(normalized.tenant_id, self.tenant_id)
        # Woo subtotal is gross price before discounts
        self.assertEqual(normalized.gross_revenue, 40.0)
        self.assertEqual(normalized.discounts, 12.0)
        self.assertEqual(normalized.shipping, 4.0)
        self.assertEqual(normalized.tax, 8.0)
        self.assertEqual(normalized.refunds, 0.0)
        self.assertLen(normalized.line_items, 1)
        self.assertEqual(normalized.line_items[0].sku, "TSHIRT-BLUE-L")
        # subtotal (40.0) / qty (2)
        self.assertEqual(normalized.line_items[0].price, 20.0)
        expected_email = hashlib.sha256(b"woo_user@example.comdefault_salt").hexdigest()
        expected_phone = hashlib.sha256(b"+9876543210default_salt").hexdigest()
        self.assertEqual(normalized.customer_email, expected_email)
        self.assertEqual(normalized.customer_phone, expected_phone)

if __name__ == "__main__":
    absltest.main()
