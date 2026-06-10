# Commercialization Engine unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import commercialization

class CommercializationTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.engine = commercialization.CommercializationEngine()

    def test_calculate_saved_spend(self):
        budgets = {
            "adg-1": 100.0,  # saved spend = 100 * 3.5 = 350.0
            "adg-2": 50.0,   # saved spend = 50 * 10 = 500.0
            "adg-3": 200.0   # saved spend = 0 (duration missing)
        }
        durations = {
            "adg-1": 3.5,
            "adg-2": 10.0
        }

        total_saved = self.engine.calculate_saved_spend(budgets, durations)
        self.assertEqual(total_saved, 850.0)

    def test_calculate_monthly_fee_starter(self):
        # Starter: $299.0 base + 1.5% of $10,000 saved spend ($150.0) -> $449.0
        fee = self.engine.calculate_monthly_fee("STARTER", saved_spend=10000.0)
        self.assertEqual(fee, 449.0)

    def test_calculate_monthly_fee_professional(self):
        # Professional: $999.0 base + 1.0% of $20,000 saved spend ($200.0) -> $1199.0
        fee = self.engine.calculate_monthly_fee("professional", saved_spend=20000.0)
        self.assertEqual(fee, 1199.0)

    def test_calculate_monthly_fee_invalid_tier(self):
        with self.assertRaises(ValueError):
            self.engine.calculate_monthly_fee("INVALID_TIER", saved_spend=100.0)

if __name__ == "__main__":
    absltest.main()
