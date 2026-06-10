# Context Constructor unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import context_constructor

class ContextConstructorTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.constructor = context_constructor.ContextConstructor()
        self.metrics = {"CM1": 5000.0, "CM2": 3500.0, "POAS": 1.25}
        self.alerts = [
            {"alert_type": "BRAND_REPUTATION_CRITICAL", "message": "High-risk review flagged."}
        ]

    def test_construct_context_tier2(self):
        ctx = self.constructor.construct_agent_context(
            tenant_id="t-101",
            brand_name="Abley",
            trust_score=95.0,
            autonomy_tier=2,
            financial_metrics=self.metrics,
            open_alerts=self.alerts
        )

        self.assertIn("# Active Tenant Context", ctx)
        self.assertIn("**Tenant ID**: t-101", ctx)
        self.assertIn("**Trust Score**: 95.0/100.0", ctx)
        self.assertIn("**Autonomy Tier**: Tier 2", ctx)
        self.assertIn("DIRECTIVE: FULL AUTONOMY ENABLED", ctx)
        self.assertIn("- CM1: 5000.00", ctx)
        self.assertIn("1. [BRAND_REPUTATION_CRITICAL] High-risk review flagged.", ctx)

    def test_construct_context_tier1(self):
        ctx = self.constructor.construct_agent_context(
            tenant_id="t-101",
            brand_name="Abley",
            trust_score=75.0,
            autonomy_tier=1,
            financial_metrics=self.metrics,
            open_alerts=self.alerts
        )
        self.assertIn("DIRECTIVE: SEMI-AUTONOMY ENABLED", ctx)
        self.assertIn("MUST write them to the `action_cards` table", ctx)

    def test_construct_context_tier0_empty_alerts(self):
        ctx = self.constructor.construct_agent_context(
            tenant_id="t-101",
            brand_name="Abley",
            trust_score=45.0,
            autonomy_tier=0,
            financial_metrics=self.metrics,
            open_alerts=[]
        )
        self.assertIn("DIRECTIVE: SYSTEM LOCKED / SAFE MODE", ctx)
        self.assertIn("*No open brand reputation or configuration alerts.*", ctx)

if __name__ == "__main__":
    absltest.main()
