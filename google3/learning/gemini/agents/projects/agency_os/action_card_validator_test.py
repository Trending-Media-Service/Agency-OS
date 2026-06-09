# Action Card Validator unit tests
from absl.testing import absltest
from google3.learning.gemini.agents.projects.agency_os import action_card_validator

class ActionCardValidatorTest(absltest.TestCase):

    def setUp(self):
        super().setUp()
        self.valid_card = {
            "id": "uuid-12345",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 8.5,
            "description": "Increase bid for high-performing keywords.",
            "payload": {
                "campaign_id": "camp-1",
                "ad_group_id": "adg-2",
                "old_bid": 1.20,
                "new_bid": 1.50
            },
            "created_at": "2026-06-08T20:00:00Z",
            "status": "PENDING"
        }

    def test_valid_bid_adjustment_passes(self):
        is_valid, errors = action_card_validator.validate_action_card(self.valid_card)
        self.assertTrue(is_valid)
        self.assertEmpty(errors)

    def test_missing_base_fields_fails(self):
        invalid_card = self.valid_card.copy()
        del invalid_card["id"]
        del invalid_card["impact_score"]
        
        is_valid, errors = action_card_validator.validate_action_card(invalid_card)
        self.assertFalse(is_valid)
        self.assertLen(errors, 2)
        self.assertIn("Missing required base field: 'id'", errors)
        self.assertIn("Missing required base field: 'impact_score'", errors)

    def test_invalid_base_field_types_fails(self):
        invalid_card = self.valid_card.copy()
        invalid_card["impact_score"] = "very high" # Should be float/int
        invalid_card["payload"] = "not a dict"      # Should be dict
        
        is_valid, errors = action_card_validator.validate_action_card(invalid_card)
        self.assertFalse(is_valid)
        self.assertLen(errors, 2)
        self.assertIn("Field 'impact_score' has invalid type. Expected (<class 'int'>, <class 'float'>), got <class 'str'>", errors)

    def test_invalid_enums_and_ranges_fails(self):
        invalid_card = self.valid_card.copy()
        invalid_card["recommendation_type"] = "INVALID_TYPE"
        invalid_card["status"] = "COMPLETED" # Valid are PENDING, APPROVED, REJECTED
        invalid_card["impact_score"] = 12.5  # Max 10.0
        
        is_valid, errors = action_card_validator.validate_action_card(invalid_card)
        self.assertFalse(is_valid)
        self.assertLen(errors, 3)
        self.assertIn("impact_score must be between 0.0 and 10.0 (got 12.5)", errors)

    def test_budget_reallocation_payload_validation(self):
        card = {
            "id": "uuid-1",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BUDGET_REALLOCATION",
            "impact_score": 5.0,
            "description": "Shift budget.",
            "payload": {
                "source_campaign_id": "camp-1",
                # missing target_campaign_id
                "amount": "100" # invalid type string
            },
            "created_at": "now",
            "status": "PENDING"
        }
        is_valid, errors = action_card_validator.validate_action_card(card)
        self.assertFalse(is_valid)
        self.assertLen(errors, 2)
        self.assertIn("[BUDGET_REALLOCATION] Missing payload field: 'target_campaign_id'", errors)
        self.assertIn("[BUDGET_REALLOCATION] Payload field 'amount' has invalid type. Expected (<class 'int'>, <class 'float'>), got <class 'str'>", errors)

if __name__ == "__main__":
    absltest.main()
