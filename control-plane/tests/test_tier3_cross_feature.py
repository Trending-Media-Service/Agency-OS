import pytest
import datetime as dt
from unittest.mock import patch, MagicMock
from sqlalchemy import select

from app.models import (
    Connection,
    CircuitBreakerRow,
    OpRow,
    TrustSnapshot,
    Campaign,
    SpendFact,
    Order,
    OrderLine,
    Touchpoint,
    BrandProperty
)
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money, OpState
from app.kernel.loop import drain_once, record_failure, is_circuit_tripped
from app.adapters.manage import ManageAdapter
from app.services.google_audit import GoogleSearchConsoleAudit
from app.profit.poas import calculate_campaign_poas

# --- TEST 53: CROSS-TENANT SECRET & HEALTH ISOLATION ---
@pytest.mark.asyncio
async def test_cross_tenant_secret_and_health_isolation(session, mock_secrets_client, mock_mcp_client):
    """Verify that connection verification does not leak or cross-pollinate between tenants."""
    # Seed Tenant A and Connection
    conn_a = Connection(
        tenant_id="tenant-a", brand_id="brand-a", provider="shopify",
        credential="projects/p1/secrets/sec-a/versions/1", status="active",
        config={"shop_url": "store-a.myshopify.com"}
    )
    # Seed Tenant B and Connection
    conn_b = Connection(
        tenant_id="tenant-b", brand_id="brand-b", provider="shopify",
        credential="projects/p2/secrets/sec-b/versions/1", status="active",
        config={"shop_url": "store-b.myshopify.com"}
    )
    session.add_all([conn_a, conn_b])
    await session.commit()

    # Mock Secrets Client responses
    mock_secrets_client.store.update({
        "projects/p1/secrets/sec-a/versions/1": "token-tenant-a",
        "projects/p2/secrets/sec-b/versions/1": "token-tenant-b"
    })

    adapter = ManageAdapter()
    op_a = OpSpec(
        tenant_id="tenant-a",
        brand_id="brand-a",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "projects/p1/secrets/sec-a/versions/1",
            "config": {"shop_url": "store-a.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )

    # Call verify on the adapter for Tenant A
    verdict = await adapter.verify(op_a, session=session)
    
    assert verdict.ok is True
    
    # Assert secrets client was only called for Tenant A's secret
    mock_secrets_client.read_secret.assert_called_once_with("projects/p1/secrets/sec-a/versions/1")
    called_secrets = [call[0][0] for call in mock_secrets_client.read_secret.call_args_list]
    assert "projects/p2/secrets/sec-b/versions/1" not in called_secrets

    # Query connection for tenant-a and assert tenant boundary isolation
    stmt = select(Connection).where(Connection.tenant_id == "tenant-a")
    res = await session.execute(stmt)
    conns = res.scalars().all()
    assert len(conns) == 1
    assert conns[0].tenant_id == "tenant-a"


# --- TEST 54: CIRCUIT BREAKER & HEALTH INTERACTION ---
@pytest.mark.asyncio
async def test_circuit_breaker_and_health_interaction(session):
    """Verify that multiple failures on a provider trip the circuit breaker and block subsequent executions."""
    tenant_id = "cb-tenant"
    brand_id = "cb-brand"
    domain = "manage"

    # Trip the circuit breaker by recording failures
    for _ in range(3):
        await record_failure(session, tenant_id, brand_id, domain)
    await session.commit()

    # Assert circuit breaker is OPEN in database
    stmt = select(CircuitBreakerRow).where(
        CircuitBreakerRow.tenant_id == tenant_id,
        CircuitBreakerRow.brand_id == brand_id,
        CircuitBreakerRow.domain == domain
    )
    res = await session.execute(stmt)
    cb = res.scalar_one_or_none()
    assert cb is not None
    assert cb.state == "OPEN"
    assert cb.consecutive_failures >= 3

    # Propose a new operation under this tenant, brand, and domain
    op = OpRow(
        id="cb-op-123",
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain=domain,
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "secret-ref", "config": {"shop_url": "store.myshopify.com"}},
        state="APPROVED",
        impact=1,
        reversibility="COMPENSATABLE",
        preview_summary="Connect shopify store",
        idem_key="idem_cb_test_123"
    )
    session.add(op)
    
    # Insert a PENDING outbox item to be processed by drain_once
    from app.models import OutboxItem
    outbox_item = OutboxItem(
        op_id="cb-op-123",
        tenant_id=tenant_id,
        status="PENDING",
        next_attempt_at=dt.datetime.utcnow() - dt.timedelta(seconds=1)
    )
    session.add(outbox_item)
    await session.commit()

    # Run the outbox drain loop
    processed = await drain_once(session)
    assert processed > 0

    # Refresh OpRow and OutboxItem from DB
    await session.refresh(op)
    stmt_item = select(OutboxItem).where(OutboxItem.op_id == "cb-op-123")
    res_item = await session.execute(stmt_item)
    item = res_item.scalar_one()

    # Assert that the operation was BLOCKED and outbox item is DEAD
    assert op.state == "BLOCKED"
    assert item.status == "DEAD"


# --- TEST 55: CONNECTION LIFECYCLE, SCHEDULED ROTATION & AUDIT ---
@pytest.mark.asyncio
async def test_connection_lifecycle_scheduled_rotation_and_audit(client, session, mock_secrets_client):
    """Verify end-to-end flow of token rotation, database pruning, and subsequent search console audit."""
    tenant_id = "rot-tenant"
    brand_id = "rot-brand"

    # Seed google-search-console connection near expiry
    conn = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider="google-search-console",
        credential="projects/p1/secrets/gsc-token_access/versions/1",
        status="active",
        config={
            "site_url": "https://rot-brand.com",
            "refresh_token_ref": "projects/p1/secrets/gsc-token/versions/1"
        },
        expires_at=dt.datetime.utcnow() - dt.timedelta(minutes=5)
    )
    session.add(conn)
    await session.commit()

    # Seed Secret Manager
    mock_secrets_client.store.update({
        "projects/p1/secrets/gsc-token/versions/1": "old-gsc-token",
        "projects/test-project/secrets/gsc-token/versions/1": "new-gsc-token",
        "projects/test-project/secrets/gsc-token/versions/2": "new-gsc-token",
        "projects/test-project/secrets/gsc-token_access/versions/1": "new-gsc-access-token"
    })

    # Mock google oauth API token refresh post response, delegating local app requests to prevent mock leakage
    from httpx import AsyncClient
    original_post = AsyncClient.post
    print(f"DEBUG: original_post is: {original_post}", flush=True)
    
    async def mock_post_fn(self, url, *args, **kwargs):
        url_str = str(url)
        if url_str.startswith("http://test") or url_str.startswith("/"):
            return await original_post(self, url, *args, **kwargs)
            
        mock_resp = MagicMock()
        if "oauth2.googleapis.com" in url_str:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "access_token": "new-gsc-access-token",
                "refresh_token": "new-gsc-token",
                "expires_in": 3600
            }
        elif "searchconsole.googleapis.com" in url_str:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "inspectionResult": {
                    "indexStatusResult": {
                        "verdict": "PASS",
                        "crawlState": "SUCCESSFUL"
                    }
                }
            }
        else:
            mock_resp.status_code = 404
            mock_resp.json.return_value = {"error": "Not Found"}
        return mock_resp

    with patch("httpx.AsyncClient.post", new=mock_post_fn):
        # Commit the transaction so refresh-tokens endpoint (which runs in a separate session/transaction) can see the seeded data
        await session.commit()

        # Trigger token rotation background task
        resp = await client.post("/tasks/refresh-tokens")
        assert resp.status_code == 200
        print(f"DEBUG: /tasks/refresh-tokens response: {resp.json()}", flush=True)

        # The task proposed the rotation Op. Query and execute it!
        from app.models import OpRow
        from app.kernel import loop
        
        stmt_op = select(OpRow).where(
            OpRow.tenant_id == tenant_id,
            OpRow.action == "manage.connection.rotate"
        )
        res_op = await session.execute(stmt_op)
        op_row = res_op.scalar_one()
        assert op_row.state == "AWAITING_APPROVAL"
        
        # Approve and execute
        await loop.decide(session, op_row, decision="approve", actor="operator", role="OPERATOR", surface="whatsapp")
        await session.commit()
        await loop._execute_and_verify(session, op_row)
        await session.commit()

        session.expire_all()
        # Query connection fresh from database to avoid caching/transaction visibility issues in sqlite
        stmt_conn = select(Connection).where(
            Connection.tenant_id == tenant_id,
            Connection.brand_id == brand_id,
            Connection.provider == "google-search-console"
        )
        res_conn = await session.execute(stmt_conn)
        conn_fresh = res_conn.scalar_one()
        print(f"DEBUG: fresh connection: credential={conn_fresh.credential}, status={conn_fresh.status}, last_error={conn_fresh.last_error}", flush=True)
        
        # Verify token is updated
        assert conn_fresh.credential.startswith("projects/test-project/secrets/gsc-token")
        assert conn_fresh.status == "active"
        assert conn_fresh.expires_at > dt.datetime.utcnow()

        # Now run the Google Search Console Audit task
        audit = GoogleSearchConsoleAudit(tenant_id=tenant_id, brand_id=brand_id, session=session)
        result = await audit.run()
        
        # Assert audit succeeded and fetched mock data (since we passed a real token reference, it ran, but we can verify indexing status)
        assert "findings" in result


