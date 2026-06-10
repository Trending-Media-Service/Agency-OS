# pLTV Engine unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import pltv_engine

class PltvEngineTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.engine = pltv_engine.PltvEngine()

    def test_calculate_historical_multipliers(self):
        mature = [
            pltv_engine.Cohort("2026-01", day30_value=1000.0, day90_value=1500.0), # 1.5x
            pltv_engine.Cohort("2026-02", day30_value=2000.0, day90_value=3200.0)  # 1.6x
        ]
        # Average multiplier: (1.5 + 1.6) / 2 = 1.55
        multiplier = self.engine.calculate_historical_multipliers(mature)
        self.assertEqual(multiplier, 1.55)

    def test_project_cohort_ltv(self):
        active = [
            pltv_engine.Cohort("2026-05", day30_value=100.0, day90_value=0.0) # Active
        ]
        projected = self.engine.project_cohort_ltv(active, multiplier=1.6)
        self.assertLen(projected, 1)
        self.assertEqual(projected[0].projected_ltv, 160.0)

    def test_project_cohort_ltv_mature_unchanged(self):
        active = [
            pltv_engine.Cohort("2026-01", day30_value=100.0, day90_value=150.0) # Already mature
        ]
        projected = self.engine.project_cohort_ltv(active, multiplier=1.6)
        self.assertEqual(projected[0].projected_ltv, 150.0)

if __name__ == "__main__":
    absltest.main()
