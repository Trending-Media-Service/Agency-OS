# Database Error Sink unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import error_sink

class ErrorSinkTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.sink = error_sink.DatabaseErrorSink()

    def test_pii_scrubbing_sensitive_keys(self):
        payload = {
            "user_id": "u123",
            "api_key": "secret-api-key-1234",
            "db_password": "superpassword",
            "metadata": {"access_token": "token-xyz"}
        }

        sanitized = self.sink.sanitize_payload(payload)

        self.assertEqual(sanitized["user_id"], "u123")
        self.assertEqual(sanitized["api_key"], "[SCRUBBED_SENSITIVE]")
        self.assertEqual(sanitized["db_password"], "[SCRUBBED_SENSITIVE]")
        self.assertEqual(
            sanitized["metadata"]["access_token"], "[SCRUBBED_SENSITIVE]"
        )

    def test_pii_scrubbing_luhn_valid_credit_card(self):
        # Valid test Visa card: 4111-1111-1111-1111
        payload = {
            "message": "Payment failed for card 4111-1111-1111-1111 in checkout",
            "account_id": "acc-999"
        }

        sanitized = self.sink.sanitize_payload(payload)
        self.assertIn("[SCRUBBED_CREDIT_CARD]", sanitized["message"])
        self.assertNotIn("4111-1111-1111-1111", sanitized["message"])

    def test_pii_intact_luhn_invalid_card(self):
        # Invalid checksum sequence: 1234-5678-1234-5678
        payload = {
            "message": "Order reference 1234-5678-1234-5678 completed",
        }

        sanitized = self.sink.sanitize_payload(payload)
        self.assertEqual(sanitized["message"], "Order reference 1234-5678-1234-5678 completed")

    def test_db_restore_drill_success(self):
        self.assertTrue(self.sink.run_db_restore_drill())

if __name__ == "__main__":
    absltest.main()
