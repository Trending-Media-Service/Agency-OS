import os
import sys
from flask import Flask, jsonify, request, send_from_directory

# Ensure google3 is in path if running from elsewhere
# This is a helper for local running if needed, but we should rely on PYTHONPATH
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../..')))

from google3.learning.gemini.agents.projects.agency_os import autonomy_runner
from google3.learning.gemini.agents.projects.agency_os import approval_portal

app = Flask(__name__, static_folder='static', static_url_path='')

runner = autonomy_runner.AutonomyGraduationRunner()
portal = approval_portal.ActionApprovalPortal()

# Global in-memory state to simulate DB
state = {
    "tenant_id": "tenant-abc",
    "brand_name": "Abley",
    "gtm_present": True,
    "pixel_present": True,
    "capi_dedup_rate": 0.98,
    "gmc_critical_mismatch_count": 0,
    "gmc_warning_count": 1,
    "reputation_alert_count": 0,
    "financial_metrics": {"CM1": 12000.0, "POAS": 1.4, "COGS": 5000.0}, # Added COGS to avoid cold start fallback unless wanted
    "open_alerts": [],
    "integrations": [
        {"name": "google_ads", "connected": True},
        {"name": "facebook_ads", "connected": True},
        {"name": "shopify", "connected": True},
        {"name": "google_merchant_center", "connected": True}
    ],
    "processed_cards": [] # Keep track of processed cards
}

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    score = runner.ats_calc.calculate_score(
        state["gtm_present"],
        state["pixel_present"],
        state["capi_dedup_rate"],
        state["gmc_critical_mismatch_count"],
        state["gmc_warning_count"],
        state["reputation_alert_count"]
    )
    tier = runner.ats_calc.resolve_autonomy_tier(score)
    
    return jsonify({
        "tenant_id": state["tenant_id"],
        "brand_name": state["brand_name"],
        "trust_score": score,
        "autonomy_tier": tier,
        "lockout_active": tier == 0,
        "integrations": state["integrations"],
        "financial_metrics": state["financial_metrics"]
    })

@app.route('/api/cards', methods=['GET'])
def get_cards():
    # Return cards from the runner's stateful queue
    cards = []
    for card_id, queue_item in runner.stateful_queue.items():
        cards.append(queue_item["card"])
    # Also include processed cards that might not be in queue (e.g. approved/rejected)
    # for visualization
    return jsonify({
        "pending": cards,
        "processed": state["processed_cards"]
    })

@app.route('/api/sweep', methods=['POST'])
def run_sweep():
    # Simulate receiving some proposed cards
    # In a real app, these would come from an AI recommendation engine
    proposed_cards = request.json.get("proposed_cards", [
        {
            "id": "card-1",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 8.5,
            "description": "Increase bid for high-performing campaign",
            "payload": {
                "campaign_id": "camp-1",
                "ad_group_id": "adg-1",
                "new_bid": 5.0,
                "old_bid": 2.5
            },
            "created_at": "2026-06-09T18:00:00Z",
            "status": "PENDING"
        },
        {
            "id": "card-2",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BUDGET_REALLOCATION",
            "impact_score": 6.5,
            "description": "Reallocate budget from underperforming ad set",
            "payload": {
                "source_campaign_id": "camp-2",
                "target_campaign_id": "camp-3",
                "amount": 1000.0
            },
            "created_at": "2026-06-09T18:00:00Z",
            "status": "PENDING"
        },
        {
            "id": "card-3",
            "tenant_id": "tenant-abc",
            "recommendation_type": "BID_ADJUSTMENT",
            "impact_score": 9.5,
            "description": "Violate OPA: Increase bid too high",
            "payload": {
                "campaign_id": "camp-1",
                "ad_group_id": "adg-1",
                "new_bid": 15.0,
                "old_bid": 2.0
            },
            "created_at": "2026-06-09T18:00:00Z",
            "status": "PENDING"
        }
    ])

    results = runner.run_autonomy_cycle(
        tenant_id=state["tenant_id"],
        brand_name=state["brand_name"],
        gtm_present=state["gtm_present"],
        pixel_present=state["pixel_present"],
        capi_dedup_rate=state["capi_dedup_rate"],
        gmc_critical_mismatch_count=state["gmc_critical_mismatch_count"],
        gmc_warning_count=state["gmc_warning_count"],
        reputation_alert_count=state["reputation_alert_count"],
        financial_metrics=state["financial_metrics"],
        open_alerts=state["open_alerts"],
        proposed_cards=proposed_cards
    )

    # Update state with processed cards (for history)
    for card in results.processed_cards:
        if card["status"] != "PENDING":
            # If it was auto-approved or rejected, add to processed
            state["processed_cards"].append(card)

    return jsonify({
        "trust_score": results.trust_score,
        "autonomy_tier": results.autonomy_tier,
        "lockout_active": results.lockout_active,
        "processed_cards": results.processed_cards
    })

@app.route('/api/approve', methods=['POST'])
def approve_card():
    data = request.json
    card_id = data.get("card_id")
    user_role = data.get("user_role", "AGENCY_OWNER") # Default to authorized role for simplicity if not provided

    if not card_id:
        return jsonify({"error": "Missing card_id"}), 400

    # We need to find the card in the queue to approve it via portal
    # or resume it via runner.
    # The runner's `resume_and_execute` handles it if it's in the stateful queue.
    # The portal's `approve_card` seems to be for direct approval of a card object.
    
    if card_id in runner.stateful_queue:
        try:
            # resume_and_execute returns {"status": ..., "card": ...}
            res = runner.resume_and_execute(card_id, user_role)
            card = res["card"]
            state["processed_cards"].append(card)
            return jsonify({"status": "success", "card": card})
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "Card not found in pending queue"}), 404

@app.route('/api/reject', methods=['POST'])
def reject_card():
    data = request.json
    card_id = data.get("card_id")
    user_role = data.get("user_role", "AGENCY_OWNER")

    if not card_id:
        return jsonify({"error": "Missing card_id"}), 400

    if card_id in runner.stateful_queue:
        # The runner doesn't have a direct 'reject' method that evicts,
        # but we can simulate it by using the portal or just evicting it.
        # Actually portal has reject_card.
        card = runner.stateful_queue[card_id]["card"]
        try:
            res = portal.reject_card(card, user_role)
            # Evict from runner queue
            del runner.stateful_queue[card_id]
            updated_card = res["updated_card"]
            state["processed_cards"].append(updated_card)
            return jsonify({"status": "success", "card": updated_card})
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "Card not found in pending queue"}), 404

# Endpoint to update state for testing (e.g. change trust factors)
@app.route('/api/state', methods=['POST'])
def update_state():
    global state
    data = request.json
    for k, v in data.items():
        if k in state:
            state[k] = v
    return jsonify({"status": "success", "state": state})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
