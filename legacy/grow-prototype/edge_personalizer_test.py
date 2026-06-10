# Edge Personalizer unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import edge_personalizer

class EdgePersonalizerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.rules = [
            edge_personalizer.PersonalizationRule(
                utm_param="utm_content",
                trigger_value="save20",
                variant_payload={"headline": "Save 20% on Sweaters", "coupon_code": "SAVE20"}
            ),
            edge_personalizer.PersonalizationRule(
                utm_param="utm_campaign",
                trigger_value="wool-promo",
                variant_payload={"headline": "Premium Wool Collection", "coupon_code": None}
            )
        ]
        self.personalizer = edge_personalizer.EdgePersonalizer(self.rules)

    def test_resolve_variant_match(self):
        params = {"utm_content": "save20", "gclid": "abc"}
        variant = self.personalizer.resolve_variant(params)
        self.assertEqual(variant["headline"], "Save 20% on Sweaters")
        self.assertEqual(variant["coupon_code"], "SAVE20")

    def test_resolve_variant_case_insensitive(self):
        params = {"UTM_CONTENT": "SAVE20"}
        variant = self.personalizer.resolve_variant(params)
        self.assertEqual(variant["headline"], "Save 20% on Sweaters")

    def test_resolve_variant_default(self):
        params = {"utm_source": "google"} # No matching UTM content or campaign
        variant = self.personalizer.resolve_variant(params)
        self.assertEqual(variant["headline"], "Welcome to Abley's Premium Sweaters")
        self.assertIsNone(variant["coupon_code"])

if __name__ == "__main__":
    absltest.main()
