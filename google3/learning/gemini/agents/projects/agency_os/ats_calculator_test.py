# ATS Calculator unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import ats_calculator

class AtsCalculatorTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.calc = ats_calculator.AtsCalculator()

    def test_perfect_setup_tier2(self):
        score = self.calc.calculate_score(
            gtm_present=True,
            pixel_present=True,
            capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0,
            gmc_warning_count=0,
            reputation_alert_count=0
        )
        self.assertEqual(score, 100.0)
        self.assertEqual(self.calc.resolve_autonomy_tier(score), 2)

    def test_missing_tags_tier1(self):
        # Missing GTM (-30) -> Score = 70.0 -> Tier 1
        score = self.calc.calculate_score(
            gtm_present=False,
            pixel_present=True,
            capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=0,
            gmc_warning_count=0,
            reputation_alert_count=0
        )
        self.assertEqual(score, 70.0)
        self.assertEqual(self.calc.resolve_autonomy_tier(score), 1)

    def test_capi_deduplication_proportional_deduction(self):
        # Tags present, but CAPI matches only 50% (-10 points)
        score = self.calc.calculate_score(
            gtm_present=True,
            pixel_present=True,
            capi_dedup_rate=0.5,
            gmc_critical_mismatch_count=0,
            gmc_warning_count=0,
            reputation_alert_count=0
        )
        self.assertEqual(score, 90.0)

    def test_critical_feed_errors_and_alerts_tier0(self):
        score = self.calc.calculate_score(
            gtm_present=True,
            pixel_present=True,
            capi_dedup_rate=1.0,
            gmc_critical_mismatch_count=3,
            gmc_warning_count=0,
            reputation_alert_count=2
        )
        self.assertEqual(score, 40.0)
        self.assertEqual(self.calc.resolve_autonomy_tier(score), 0)

    def test_maximum_deductions_capped(self):
        score = self.calc.calculate_score(
            gtm_present=False,
            pixel_present=False,
            capi_dedup_rate=0.0,
            gmc_critical_mismatch_count=10,
            gmc_warning_count=10,
            reputation_alert_count=10
        )
        self.assertEqual(score, 0.0)

    def test_calculate_dynamic_ats_perfect(self):
        score = self.calc.calculate_dynamic_ats(
            total_proposed=10, approved=10,
            total_auto=5, success_auto=5,
            overrides=0, days_since_last_override=0.0
        )
        self.assertEqual(score, 100.0)

    def test_calculate_dynamic_ats_partial(self):
        # 8/10 approved (80% * 60 = 48)
        # 4/5 success (80% * 40 = 32)
        # 48 + 32 = 80.0
        score = self.calc.calculate_dynamic_ats(
            total_proposed=10, approved=8,
            total_auto=5, success_auto=4,
            overrides=0, days_since_last_override=0.0
        )
        self.assertEqual(score, 80.0)

    def test_calculate_dynamic_ats_overrides_decay(self):
        # Perfect actions (100.0) but 1 override 15 days ago (decay = 0.5)
        # Penalty = 1 * 20 * 0.5 = 10.0 -> Score = 90.0
        score = self.calc.calculate_dynamic_ats(
            total_proposed=10, approved=10,
            total_auto=5, success_auto=5,
            overrides=1, days_since_last_override=15.0
        )
        self.assertEqual(score, 90.0)

        # Perfect actions (100.0) but 1 override 30 days ago (decay = 0.0)
        # Penalty = 0 -> Score = 100.0
        score_cooldown = self.calc.calculate_dynamic_ats(
            total_proposed=10, approved=10,
            total_auto=5, success_auto=5,
            overrides=1, days_since_last_override=30.0
        )
        self.assertEqual(score_cooldown, 100.0)

if __name__ == "__main__":
    absltest.main()
