import pytest
import datetime as dt
import os
import hmac
import hashlib
import base64
import json
from sqlalchemy import select
from unittest.mock import patch, MagicMock, AsyncMock

from app.models import (
    Tenant,
    Brand,
    Connection,
    OpRow,
    OutboxItem,
    Campaign,
    Order,
    AuditEvent,
    ConsentBasis,
    TrustSnapshot,
    TrustEvent
)
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money, OpState
from app.kernel.loop import drain_once, propose, preview_and_gate
from app.kernel.services import audit_append, audit_verify
from app.services.marketing import MockMarketingClient
from app.services.mcp import McpClient

# --- TEST 58: REAL-WORLD SHOPIFY CONNECTION WEBHOOK LIFECYCLE ---
@pytest.mark.asyncio
async def test_rw_shopify_connection_webhook_lifecycle(client, session, mock_secrets_client, mock_mcp_client):
    """Verify the end-to-end webhook ingestion flow including HMAC signature verification, connection routing, and MCP lookup."""
    tenant_id = "wh-tenant"
    brand_id = "wh-brand"

    # 1. Seed tenant, brand and connection
    tenant = Tenant(
        id=tenant_id,
        name="Webhook Tenant",
        gcp_project="webhook-project"
    )
    brand = Brand(
        id=brand_id,
        tenant_id=tenant_id,
        name="Webhook Brand"
    )
    conn = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider="shopify",
        credential="projects/webhook-project/secrets/shopify-secret/versions/1",
        status="active",
        config={"shop_url": "test-webhook-shop.myshopify.com"}
    )
    session.add_all([tenant, brand, conn])
    await session.commit()

    # Seed Secret Manager with the webhook shared secret
    mock_secrets_client.store.update({
        "projects/webhook-project/secrets/shopify-secret/versions/1": "my-shared-webhook-secret-key"
    })

    # Mock the McpClient.call_tool to return verified order details from Shopify
    mock_order_response = {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "id": "order-999",
                    "total_price": "189.50",
                    "created_at": "2026-06-19T14:30:00Z"
                })
            }
        ]
    }
    mock_mcp_client.call_tool.return_value = mock_order_response

    # 2. Construct the webhook payload and calculate Shopify-compliant HMAC signature
    payload = {"id": "order-999", "total_price": "189.50", "created_at": "2026-06-19T14:30:00Z"}
    raw_body = json.dumps(payload).encode("utf-8")
    
    # Calculate HMAC signature
    sig_digest = hmac.new(
        b"my-shared-webhook-secret-key",
        raw_body,
        hashlib.sha256
    ).digest()
    sig_b64 = base64.b64encode(sig_digest).decode("utf-8")

    # 3. Deliver the webhook via the POST endpoint
    headers = {
        "X-Shopify-Shop-Domain": "test-webhook-shop.myshopify.com",
        "X-Shopify-Topic": "orders/create",
        "X-Shopify-Hmac-Sha256": sig_b64,
        "Content-Type": "application/json",
        "X-Request-Id": "req-unique-999"
    }

    resp = await client.post(
        "/webhooks/plugins/shopify",
        content=raw_body,
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert len(data["proposed_ops"]) == 1
    proposed_op_id = data["proposed_ops"][0]

    # 4. Verify that the translated operation is proposed and gated in the database
    # Query fresh from database to ensure transaction visibility
    stmt_op = select(OpRow).where(OpRow.id == proposed_op_id)
    res_op = await session.execute(stmt_op)
    op_row = res_op.scalar_one()

    assert op_row.tenant_id == tenant_id
    assert op_row.brand_id == brand_id
    assert op_row.action == "manage.shopify.sync_order"
    assert op_row.params["order_id"] == "order-999"
    assert op_row.params["amount_minor"] == 18950


# --- TEST 59: REAL-WORLD MARKETING OPTIMIZATION LOOP ---
@pytest.mark.asyncio
async def test_rw_marketing_optimization_loop(client, session, mock_secrets_client):
    """Verify autonomous marketing loop: detect low ROI, propose cross-channel budget reallocation Saga."""
    tenant_id = "mopt-tenant"
    brand_id = "mopt-brand"

    # 1. Seed tenant, brand, connections
    tenant = Tenant(id=tenant_id, name="Marketing Tenant", gcp_project="mopt-project")
    brand = Brand(id=brand_id, tenant_id=tenant_id, name="Marketing Brand")
    conn_google = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider="google-ads",
        credential="projects/mopt-project/secrets/google-ads/versions/1",
        status="active"
    )
    conn_meta = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider="meta-ads",
        credential="projects/mopt-project/secrets/meta-ads/versions/1",
        status="active"
    )
    
    # 2. Seed DONE campaign creation operations in OpRow (since evaluate-trust scans OpRow for DONE creations)
    op_g = OpRow(
        id="op-create-google",
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.campaign.create",
        params={"campaign_id": "camp-google", "provider": "google-ads", "budget_minor": 500000, "bid_minor": 5000, "name": "Google Ads Campaign"},
        state="DONE",
        impact=1,
        reversibility="COMPENSATABLE",
        preview_summary="Create Google campaign",
        idem_key="idem-create-google-campaign-123"
    )
    op_m = OpRow(
        id="op-create-meta",
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.campaign.create",
        params={"campaign_id": "camp-meta", "provider": "meta-ads", "budget_minor": 500000, "bid_minor": 5000, "name": "Meta Ads Campaign"},
        state="DONE",
        impact=1,
        reversibility="COMPENSATABLE",
        preview_summary="Create Meta campaign",
        idem_key="idem-create-meta-campaign-123"
    )
    
    # Seed Campaigns in local DB
    camp_g = Campaign(id="camp-google", tenant_id=tenant_id, brand_id=brand_id, name="Google Ads Campaign", platform="google-ads", status="active")
    camp_m = Campaign(id="camp-meta", tenant_id=tenant_id, brand_id=brand_id, name="Meta Ads Campaign", platform="meta-ads", status="active")
    
    # Seed Google and Meta Orders to simulate ROAS difference:
    # Google spend is 4000 INR (5000 budget * 0.8). Seed orders = 1000 INR -> Google ROAS = 0.25 (low)
    # Meta spend is 4000 INR (5000 budget * 0.8). Seed orders = 8000 INR -> Meta ROAS = 2.0 (high)
    order_g = Order(
        id="order-google", tenant_id=tenant_id, brand_id=brand_id, amount_minor=100000, currency="INR",
        attributed_campaign_id="camp-google", placed_at=dt.datetime.utcnow()
    )
    order_m = Order(
        id="order-meta", tenant_id=tenant_id, brand_id=brand_id, amount_minor=800000, currency="INR",
        attributed_campaign_id="camp-meta", placed_at=dt.datetime.utcnow()
    )
    
    session.add_all([tenant, brand, conn_google, conn_meta, op_g, op_m, camp_g, camp_m, order_g, order_m])
    await session.commit()

    # 3. Seed campaigns in MockMarketingClient
    mock_m_client = MockMarketingClient(provider="google-ads")
    mock_m_client.clear()
    await mock_m_client.create_campaign("camp-google", "Google Ads Campaign", budget_minor=500000, bid_minor=5000)
    
    mock_m_client_meta = MockMarketingClient(provider="meta-ads")
    await mock_m_client_meta.create_campaign("camp-meta", "Meta Ads Campaign", budget_minor=500000, bid_minor=5000)

    # 4. Trigger evaluate-trust task
    resp = await client.post("/tasks/evaluate-trust")
    assert resp.status_code == 200

    # 5. Verify that a grow.budget.reallocate Saga parent and two child updates were proposed!
    stmt_saga = select(OpRow).where(
        OpRow.tenant_id == tenant_id,
        OpRow.brand_id == brand_id,
        OpRow.action == "grow.budget.reallocate"
    )
    res_saga = await session.execute(stmt_saga)
    sagas = res_saga.scalars().all()
    assert len(sagas) == 1
    parent_saga = sagas[0]
    
    assert parent_saga.params["source_campaign_id"] == "camp-google"
    assert parent_saga.params["target_campaign_id"] == "camp-meta"
    assert parent_saga.params["transfer_amount_minor"] == 100000

    # Verify child operations
    stmt_children = select(OpRow).where(OpRow.parent_op_id == parent_saga.id).order_by(OpRow.sequence_order)
    res_children = await session.execute(stmt_children)
    children = res_children.scalars().all()
    assert len(children) == 2
    
    # Child 1: Decrease Google Ads budget
    assert children[0].action == "grow.campaign.update"
    assert children[0].params["campaign_id"] == "camp-google"
    assert children[0].params["budget_minor"] == 400000
    
    # Child 2: Increase Meta Ads budget
    assert children[1].action == "grow.campaign.update"
    assert children[1].params["campaign_id"] == "camp-meta"
    assert children[1].params["budget_minor"] == 600000

    # Clean up mock campaigns file
    mock_m_client.clear()


