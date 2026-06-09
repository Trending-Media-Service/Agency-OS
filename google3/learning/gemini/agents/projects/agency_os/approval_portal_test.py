# Approval Portal unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import approval_portal

class ApprovalPortalTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.portal = approval_portal.ActionApprovalPortal()
        self.pending_card = {
            "id": "c1",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 8.0,
            "description": "Increase bid",
            "payload": {"campaign_id": "c", "ad_group_id": "g", "old_bid": 1.0, "new_bid": 1.2},
            "created_at": "now",
            "status": "PENDING"
        }

    def test_owner_approves_successfully(self):
        receipt = self.portal.approve_card(self.pending_card, "AGENCY_OWNER")
        self.assertEqual(receipt["status"], "DISPATCHED")
        self.assertEqual(receipt["dispatched_by"], "AGENCY_OWNER")
        self.assertEqual(receipt["updated_card"]["status"], "APPROVED")
        self.assertIn("googleapis.com", receipt["webhook_url"]) # BID_ADJUSTMENT goes to Google

    def test_unauthorized_role_fails(self):
        with self.assertRaises(PermissionError):
            self.portal.approve_card(self.pending_card, "CLIENT_ACCOUNTANT")

    def test_cannot_approve_already_processed_card(self):
        approved_card = self.pending_card.copy()
        approved_card["status"] = "APPROVED"
        with self.assertRaises(ValueError):
            self.portal.approve_card(approved_card, "CLIENT_DBA")

    def test_dba_rejects_successfully(self):
        receipt = self.portal.reject_card(self.pending_card, "CLIENT_DBA")
        self.assertEqual(receipt["status"], "REJECTED_SUCCESSFULLY")
        self.assertEqual(receipt["updated_card"]["status"], "REJECTED")

if __name__ == "__main__":
    absltest.main()
