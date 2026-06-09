# Account Discovery Engine unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import account_discovery

class AccountDiscoveryTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.engine = account_discovery.AccountDiscoveryEngine()

    def test_traverse_mcc_recursive(self):
        # MCC manager tree
        mcc_tree = {
            "id": "mcc-parent",
            "name": "Global MCC",
            "type": "MANAGER",
            "children": [
                {
                    "id": "mcc-sub",
                    "name": "APAC MCC",
                    "type": "MANAGER",
                    "children": [
                        {"id": "ads-1", "name": "Abley APAC", "type": "LEAF", "domain": "abley.com"},
                        {"id": "ads-2", "name": "Abley Tokyo", "type": "LEAF", "domain": "abley.jp"}
                    ]
                },
                {"id": "ads-3", "name": "Abley US", "type": "LEAF", "domain": "abley.com"}
            ]
        }

        accounts = self.engine.traverse_mcc(mcc_tree)
        self.assertLen(accounts, 3)
        ids = {a.account_id for a in accounts}
        self.assertEqual(ids, {"ads-1", "ads-2", "ads-3"})

    def test_discover_mca_merchants(self):
        mca_structure = {
            "id": "mca-parent",
            "name": "Global MCA",
            "sub_accounts": [
                {"id": "merch-1", "name": "Abley Store", "domain": "abley.com"},
                {"id": "merch-2", "name": "Other Brand", "domain": "other.com"}
            ]
        }
        merchants = self.engine.discover_mca_merchants(mca_structure)
        self.assertLen(merchants, 2)
        self.assertEqual(merchants[0].merchant_id, "merch-1")

    def test_auto_link_properties_domain_matching(self):
        tenant_id = "tenant-1"
        storefronts = [
            account_discovery.StorefrontProfile("st-1", "Abley's Shop", "https://abley.com/store")
        ]
        ads_accounts = [
            account_discovery.AdAccount("ads-1", "Ad account A", "abley.com")
        ]
        merchants = [
            account_discovery.MerchantProfile("m-1", "Merchant A", "abley.com")
        ]

        linked = self.engine.auto_link_properties(tenant_id, storefronts, ads_accounts, merchants)
        
        self.assertLen(linked, 1)
        link = linked[0]
        self.assertEqual(link.tenant_id, tenant_id)
        self.assertEqual(link.store_id, "st-1")
        self.assertEqual(link.ad_account_id, "ads-1")
        self.assertEqual(link.merchant_id, "m-1")
        self.assertEqual(link.status, "PENDING_VERIFICATION")

    def test_auto_link_properties_fuzzy_name_matching(self):
        tenant_id = "tenant-1"
        # Domains are missing, but name "Abley" is a substring of "Abley Sweaters"
        storefronts = [
            account_discovery.StorefrontProfile("st-1", "Abley", "https://abley-shop.com")
        ]
        ads_accounts = [
            # No domain match
            account_discovery.AdAccount("ads-1", "Abley Sweaters Ltd", "")
        ]
        merchants = [
            account_discovery.MerchantProfile("m-1", "Abley's Sweaters (MCA)", "")
        ]

        linked = self.engine.auto_link_properties(tenant_id, storefronts, ads_accounts, merchants)

        self.assertLen(linked, 1)
        link = linked[0]
        self.assertEqual(link.ad_account_id, "ads-1")
        self.assertEqual(link.merchant_id, "m-1")

if __name__ == "__main__":
    absltest.main()
