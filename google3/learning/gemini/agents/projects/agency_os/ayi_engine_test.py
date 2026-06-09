# AYI Engine unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import ayi_engine

class AyiEngineTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.brand_keywords = ["Abley", "Abley's", "Abley Sweaters"]
        # Value per click is 1.50 (e.g. $1.5 CPC)
        self.engine = ayi_engine.AyiEngine(
            self.brand_keywords, target_value_per_click=1.50
        )

    def test_calculate_baseline_clicks(self):
        # 2 days of historical GSC data
        historical_data = [
            ayi_engine.GscMetric("2026-06-01", "abley cozy sweater", 10, 100),
            ayi_engine.GscMetric("2026-06-01", "best wool sweaters", 5, 200),
            ayi_engine.GscMetric("2026-06-01", "Abley's discount", 15, 150),
            
            ayi_engine.GscMetric("2026-06-02", "abley brand", 12, 120),
            ayi_engine.GscMetric("2026-06-02", "how to wash wool", 2, 50),
            ayi_engine.GscMetric("2026-06-02", "cheap sweaters online", 8, 80),
        ]

        # Brand Clicks:
        # Day 1: 10 + 15 = 25
        # Day 2: 12
        # Avg = (25 + 12) / 2 = 18.5
        baseline = self.engine.calculate_baseline_clicks(historical_data)
        self.assertEqual(baseline, 18.5)

    def test_calculate_baseline_clicks_empty(self):
        self.assertEqual(self.engine.calculate_baseline_clicks([]), 0.0)

    def test_calculate_organic_lift(self):
        current_data = [
            ayi_engine.GscMetric("2026-06-08", "Abley hoodies", 25, 250),
            ayi_engine.GscMetric("2026-06-08", "warm winter clothes", 30, 300)
        ]
        
        current_clicks = self.engine.calculate_current_brand_clicks(current_data)
        self.assertEqual(current_clicks, 25.0)

        # Baseline was 18.5, Lift = 25.0 - 18.5 = 6.5
        lift = self.engine.calculate_organic_lift(current_clicks, 18.5)
        self.assertEqual(lift, 6.5)

    def test_calculate_cm3_awareness_positive(self):
        # Lift 6.5 * 1.50 = 9.75
        cm3_awareness = self.engine.calculate_cm3_awareness(6.5)
        self.assertEqual(cm3_awareness, 9.75)

    def test_calculate_cm3_awareness_negative_or_zero(self):
        self.assertEqual(self.engine.calculate_cm3_awareness(-5.0), 0.0)
        self.assertEqual(self.engine.calculate_cm3_awareness(0.0), 0.0)

    def test_calculate_ayi(self):
        # CM3 Awareness = 9.75, Net Ad Spend = 100.0 -> AYI = 0.0975
        ayi = self.engine.calculate_ayi(cm3_awareness=9.75, net_ad_spend=100.0)
        self.assertEqual(ayi, 0.0975)

        ayi_zero = self.engine.calculate_ayi(cm3_awareness=9.75, net_ad_spend=0.0)
        self.assertEqual(ayi_zero, 0.0)

    def test_calculate_sov_success(self):
        sov = self.engine.calculate_sov(
            brand_impressions=50000.0,
            total_market_impressions=200000.0
        )
        self.assertEqual(sov, 25.0)

    def test_calculate_sov_zero_market_safe(self):
        sov = self.engine.calculate_sov(brand_impressions=10.0, total_market_impressions=0.0)
        self.assertEqual(sov, 0.0)

if __name__ == "__main__":
    absltest.main()
