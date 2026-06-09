# VAR reconciler unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import var_reconciler

class VarReconcilerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.probabilities = {
            "LEAD": 0.10,
            "MEETING": 0.30,
            "PROPOSAL": 0.60,
            "WON": 1.00,
            "LOST": 0.00
        }
        self.reconciler = var_reconciler.VarReconciler(self.probabilities)

    def test_calculate_var(self):
        opportunities = [
            var_reconciler.Opportunity("d1", "t1", 10000.0, "LEAD"),
            var_reconciler.Opportunity("d2", "t1", 50000.0, "PROPOSAL"),
            var_reconciler.Opportunity("d3", "t1", 20000.0, "WON")
        ]
        total_var = self.reconciler.calculate_var(opportunities)
        self.assertEqual(total_var, 51000.0)

    def test_reconcile_and_retrain_amplify(self):
        old_opps = [
            var_reconciler.Opportunity(
                "d1", "t1", 10000.0, "LEAD", gclid="g1"
            )
        ]
        new_opps = [
            var_reconciler.Opportunity(
                "d1", "t1", 10000.0, "PROPOSAL", gclid="g1"
            )
        ]

        adjustments = self.reconciler.reconcile_and_retrain(old_opps, new_opps)

        self.assertLen(adjustments, 1)
        event = adjustments[0]
        self.assertEqual(event["gclid"], "g1")
        self.assertEqual(event["deal_id"], "d1")
        self.assertEqual(event["adjustment_value"], 5000.0)
        self.assertEqual(event["action_type"], "AMPLIFY")

    def test_reconcile_and_retrain_retract(self):
        old_opps = [
            var_reconciler.Opportunity(
                "d2", "t1", 50000.0, "PROPOSAL", gclid="g2"
            )
        ]
        new_opps = [
            var_reconciler.Opportunity(
                "d2", "t1", 50000.0, "LOST", gclid="g2"
            )
        ]

        adjustments = self.reconciler.reconcile_and_retrain(old_opps, new_opps)

        self.assertLen(adjustments, 1)
        event = adjustments[0]
        self.assertEqual(event["gclid"], "g2")
        self.assertEqual(event["deal_id"], "d2")
        self.assertEqual(event["adjustment_value"], -30000.0)
        self.assertEqual(event["action_type"], "RETRACT")

    def test_reconcile_untracked_filtered(self):
        old_opps = [
            var_reconciler.Opportunity(
                "d1", "t1", 10000.0, "LEAD", gclid=None
            )
        ]
        new_opps = [
            var_reconciler.Opportunity(
                "d1", "t1", 10000.0, "PROPOSAL", gclid=None
            )
        ]

        adjustments = self.reconciler.reconcile_and_retrain(old_opps, new_opps)
        self.assertEmpty(adjustments)

    def test_calculate_lqs_high_quality(self):
        score = self.reconciler.calculate_lqs(
            email="buyer@google.com",
            form_submission_speed_sec=5.0,
            sentiment_score=0.5
        )
        self.assertEqual(score, 85.0)

    def test_calculate_lqs_low_quality(self):
        score = self.reconciler.calculate_lqs(
            email="spam@gmail.com",
            form_submission_speed_sec=0.5,
            sentiment_score=-0.8
        )
        self.assertEqual(score, 10.0)

    def test_calculate_lqs_max_clamped(self):
        score = self.reconciler.calculate_lqs(
            email="partner@stripe.com",
            form_submission_speed_sec=15.0,
            sentiment_score=1.5
        )
        self.assertEqual(score, 100.0)

if __name__ == "__main__":
    absltest.main()
