# MMM Worker unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import mmm_worker

class MmmWorkerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.worker = mmm_worker.MmmWorker()

    def test_calculate_ipoas(self):
        # CM3 = 500.0, Baseline clicks = 100, target click value = 1.50 -> baseline value = 150.0
        # Incremental margin = 500.0 - 150.0 = 350.0
        # Net spend = 200.0 -> iPOAS = 350.0 / 200.0 = 1.75
        ipoas = self.worker.calculate_ipoas(
            cm3=500.0,
            baseline_clicks=100.0,
            target_value_per_click=1.50,
            net_ad_spend=200.0
        )
        self.assertEqual(ipoas, 1.75)

    def test_calculate_ipoas_zero_spend(self):
        self.assertEqual(self.worker.calculate_ipoas(100.0, 10.0, 1.0, 0.0), 0.0)

    def test_generate_reallocation_recommendations(self):
        campaigns = [
            {"campaign_id": "low-c1", "name": "Brand Search", "net_spend": 1000.0, "ipoas": 0.8}, # Low iPOAS
            {"campaign_id": "high-c2", "name": "PMax Prospecting", "net_spend": 2000.0, "ipoas": 1.5}, # High iPOAS
            {"campaign_id": "mid-c3", "name": "FB Retargeting", "net_spend": 1500.0, "ipoas": 1.1} # Mid
        ]

        # Target iPOAS = 1.2.
        # "low-c1" has ipoas < 1.0 -> underperforming.
        # "high-c2" has ipoas (1.5) >= 1.2 -> scaling candidate.
        # Shift 20% of 1000.0 = 200.0 from low-c1 to high-c2.
        recs = self.worker.generate_reallocation_recommendations(campaigns, target_ipoas=1.2)

        self.assertLen(recs, 1)
        rec = recs[0]
        self.assertEqual(rec["source_campaign_id"], "low-c1")
        self.assertEqual(rec["target_campaign_id"], "high-c2")
        self.assertEqual(rec["amount"], 200.0)
        self.assertIn("Cannibalization protection", rec["reason"])

if __name__ == "__main__":
    absltest.main()
