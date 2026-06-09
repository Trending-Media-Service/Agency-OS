# Metrics Tracker unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import metrics_tracker

class MetricsTrackerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.tracker = metrics_tracker.MetricsTracker()
        self.tracker.reset()

    def test_record_and_get_metrics(self):
        self.tracker.record_request(latency_ms=250.0, is_success=True)
        self.tracker.record_request(latency_ms=750.0, is_success=False)
        self.tracker.update_backlog(10)

        stats = self.tracker.get_metrics_payload()

        self.assertEqual(stats["total_requests"], 2)
        self.assertEqual(stats["average_latency_ms"], 500.0)
        self.assertEqual(stats["failure_rate"], 0.50)
        self.assertEqual(stats["backlog_depth"], 10)

    def test_evaluate_rules_healthy(self):
        self.tracker.record_request(latency_ms=100.0, is_success=True)
        self.tracker.update_backlog(5)
        
        is_healthy, alerts = self.tracker.evaluate_rules()
        self.assertTrue(is_healthy)
        self.assertEmpty(alerts)

    def test_evaluate_rules_latency_and_failure_alerts(self):
        # 1 request that fails and takes 1200ms -> Failure rate 100%,
        # latency 1200ms.
        self.tracker.record_request(latency_ms=1200.0, is_success=False)
        self.tracker.update_backlog(150) # Backlog depth > 100

        is_healthy, alerts = self.tracker.evaluate_rules()

        self.assertFalse(is_healthy)
        self.assertLen(alerts, 3) # Latency alert, Failure alert, Backlog alert
        self.assertTrue(any("LATENCY_SPIKE" in a for a in alerts))
        self.assertTrue(any("HIGH_ERRORS" in a for a in alerts))
        self.assertTrue(any("QUEUE_BACKLOG" in a for a in alerts))

if __name__ == "__main__":
    absltest.main()