# --- TEST 60: REAL-WORLD DISASTER RECOVERY & DRIFT RECONCILIATION ---
@pytest.mark.asyncio
async def test_rw_disaster_recovery_backup_drift_reconciliation(client, session, mock_secrets_client):
    """Verify database backup and drift reconciliation flow using mock terraform drift simulation."""
    tenant_id = "dr-tenant"
    brand_id = "dr-brand"

    from app.models import Cadence
    import datetime as dt

    # 1. Seed tenant, brand, connection, and a DONE provisioned resource to check for drift
    tenant = Tenant(id=tenant_id, name="DR Tenant", gcp_project="dr-project")
    brand = Brand(id=brand_id, tenant_id=tenant_id, name="DR Brand")
    conn = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider="google-ads",
        credential="projects/dr-project/secrets/google-ads/versions/1",
        status="active"
    )
    op_provision = OpRow(
        id="prov-web-1",
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="provision",
        action="provision.web_host.create",
        params={"recipe": "web-host", "domain": "dr-brand.com"},
        state="DONE",
        impact=2,
        reversibility="COMPENSATABLE",
        preview_summary="Provision web host",
        idem_key="idem-provision-web-host-999"
    )
    cadence = Cadence(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="manage",
        action="manage.drift.detect",
        schedule="daily",
        status="on_track",
        next_run=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    )
    # Seed a TrustSnapshot with tier=2 for the manage domain to allow auto-approval of the drift check cadence
    from app.models import TrustSnapshot
    snapshot = TrustSnapshot(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="manage",
        tier=2,
        score=95.0,
        ts=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
    )
    session.add_all([tenant, brand, conn, op_provision, cadence, snapshot])
    await session.commit()

    # 2. Simulate out-of-band drift by setting the SIMULATE_DRIFT env var
    os.environ["SIMULATE_DRIFT"] = "1"
    try:
        # Commit seed session transaction
        await session.commit()

        # Trigger process cadences task which triggers drift detection
        resp = await client.post("/tasks/process-cadences")
        assert resp.status_code == 200

        # Run outbox drain loop to execute the proposed manage.drift.detect operation
        processed = await drain_once(session)
        assert processed > 0

        # 3. Verify that the drift detector identified the drift and proposed a provision.reconcile.apply Op
        stmt_rec = select(OpRow).where(
            OpRow.tenant_id == tenant_id,
            OpRow.brand_id == brand_id,
            OpRow.action == "provision.reconcile.apply"
        )
        res_rec = await session.execute(stmt_rec)
        reconcile_ops = res_rec.scalars().all()
        
        assert len(reconcile_ops) == 1
        assert reconcile_ops[0].state in ("PROPOSED", "AWAITING_APPROVAL", "APPROVED", "PENDING")
    finally:
        if "SIMULATE_DRIFT" in os.environ:
            del os.environ["SIMULATE_DRIFT"]