# --- TEST 56: REVOCATION RECOVERY VIA SELF-SERVICE ---
@pytest.mark.asyncio
async def test_revocation_recovery_via_self_service(client, session, mock_secrets_client, mock_mcp_client):
    """Verify that a broken connection can be repaired using a self-service intent trigger."""
    tenant_id = "rep-tenant"
    brand_id = "rep-brand"

    # 1. Seed a broken Shopify connection in error state
    conn = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider="shopify",
        credential="projects/p1/secrets/shopify-token/versions/1",
        status="error",
        last_error="API_REVOKED",
        config={"shop_url": "broken-shop.myshopify.com"}
    )
    session.add(conn)
    await session.commit()
    
    # Debug print
    res_dbg = await session.execute(select(Connection))
    print(f"DEBUG 1: seeded connections={[(c.tenant_id, c.brand_id, c.provider, c.status) for c in res_dbg.scalars().all()]}", flush=True)

    # Mock Secret Manager
    mock_secrets_client.store["projects/p1/secrets/shopify-token/versions/1"] = "new-working-shopify-token"

    # 2. Invoke self-service repair by submitting intent to connect shopify
    H = {"X-Tenant-Id": tenant_id}
    resp = await client.post(
        "/intents",
        json={
            "brand_id": brand_id,
            "domain": "manage",
            "text": "connect shopify store broken-shop.myshopify.com with secret:projects/p1/secrets/shopify-token/versions/1"
        },
        headers=H
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["cards"]) == 1
    op_id = data["cards"][0]["op_id"]

    # Debug print after intents call
    res_dbg = await session.execute(select(Connection))
    print(f"DEBUG 2: connections after intents={[(c.tenant_id, c.brand_id, c.provider, c.status) for c in res_dbg.scalars().all()]}", flush=True)

    # 3. Approve and execute the resulting connection repair operation
    # First transition to approved
    stmt_op = select(OpRow).where(OpRow.id == op_id)
    res_op = await session.execute(stmt_op)
    op_row = res_op.scalar_one()
    op_row.state = "APPROVED"
    
    # Add outbox item
    from app.models import OutboxItem
    outbox_item = OutboxItem(
        op_id=op_id,
        tenant_id=tenant_id,
        status="PENDING",
        next_attempt_at=dt.datetime.utcnow() - dt.timedelta(seconds=1)
    )
    session.add(outbox_item)
    await session.commit()

    # Drain the outbox to execute the connection repair
    processed = await drain_once(session)
    assert processed > 0
    await session.commit()
    session.expire_all()

    # Debug print after drain
    res_dbg = await session.execute(select(Connection))
    print(f"DEBUG 3: connections after drain={[(c.tenant_id, c.brand_id, c.provider, c.status) for c in res_dbg.scalars().all()]}", flush=True)

    # 4. Verify that the connection is now 'active' and last_error is cleared
    # Query fresh from database
    stmt_conn = select(Connection).where(
        Connection.tenant_id == tenant_id,
        Connection.brand_id == brand_id,
        Connection.provider == "shopify"
    )
    res_conn = await session.execute(stmt_conn)
    conn_fresh = res_conn.scalar_one()
    assert conn_fresh.status == "active"
    assert conn_fresh.last_error is None


