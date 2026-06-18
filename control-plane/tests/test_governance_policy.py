import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import Tenant, Brand, OpRow, PolicyVersion, TrustSnapshot
from app.kernel import loop
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.mark.asyncio
async def test_policy_update_flow(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Gov Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Gov")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # 2. Seed a TrustSnapshot as Tier 2 to allow auto-approvals
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id=tenant_id, brand_id=brand_id, domain="provision", score=90.0, tier=2))
        s.add(TrustSnapshot(tenant_id=tenant_id, brand_id=brand_id, domain="governance", score=90.0, tier=2))
        await s.commit()

    # 3. Seed an initial active PolicyVersion with a low cost ceiling (100 INR = 10_000 minor)
    async with async_session() as s:
        initial_policy = PolicyVersion(
            tenant_id=tenant_id,
            version=1,
            status="active",
            params={"provision_cost_ceiling_minor": 10_000}
        )
        s.add(initial_policy)
        await s.commit()

    # 4. Propose a Provision Op that exceeds this ceiling (150 INR = 15_000 minor)
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="provision",
        action="provision.web_host.create",
        params={"domain": "test.in"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(15_000) # 150 INR
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="test")
        await s.commit()
        op_id = row.id

    # Verify it is blocked
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        gate, req = await loop.preview_and_gate(s, db_row, tier=2)
        await s.commit()
        assert req == "BLOCKED"
        assert db_row.state == "BLOCKED"

    # 5. Plan Policy Update Op to raise ceiling to 200 INR (20_000 minor)
    resp_plan = await client.post("/intents", headers=H, json={
        "domain": "governance",
        "brand_id": brand_id,
        "text": "update policy ceiling to 20000"
    })
    assert resp_plan.status_code == 200
    data = resp_plan.json()
    assert len(data["cards"]) == 1
    update_op_id = data["cards"][0]["op_id"]

    # 6. Approve the Policy Update Op
    resp_dec = await client.post(f"/ops/{update_op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp",
        "reason": "raising ceiling"
    })
    assert resp_dec.status_code == 200

    # 7. Verify the new PolicyVersion is active and the old one is superseded
    async with async_session() as s:
        res = await s.execute(select(PolicyVersion).where(PolicyVersion.tenant_id == tenant_id).order_by(PolicyVersion.version.asc()))
        policies = res.scalars().all()
        
        assert len(policies) == 2
        assert policies[0].version == 1
        assert policies[0].status == "superseded"
        
        assert policies[1].version == 2
        assert policies[1].status == "active"
        assert policies[1].params["provision_cost_ceiling_minor"] == 20_000

    # 8. Re-propose and verify it now passes
    op_spec_2 = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="provision",
        action="provision.web_host.create",
        params={"domain": "test2.in"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(15_000) # 150 INR
    )

    async with async_session() as s:
        row2 = await loop.propose(s, op_spec_2, actor="test")
        await s.commit()
        op_id_2 = row2.id

    async with async_session() as s:
        db_row2 = await s.get(OpRow, op_id_2)
        gate2, req2 = await loop.preview_and_gate(s, db_row2, tier=2)
        await s.commit()
        assert req2 == "AUTO"
        assert db_row2.state == "APPROVED"


@pytest.mark.asyncio
async def test_dynamic_trust_config_evaluation(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.kernel.services import compute_snapshots
    from app.models import TrustSnapshot
    
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Trust Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Trust")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    # 2. Seed an active PolicyVersion with a custom trust_config
    custom_trust_config = {
        "health_weights": {"gtm_present": 50.0, "pixel_present": 0.0, "capi_dedup_rate": 0.0},
        "penalties": {
            "gmc_critical_mismatches": {"p_max": 25.0, "tau": 5.0},
            "reputation_alerts": {"p_max": 20.0, "tau": 2.0},
        },
        "history": {
            "deltas": {"verified_success": +1.0, "override": -5.0, "verify_failure": -8.0, "rejection": -2.0},
            "half_life_days": 45.0,
            "clamp": 30.0,
        },
        "tiers": {"lockout_below": 40.0, "autonomy_at": 50.0},
    }

    async with async_session() as s:
        policy = PolicyVersion(
            tenant_id=tenant_id,
            version=1,
            status="active",
            params={
                "provision_cost_ceiling_minor": 100_000,
                "trust_config": custom_trust_config
            }
        )
        s.add(policy)
        await s.commit()

    # 3. Run compute_snapshots
    async with async_session() as s:
        await compute_snapshots(s)
        await s.commit()

    # 4. Fetch the generated snapshot and assert it matches the custom config calculation!
    async with async_session() as s:
        res = await s.execute(
            select(TrustSnapshot).where(
                TrustSnapshot.tenant_id == tenant_id,
                TrustSnapshot.brand_id == brand_id,
                TrustSnapshot.domain == "provision"
            )
        )
        snapshot = res.scalar_one_or_none()
        assert snapshot is not None
        assert snapshot.score == 50.0
        assert snapshot.tier == 2
