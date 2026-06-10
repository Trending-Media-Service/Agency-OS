# Autonomy Graduation Runner unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import autonomy_runner

class AutonomyRunnerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.runner = autonomy_runner.AutonomyGraduationRunner()
        self.tenant_id = "t1"
        self.brand_name = "Abley"
        # Setup metrics WITH cogs to prevent cold start by default
        self.metrics = {"CM1": 1000.0, "POAS": 1.1, "COGS": 200.0}
        self.alerts = []
        
        self.high_impact_card = {
            "id": "c1",
            "tenant_id": self.tenant_id,
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 8.0,
            "description": "Increase bid",
            "payload": {
                "campaign_id": "c",
                "ad_group_id": "g",
                "old_bid": 1.0,
                "new_bid": 1.2
            },
            "created_at": "now",
            "status": "PENDING"
        }
        self.low_impact_card = {
            "id": "c2",
            "tenant_id": self.tenant_id,
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 4.0,
            "description": "Increase minor bid",
            "payload": {
                "campaign_id": "c",
                "ad_group_id": "g",
                "old_bid": 1.0,
                "new_bid": 1.1
            },
            "created_at": "now",
            "status": "PENDING"
        }
        self.invalid_card = {
            "id": "c3",
            "tenant_id": self.tenant_id,
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 4.0,
            "description": "Malformed payload",
            "payload": {},
            "created_at": "now",
            "status": "PENDING"
        }

    def test_run_cycle_tier2_full_autonomy(self):
        proposed = [self.high_impact_card, self.low_impact_card, self.invalid_card]
        
        results = self.runner.run_autonomy_cycle(
            self.tenant_id, self.brand_name,
            gtm_present=True, pixel_present=True, capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0, gmc_warning_count=0,
            reputation_alert_count=0,
            financial_metrics=self.metrics, open_alerts=self.alerts,
            proposed_cards=proposed
        )

        self.assertEqual(results.trust_score, 100.0)
        self.assertEqual(results.autonomy_tier, 2)
        self.assertFalse(results.lockout_active)
        self.assertFalse(results.needs_cogs)

        cards = {c["id"]: c for c in results.processed_cards}
        self.assertEqual(cards["c1"]["status"], "APPROVED")
        self.assertEqual(cards["c2"]["status"], "PENDING")
        self.assertEqual(cards["c3"]["status"], "REJECTED")

    def test_run_cycle_cold_start_cogs_fallback(self):
        # Missing COGS key triggers cold start
        colds_metrics = {"CM1": 100.0, "POAS": 1.0}
        proposed = [self.high_impact_card]

        results = self.runner.run_autonomy_cycle(
            self.tenant_id, self.brand_name,
            gtm_present=True, pixel_present=True, capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0, gmc_warning_count=0,
            reputation_alert_count=0,
            financial_metrics=colds_metrics, open_alerts=self.alerts,
            proposed_cards=proposed
        )

        self.assertTrue(results.needs_cogs)
        self.assertIn("marginBasis fallback", results.processed_cards[0]["description"])

    def test_run_cycle_opa_violations(self):
        # Runaway bid (new_bid = $15.0) triggers OPA violation
        runaway_card = self.high_impact_card.copy()
        runaway_card["payload"] = {
            "campaign_id": "c",
            "ad_group_id": "g",
            "old_bid": 1.0,
            "new_bid": 15.0
        }
        proposed = [runaway_card]

        results = self.runner.run_autonomy_cycle(
            self.tenant_id, self.brand_name,
            gtm_present=True, pixel_present=True, capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0, gmc_warning_count=0,
            reputation_alert_count=0,
            financial_metrics=self.metrics, open_alerts=self.alerts,
            proposed_cards=proposed
        )

        self.assertEqual(results.processed_cards[0]["status"], "REJECTED")
        self.assertIn("OPA Violations", results.processed_cards[0]["description"])

    def test_stateful_queue_resumption_workflow(self):
        # In Tier 1, cards are queued as PENDING
        proposed = [self.high_impact_card]
        
        results = self.runner.run_autonomy_cycle(
            self.tenant_id, self.brand_name,
            gtm_present=False, pixel_present=True, capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0, gmc_warning_count=0,
            reputation_alert_count=0,
            financial_metrics=self.metrics, open_alerts=self.alerts,
            proposed_cards=proposed
        )
        self.assertEqual(results.processed_cards[0]["status"], "PENDING")
        self.assertIn("c1", self.runner.stateful_queue)

        # Resume execution with CLIENT_EXECUTIVE role -> Approves successfully
        res = self.runner.resume_and_execute("c1", "CLIENT_EXECUTIVE")
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["card"]["status"], "APPROVED")
        self.assertNotIn("c1", self.runner.stateful_queue)

    def test_stateful_queue_resumption_unauthorized_role(self):
        proposed = [self.high_impact_card]
        self.runner.run_autonomy_cycle(
            self.tenant_id, self.brand_name,
            gtm_present=False, pixel_present=True, capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0, gmc_warning_count=0,
            reputation_alert_count=0,
            financial_metrics=self.metrics, open_alerts=self.alerts,
            proposed_cards=proposed
        )

        # Unauthorized client DBA role tries to resume -> Raises PermissionError
        with self.assertRaises(PermissionError):
            self.runner.resume_and_execute("c1", "CLIENT_DBA")

if __name__ == "__main__":
    absltest.main()