# --- TEST 61: REAL-WORLD COMPLIANCE GDPR PRIVACY AUDIT ---
@pytest.mark.asyncio
async def test_rw_compliance_gdpr_privacy_audit(client, session):
    """Verify cryptographic audit trail: append events, check compliance verify success, tamper with DB, and verify detection."""
    tenant_id = "comp-tenant"

    # 1. Append valid audit events forming a cryptographic hash chain
    ev1 = await audit_append(session, tenant_id=tenant_id, actor="operator", action="provision.web_host.create", op_id="op-1", payload={"domain": "comp.in"})
    ev2 = await audit_append(session, tenant_id=tenant_id, actor="optimizer", action="grow.campaign.update", op_id="op-2", payload={"budget": 100000})
    await session.commit()

    # 2. Verify that the cryptographic hash chain is fully intact and compliant
    resp = await client.get("/audit/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["first_bad_id"] is None

    # 3. Simulate out-of-band database tampering by modifying an event payload directly
    ev1.payload = {"domain": "tampered-domain.in"}
    await session.commit()

    # 4. Verify that the audit checker detects the breach and reports a broken hash chain
    resp_tampered = await client.get("/audit/verify")
    assert resp_tampered.status_code == 200
    data_tampered = resp_tampered.json()
    assert data_tampered["ok"] is False
    assert data_tampered["first_bad_id"] == ev1.id


# --- TEST 62: REAL-WORLD AGENTIC MCP TOOL EXECUTION GOVERNANCE ---
@pytest.mark.asyncio
async def test_rw_agentic_mcp_tool_execution_governance(client, session):
    """Verify that operations requiring PII consent are blocked, and pass only after explicit consent is granted."""
    tenant_id = "gov-tenant"
    brand_id = "gov-brand"

    # 1. Seed brand
    brand = Brand(id=brand_id, tenant_id=tenant_id, name="Gov Brand")
    session.add(brand)
    await session.commit()

    # Propose an operation requiring PII upload consent (action contains "audience")
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.audience.upload",
        params={"audience_id": "aud-123", "emails": ["user1@test.com", "user2@test.com"]},
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE)
    )
    row = await propose(session, op_spec, actor="agent")

    # 2. Evaluate the operation under Tier 1 (Supervised) or Tier 2 (Automatic)
    gate, requirement = await preview_and_gate(session, row, tier=2, actor="agent")
    
    # Assert that a Violation is flagged for missing consent basis
    assert len(gate.violations) == 1
    assert gate.violations[0].rule_id == "consent_gate"
    assert "Missing PII upload consent basis" in gate.violations[0].delta
    assert row.state == "BLOCKED"

    # 3. Grant consent using the governance adapter
    from app.adapters.governance import GovernanceAdapter
    gov_adapter = GovernanceAdapter()
    consent_op = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="governance",
        action="governance.consent.grant",
        params={"category": "pii_upload", "action_or_vendor": "grow.audience.upload", "actor": "owner"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    exec_res = await gov_adapter.execute(consent_op, idem_key="idem-consent-grant-123", session=session)
    assert exec_res.ok is True
    await session.commit()

    # 4. Re-evaluate the gated operation after consent is granted
    # First reset state to PROPOSED to allow re-gating transition
    row.state = "PROPOSED"
    gate_after, requirement_after = await preview_and_gate(session, row, tier=2, actor="agent")

    # Assert that the gate passes successfully without violations
    assert len(gate_after.violations) == 0
    assert row.state in ("APPROVED", "PENDING")
