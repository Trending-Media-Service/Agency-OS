# API Layer unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import api_layer
from google3.learning.gemini.agents.projects.agency_os import autonomy_runner

class ApiLayerTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.runner = autonomy_runner.AutonomyGraduationRunner()
        self.server = api_layer.MockApiServer(self.runner)
        self.proposed_card = {
            "id": "c1",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 8.0,
            "description": "Increase bid",
            "payload": {"campaign_id": "c", "ad_group_id": "g", "old_bid": 1.0, "new_bid": 1.2},
            "created_at": "now",
            "status": "PENDING"
        }

    def test_get_integrations(self):
        status, body = self.server.route_request("GET", "/api/v1/integrations")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertLen(body["integrations"], 4)

    def test_get_autonomy_status(self):
        # Default mock state is healthy (GTM & Pixel true, etc. -> trust score 100)
        status, body = self.server.route_request("GET", "/api/v1/autonomy")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["trust_score"], 94.6)
        self.assertEqual(body["autonomy_tier"], 2)

    def test_auth_ticket_generation(self):
        payload = {"username": "chandansinghr"}
        status, body = self.server.route_request("POST", "/api/v1/auth/ticket", payload)
        self.assertEqual(status, 201)
        self.assertEqual(body["status"], "authorized")
        self.assertIn("chandansinghr", body["ticket_id"])

    def test_sweep_post_execution(self):
        # Default mock state has autonomy tier 2, so high impact card (8.0) should be APPROVED
        payload = {"proposed_cards": [self.proposed_card]}
        status, body = self.server.route_request("POST", "/api/v1/sweep", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["trust_score"], 94.6)
        self.assertEqual(body["autonomy_tier"], 2)
        self.assertFalse(body["lockout_active"])
        self.assertLen(body["processed_cards"], 1)
        self.assertEqual(body["processed_cards"][0]["status"], "APPROVED")

    def test_route_not_found(self):
        status, body = self.server.route_request("GET", "/api/v1/unknown_path")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

if __name__ == "__main__":
    absltest.main()