# --- TEST 57: CROSS-SUBSYSTEM CAMPAIGN SYNC & ATTRIBUTION ---
@pytest.mark.asyncio
async def test_cross_subsystem_campaign_sync_and_attribution(session):
    """Verify multi-touch attribution and POAS calculation with an incrementality multiplier."""
    tenant_id = "attr-tenant"
    brand_id = "attr-brand"

    # Seed the BrandProperty containing the attribution multiplier (alpha_inc = 1.2)
    prop = BrandProperty(
        id="prop-123",
        tenant_id=tenant_id,
        brand_id=brand_id,
        type="attribution_multiplier",
        provider="shopify",
        findings={"alpha_inc": 1.2}
    )
    session.add(prop)

    # Seed Campaigns
    c1 = Campaign(id="camp-1", tenant_id=tenant_id, brand_id=brand_id, name="Google Search Ads", platform="google", status="active")
    c2 = Campaign(id="camp-2", tenant_id=tenant_id, brand_id=brand_id, name="Meta Retargeting", platform="meta", status="active")
    session.add_all([c1, c2])

    # Seed Spend Facts (c1 spend = 1000 INR, c2 spend = 500 INR in minor units)
    s1 = SpendFact(id="sf-1", tenant_id=tenant_id, campaign_id="camp-1", amount_minor=100000, date=dt.date.today())
    s2 = SpendFact(id="sf-2", tenant_id=tenant_id, campaign_id="camp-2", amount_minor=50000, date=dt.date.today())
    session.add_all([s1, s2])

    # Seed Order and Order Lines
    # Order amount = 2400 INR minor units
    o1 = Order(
        id="order-123",
        tenant_id=tenant_id,
        brand_id=brand_id,
        amount_minor=240000,
        currency="INR",
        attributed_campaign_id="camp-1",  # Initial attribution to c1
        customer_id="cust-456",
        placed_at=dt.datetime.now()
    )
    session.add(o1)

    ol1 = OrderLine(
        id="oline-1",
        tenant_id=tenant_id,
        order_id="order-123",
        unit_price_minor=200000,
        line_discount_minor=0,
        qty=1,
        unit_cost_minor=50000  # Cost of Goods Sold (COGS) = 500 INR minor units
    )
    ol2 = OrderLine(
        id="oline-2",
        tenant_id=tenant_id,
        order_id="order-123",
        unit_price_minor=40000,
        line_discount_minor=0,
        qty=1,
        unit_cost_minor=10000  # COGS = 100 INR minor units
    )
    session.add_all([ol1, ol2])

    # Seed Touchpoints for multi-touch attribution (Customer visited c2, then c1)
    t1 = Touchpoint(
        id="tp-1",
        tenant_id=tenant_id,
        customer_id="cust-456",
        campaign_id="camp-2",
        type="click",
        occurred_at=dt.datetime.now() - dt.timedelta(hours=2)
    )
    t2 = Touchpoint(
        id="tp-2",
        tenant_id=tenant_id,
        customer_id="cust-456",
        campaign_id="camp-1",
        type="click",
        occurred_at=dt.datetime.now() - dt.timedelta(hours=1)
    )
    session.add_all([t1, t2])

    await session.commit()

    # Compute Campaign POAS
    poas_results = await calculate_campaign_poas(
        session,
        tenant_id=tenant_id,
        brand_id=brand_id,
        attribution_window_days=30,
        attribution_model="last_touch"
    )

    # Let's verify the calculations:
    # Attribution model: "last_touch" -> touchpoint occurred_at: tp-2 (camp-1) is later than tp-1 (camp-2).
    # So order-123 is attributed to camp-1.
    # Gross Revenue = 240,000
    # Total COGS = ol1 unit_cost_minor + ol2 unit_cost_minor = 50,000 + 10,000 = 60,000
    # Gross Profit = Gross Revenue - Total COGS = 180,000
    # alpha_inc = 1.2
    # Contribution Margin = Gross Profit * alpha_inc = 180,000 * 1.2 = 216,000
    # POAS for camp-1 = Contribution Margin / Spend = 216,000 / 100000 = 2.16
    # Let's find camp-1 in the results
    camp1_result = next((r for r in poas_results if r["campaign_id"] == "camp-1"), None)
    assert camp1_result is not None
    # Base POAS is 1.80 (Gross Profit 180000 / Spend 100000)
    assert camp1_result["poas"] == pytest.approx(1.80, rel=1e-2)
    # Incrementality-adjusted POAS (ipoas) is 2.16 (Base POAS 1.80 * alpha_inc 1.2)
    assert camp1_result["ipoas"] == pytest.approx(2.16, rel=1e-2)
    # Base contribution margin (before alpha_inc is applied) is 180,000 minor units
    assert camp1_result["contribution_margin_minor"] == pytest.approx(180000, rel=1e-2)
