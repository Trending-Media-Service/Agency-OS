import os
os.environ["ENV"] = "test"
os.environ["AOS_ENV"] = "test"
os.environ["AOS_STATE_BUCKET"] = "mock-test-bucket"

import asyncio
import sys
from fastapi.testclient import TestClient
from sqlalchemy import select

# Add parent directory to path to import app
sys.path.append(".")

from app.main import app, verify_operator_auth, resolved_operator_role
from app.models import Base, Tenant, Brand, OpRow, make_engine, make_session_factory
from app.database import get_db

async def run_verification():
    print("=== Starting Manual Security Verification ===")
    
    # 1. Setup async in-memory database for testing
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    # Initialize tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
    # Override get_db to use our clean in-memory session
    async def override_get_db():
        async with session_factory() as session:
            await session.begin()
            try:
                yield session
                if session.in_transaction():
                    await session.commit()
            except Exception:
                if session.in_transaction():
                    await session.rollback()
                raise
                
    app.dependency_overrides[get_db] = override_get_db
    
    # Also override worker db dependencies for in-memory execution
    from app.database import get_worker_db, get_worker_session_maker
    app.dependency_overrides[get_worker_db] = override_get_db
    
    async def override_get_worker_session_maker():
        return session_factory
    app.dependency_overrides[get_worker_session_maker] = override_get_worker_session_maker
    
    # Override the app state db_session_maker for the middleware to use SQLite!
    app.state.db_session_maker = session_factory
    # Enable tenant validation for manual verification
    app.state.bypass_tenant_validation = False
    
    # 2. STRICT SECURITY: Remove the test overrides to simulate real production auth
    if verify_operator_auth in app.dependency_overrides:
        del app.dependency_overrides[verify_operator_auth]
    if resolved_operator_role in app.dependency_overrides:
        del app.dependency_overrides[resolved_operator_role]
        
    client = TestClient(app)
    
    # 3. Seed initial Tenant and Brand
    # Since POST /tenants is operator-gated, we must pass the correct Bearer token
    print("[Seed] Creating tenant...")
    res = client.post(
        "/tenants",
        headers={"Authorization": "Bearer default-dev-token"},
        json={"name": "Secure Corp", "brand_name": "Secure Brand"}
    )
    assert res.status_code == 200, f"Failed to seed tenant: {res.text}"
    tid = res.json()["tenant_id"]
    bid = res.json()["brand_id"]
    print(f"[Seed] Seeded tenant={tid}, brand={bid}")
    
    H = {"X-Tenant-ID": tid}
    OP_H = {**H, "Authorization": "Bearer default-dev-token"}
    
    # 4. Propose a provision Op (requires owner/operator approval, high-risk)
    # We will propose it by hitting /intents
    print("[Seed] Proposing high-risk provision Op...")
    res = client.post("/intents", headers=H, json={"brand_id": bid, "text": "host secure.in please"})
    assert res.status_code == 200, f"Failed to propose: {res.text}"
    prov_op_id = res.json()["cards"][0]["op_id"]
    print(f"[Seed] Proposed provision op={prov_op_id}")
    
    # Propose a low-risk grow Op (CLIENT is allowed to approve)
    print("[Seed] Proposing low-risk grow Op...")
    res = client.post("/intents", headers=H, json={"brand_id": bid, "text": "optimize bids grow please"})
    assert res.status_code == 200
    grow_op_id = res.json()["cards"][0]["op_id"]
    print(f"[Seed] Proposed grow op={grow_op_id}")
    
    # Let's adjust grow_op properties in the DB to ensure it matches client thresholds
    # (impact <= 2, cost <= 10,000, domain='grow')
    async with session_factory() as session:
        # Move grow op to AWAITING_APPROVAL and ensure it is grow domain, low impact
        grow_row = await session.get(OpRow, grow_op_id)
        grow_row.domain = "grow"
        grow_row.action = "grow_campaign_optimize"
        grow_row.impact = 2
        grow_row.cost_amount_minor = 50_000 # 500 INR
        grow_row.state = "AWAITING_APPROVAL"
        
        # Ensure provision op is provision domain, high impact (5)
        prov_row = await session.get(OpRow, prov_op_id)
        prov_row.domain = "provision"
        prov_row.impact = 5
        prov_row.state = "AWAITING_APPROVAL"
        
        await session.commit()
        
    print("\n--- Running Test Cases ---")
    
    # ----------------------------------------------------
    # TEST 1: Direct Action Blocked
    # ----------------------------------------------------
    print("\n[Test 1] POST /actions without token...")
    res = client.post(
        "/actions",
        headers=H,
        json={"tool": "grow_google_ads_connect", "brand_id": bid, "params": {}}
    )
    print(f"Status Code: {res.status_code}")
    assert res.status_code == 401, "Expected 401 Unauthorized for direct action without token"
    print("=> SUCCESS: Direct action without token was blocked with 401.")
    
    # ----------------------------------------------------
    # TEST 2: Masquerade Blocked
    # ----------------------------------------------------
    print("\n[Test 2] Client tries to masquerade as AGENCY_OWNER without token...")
    res = client.post(
        f"/ops/{prov_op_id}/decision",
        headers=H,
        json={
            "decision": "approve",
            "actor": "malicious_client",
            "role": "AGENCY_OWNER", # Claiming owner but sending no token!
            "surface": "web",
            "reason": "Masquerade attempt"
        }
    )
    print(f"Status Code: {res.status_code}")
    print(f"Response Body: {res.json()}")
    assert res.status_code == 403, "Expected 403 Forbidden for masquerade attempt"
    assert "CLIENT cannot approve provision Ops" in res.json()["detail"], "Expected forced CLIENT role rejection"
    print("=> SUCCESS: Masquerading was blocked. The role was correctly forced to CLIENT and rejected.")
    
    # ----------------------------------------------------
    # TEST 3: Operator Approved
    # ----------------------------------------------------
    print("\n[Test 3] Operator approves provision Op with valid Bearer token...")
    res = client.post(
        f"/ops/{prov_op_id}/decision",
        headers=OP_H,
        json={
            "decision": "approve",
            "actor": "owner_chandan",
            "role": "AGENCY_OWNER",
            "surface": "web",
            "reason": "Authorized owner approval"
        }
    )
    print(f"Status Code: {res.status_code}")
    print(f"Response Body: {res.json()}")
    assert res.status_code == 200, "Expected 200 OK for authorized owner approval"
    assert res.json()["state"] == "APPROVED", "Expected state to transition to APPROVED"
    print("=> SUCCESS: Authorized operator was allowed to approve.")
    
    # ----------------------------------------------------
    # TEST 4: Client Self-Approve
    # ----------------------------------------------------
    print("\n[Test 4] Tenant Client self-approves low-risk grow Op without token...")
    res = client.post(
        f"/ops/{grow_op_id}/decision",
        headers=H, # No token!
        json={
            "decision": "approve",
            "actor": "client_user",
            "role": "CLIENT", # Claiming client
            "surface": "web",
            "reason": "Self-approving marketing budget tweak"
        }
    )
    print(f"Status Code: {res.status_code}")
    print(f"Response Body: {res.json()}")
    assert res.status_code == 200, "Expected 200 OK for valid client self-approval"
    assert res.json()["state"] == "APPROVED", "Expected state to transition to APPROVED"
    print("=> SUCCESS: Tenant client successfully self-approved a low-risk operation.")
    
    # ----------------------------------------------------
    # TEST 5: Shadow Tenant Blocked
    # ----------------------------------------------------
    print("\n[Test 5] Request with unregistered X-Tenant-ID...")
    from app.middleware import VALID_TENANTS_CACHE
    VALID_TENANTS_CACHE.clear()
    
    res = client.get(
        "/actions/catalog",
        headers={"X-Tenant-ID": "shadow-tenant-999"}
    )
    print(f"Status Code: {res.status_code}")
    print(f"Response Body: {res.json()}")
    assert res.status_code == 401, "Expected 401 Unauthorized for unregistered tenant"
    assert res.json()["detail"] == "Unauthorized: Tenant not registered.", "Expected unregistered tenant detail"
    print("=> SUCCESS: Shadow Tenant was correctly validation-blocked and rejected.")
    
    print("\n=== All Manual Security Verifications Passed! ===")

if __name__ == "__main__":
    # Run the async verification function in a clean event loop
    asyncio.run(run_verification())
