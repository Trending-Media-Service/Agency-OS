# Creative Analyzer unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import creative_analyzer

class CreativeAnalyzerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.analyzer = creative_analyzer.CreativeAnalyzer()
        self.ads = [
            creative_analyzer.AdPerformance(
                ad_id="ad1", campaign_id="camp1", spend=500.0, conversions=5, clicks=100,
                attributes={"color": "red", "hook": "question"} # CVR = 5/100 = 5%
            ),
            creative_analyzer.AdPerformance(
                ad_id="ad2", campaign_id="camp1", spend=400.0, conversions=1, clicks=100,
                attributes={"color": "blue", "hook": "question"} # CVR = 1/100 = 1%
            ),
            creative_analyzer.AdPerformance(
                ad_id="ad3", campaign_id="camp1", spend=100.0, conversions=0, clicks=10,
                attributes={"color": "blue", "hook": "statement"} # CVR = 0/10 = 0%
            )
        ]

    def test_analyze_features(self):
        report = self.analyzer.analyze_features(self.ads)
        
        # Check color red
        self.assertEqual(report["color"]["red"]["cvr"], 0.05)
        self.assertEqual(report["color"]["red"]["spend"], 500.0)

        # Check color blue
        # Total spend = 400 + 100 = 500.0. Total clicks = 100 + 10 = 110. Total conversions = 1.
        # CVR = 1 / 110 = 0.00909
        self.assertAlmostEqual(report["color"]["blue"]["cvr"], 0.0090909, places=5)
        self.assertEqual(report["color"]["blue"]["spend"], 500.0)

    def test_recommend_pauses_threshold(self):
        report = self.analyzer.analyze_features(self.ads)
        # Threshold 1.5% (0.015), min spend $300.
        # 'color: blue' has CVR 0.9% and spend $500 -> should be paused.
        # 'hook: statement' has CVR 0% but spend only $100 -> should NOT be paused (insufficient spend).
        recs = self.analyzer.recommend_pauses(report, cvr_threshold=0.015, min_spend=300.0)

        self.assertLen(recs, 1)
        rec = recs[0]
        self.assertEqual(rec["attribute"], "color")
        self.assertEqual(rec["value"], "blue")
        self.assertEqual(rec["action"], "PAUSE_CREATIVE_FEATURE")
        self.assertIn("Underperforming creative asset", rec["reason"])

if __name__ == "__main__":
    absltest.main()
