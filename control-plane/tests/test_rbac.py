import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.models import OpRow, Tenant
from app.kernel.optypes import OpState

@pytest.mark.asyncio
async def test_rbac_enforcement_cases(client: AsyncClient, session):
    # 1. Create tenant
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid = r.json()["tenant_id"]
    bid = r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    # 2. Propose Op
    r = await client.post("/intents", headers=H, json={"brand_id": bid, "text": "host woktok.in please"})
    op_id = r.json()["cards"][0]["op_id"]

    # Fetch and update Op to different test scenarios
    async def set_op_properties(impact: int, cost_minor: int, domain: str, statutory: bool, reversibility: str):
        row = await session.get(OpRow, op_id)
        row.impact = impact
        row.reversibility = reversibility
        row.cost_amount_minor = cost_minor
        row.domain = domain
        row.statutory = statutory
        row.state = "AWAITING_APPROVAL"
        await session.commit()

    # --- Scenario A: OPERATOR tries to approve HIGH impact (5) Op
    await set_op_properties(impact=5, cost_minor=50_000, domain="provision", statutory=False, reversibility="REVERSIBLE")
    res = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "op_bob",
        "role": "OPERATOR",
        "surface": "whatsapp",
        "reason": "Deploying standard host"
    })
    assert res.status_code == 403
    assert "OPERATOR cannot approve Ops with severity impact 5" in res.json()["detail"]

    # --- Scenario B: CLIENT tries to approve statutory Op
    await set_op_properties(impact=2, cost_minor=50_000, domain="grow", statutory=True, reversibility="REVERSIBLE")
    res = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "client_alice",
        "role": "CLIENT",
        "surface": "web",
        "reason": "Authorized"
    })
    assert res.status_code == 403
    assert "CLIENT cannot approve statutory Ops" in res.json()["detail"]

    # --- Scenario C: BRAND_VIEWER tries to approve provision Op
    await set_op_properties(impact=1, cost_minor=0, domain="provision", statutory=False, reversibility="REVERSIBLE")
    res = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "viewer_charlie",
        "role": "BRAND_VIEWER",
        "surface": "web",
        "reason": "View check"
    })
    assert res.status_code == 403
    assert "BRAND_VIEWER cannot approve provision Ops" in res.json()["detail"]

    # --- Scenario D: CLIENT tries to approve Op exceeding cost limit (10,000 INR = 1,000,000 minor units)
    # Let's set cost to 12,000 INR = 1,200,000 minor units
    await set_op_properties(impact=2, cost_minor=1_200_000, domain="grow", statutory=False, reversibility="REVERSIBLE")
    res = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "client_alice",
        "role": "CLIENT",
        "surface": "web",
        "reason": "Approve expensive Grow"
    })
    assert res.status_code == 403
    assert "CLIENT cannot approve Ops costing 12000.00 INR (max allowed 10000.00 INR)" in res.json()["detail"]

    # --- Scenario E: CLIENT tries to approve IRREVERSIBLE Op
    await set_op_properties(impact=2, cost_minor=50_000, domain="grow", statutory=False, reversibility="IRREVERSIBLE")
    res = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "client_alice",
        "role": "CLIENT",
        "surface": "web",
        "reason": "Approve irreversible Grow"
    })
    assert res.status_code == 403
    assert "CLIENT cannot approve IRREVERSIBLE Ops" in res.json()["detail"]

    # --- Scenario F: AGENCY_OWNER approves HIGH impact (5) statutory irreversible Op (succeeds)
    await set_op_properties(impact=5, cost_minor=5_000_000, domain="provision", statutory=True, reversibility="IRREVERSIBLE")
    res = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "owner_dave",
        "role": "AGENCY_OWNER",
        "surface": "whatsapp",
        "reason": "Override statutory high-risk baseline"
    })
    assert res.status_code == 200
    assert res.json()["state"] == "APPROVED"


@pytest.mark.asyncio
async def test_operator_authentication_enforcement(client: AsyncClient):
    import app.main as mainmod
    from app.main import verify_operator_auth

    # 1. Remove the override temporarily
    if verify_operator_auth in mainmod.app.dependency_overrides:
        del mainmod.app.dependency_overrides[verify_operator_auth]

    try:
        # 2. GET /tenants without header -> 401
        res = await client.get("/tenants")
        assert res.status_code == 401
        assert "Missing or invalid Authorization header" in res.json()["detail"]

        # 3. GET /tenants with invalid Bearer token -> 403
        res = await client.get("/tenants", headers={"Authorization": "Bearer wrong-token"})
        assert res.status_code == 403
        assert "Forbidden: Invalid operator token" in res.json()["detail"]

        # 4. GET /tenants with valid Bearer token -> 200
        res = await client.get("/tenants", headers={"Authorization": "Bearer default-dev-token"})
        assert res.status_code == 200
        assert isinstance(res.json(), list)
        
        # 5. POST /tenants without header -> 401
        res = await client.post("/tenants", json={"name": "New Tenant", "brand_name": "New Brand"})
        assert res.status_code == 401
        
        # 6. POST /tenants with valid Bearer token -> 200
        res = await client.post(
            "/tenants", 
            headers={"Authorization": "Bearer default-dev-token"},
            json={"name": "New Tenant", "brand_name": "New Brand"}
        )
        assert res.status_code == 200
        assert "tenant_id" in res.json()

    finally:
        # 7. Restore override to prevent leaking to other tests
        mainmod.app.dependency_overrides[verify_operator_auth] = lambda: None
