# Technical Sweep unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import technical_sweep

class TechnicalSweepTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.sweep = technical_sweep.TechnicalSweepSimulator()

    def test_audit_page_source_healthy(self):
        html = """
        <html>
        <head>
          <script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
          <script src="https://connect.facebook.net/en_US/fbevents.js"></script>
        </head>
        <body>Test Page</body>
        </html>
        """
        report = self.sweep.audit_page_source("https://example.com", html)
        self.assertTrue(report.gtm_present)
        self.assertTrue(report.pixel_present)
        self.assertTrue(report.healthy)
        self.assertEmpty(report.warnings)

    def test_audit_page_source_missing_tags(self):
        html = "<html><body>No Tracking Here</body></html>"
        report = self.sweep.audit_page_source("https://example.com", html)
        self.assertFalse(report.gtm_present)
        self.assertFalse(report.pixel_present)
        self.assertFalse(report.healthy)
        self.assertLen(report.warnings, 2)
        self.assertIn("Google Tag Manager (GTM) script is missing.", report.warnings)
        self.assertIn("Meta Pixel script is missing.", report.warnings)

    def test_verify_capi_deduplication_perfect_match(self):
        browser_events = [
            {"event_name": "Purchase", "event_id": "tx_123"},
            {"event_name": "Purchase", "event_id": "tx_124"},
        ]
        server_events = [
            {"event_name": "Purchase", "event_id": "tx_123"},
            {"event_name": "Purchase", "event_id": "tx_124"},
        ]
        score = self.sweep.verify_capi_deduplication(browser_events, server_events)
        self.assertEqual(score, 1.0)

    def test_verify_capi_deduplication_partial_match(self):
        browser_events = [
            {"event_name": "Purchase", "event_id": "tx_123"},
            # tx_124 is missing from browser
        ]
        server_events = [
            {"event_name": "Purchase", "event_id": "tx_123"},
            {"event_name": "Purchase", "event_id": "tx_124"},
        ]
        score = self.sweep.verify_capi_deduplication(browser_events, server_events)
        self.assertEqual(score, 0.5)

    def test_verify_capi_deduplication_no_browser_events(self):
        server_events = [
            {"event_name": "Purchase", "event_id": "tx_123"},
        ]
        score = self.sweep.verify_capi_deduplication([], server_events)
        self.assertEqual(score, 0.0)

if __name__ == "__main__":
    absltest.main()
