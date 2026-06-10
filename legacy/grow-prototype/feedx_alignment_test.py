# FeedX Alignment unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import feedx_alignment

class FeedXAlignmentTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.aligner = feedx_alignment.FeedXAlignment()

    def test_reconcile_catalog_aligned(self):
        gmc = [
            feedx_alignment.GmcProduct(
                "s1", "Shirt", 29.99, "in_stock", "http://l1"
            )
        ]
        store = [
            feedx_alignment.StoreProduct("s1", "Shirt", 29.99, "in_stock")
        ]
        mismatches = self.aligner.reconcile_catalog(gmc, store)
        self.assertEmpty(mismatches)

    def test_reconcile_catalog_missing_in_store(self):
        gmc = [
            feedx_alignment.GmcProduct(
                "s1", "Shirt", 29.99, "in_stock", "http://l1"
            )
        ]
        mismatches = self.aligner.reconcile_catalog(gmc, [])
        self.assertLen(mismatches, 1)
        self.assertEqual(mismatches[0]["error_type"], "MISSING_IN_STORE")
        self.assertEqual(mismatches[0]["severity"], "CRITICAL")

    def test_reconcile_catalog_price_mismatch(self):
        gmc = [
            feedx_alignment.GmcProduct(
                "s1", "Shirt", 29.99, "in_stock", "http://l1"
            )
        ]
        store = [
            # Store price is more expensive
            feedx_alignment.StoreProduct("s1", "Shirt", 34.99, "in_stock")
        ]
        mismatches = self.aligner.reconcile_catalog(gmc, store)
        self.assertLen(mismatches, 1)
        mismatch = mismatches[0]
        self.assertEqual(mismatch["error_type"], "DATA_MISMATCH")
        self.assertEqual(mismatch["severity"], "CRITICAL")
        self.assertAlmostEqual(mismatch["details"]["price_difference"], 5.0)

    def test_reconcile_catalog_availability_mismatch(self):
        gmc = [
            feedx_alignment.GmcProduct(
                "s1", "Shirt", 29.99, "in_stock", "http://l1"
            )
        ]
        store = [
            feedx_alignment.StoreProduct("s1", "Shirt", 29.99, "out_of_stock")
        ]
        mismatches = self.aligner.reconcile_catalog(gmc, store)
        self.assertLen(mismatches, 1)
        mismatch = mismatches[0]
        self.assertEqual(mismatch["error_type"], "DATA_MISMATCH")
        self.assertTrue(mismatch["details"]["availability_mismatch"])

if __name__ == "__main__":
    absltest.main()
