import pytest
from sqlalchemy import select
from app.models import OpRow, TrustSnapshot, PolicyVersion, AuditEvent, OutboxItem
from app.kernel.services import audit_append

@pytest.mark.asyncio
async def test_policy_simulation_correctness_and_readonly(client, session):
    # 1. Setup tenant and brand
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert resp.status_code == 200
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]

    # 2. Seed active baseline PolicyVersion with cost ceiling = 100 INR (10_000 paise)
    baseline_policy = PolicyVersion(
        tenant_id=tid,
        version=1,
        status="active",
        params={
            "provision_cost_ceiling_minor": 10_000,
            "grow_bid_cap_minor": 5_000
        }
    )
    session.add(baseline_policy)

    # 3. Seed TrustSnapshot as Tier 2 to allow auto-approvals
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="provision", score=90.0, tier=2))

    # 4. Seed historical operations:
    # A: Within ceiling (50 INR) -> Should be AUTO under baseline, and AUTO under proposed. (No move)
    op_within = OpRow(
        id="op_within_123",
        tenant_id=tid,
        brand_id=bid,
        domain="provision",
        action="provision.web_host.create",
        state="DONE",
        impact=1,
        reversibility="COMPENSATABLE",
        statutory=False,
        cost_amount_minor=5_000,
        cost_currency="INR",
        idem_key="idem_within"
    )
    # B: Exceeds ceiling (150 INR) -> Should be BLOCKED under baseline, and AUTO under proposed (ceiling raised to 200 INR). (newly_allowed)
    op_above = OpRow(
        id="op_above_123",
        tenant_id=tid,
        brand_id=bid,
        domain="provision",
        action="provision.web_host.create",
        state="BLOCKED",
        impact=1,
        reversibility="COMPENSATABLE",
        statutory=False,
        cost_amount_minor=15_000,
        cost_currency="INR",
        idem_key="idem_above"
    )
    session.add(op_within)
    session.add(op_above)

    # Create dummy audit log to have a head hash
    await audit_append(session, tenant_id=tid, actor="system", action="init", payload={"hello": "world"})
    await session.commit()

    # Capture state before simulation
    session.expire_all()
    
    # Audit head hash
    stmt_audit = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)
    res_audit = await session.execute(stmt_audit)
    audit_head_before = res_audit.scalar_one().hash

    # Op states
    res_ops = await session.execute(select(OpRow))
    op_states_before = {op.id: op.state for op in res_ops.scalars().all()}

    # Outbox count
    res_outbox = await session.execute(select(OutboxItem))
    outbox_count_before = len(res_outbox.scalars().all())

    H = {"X-Tenant-Id": tid}

    # 5. Call simulate endpoint (raising ceiling to 200 INR / 20_000 paise)
    resp_sim = await client.post("/policy-simulate", headers=H, json={
        "proposed_params": {
            "provision_cost_ceiling_minor": 20_000
        },
        "window_days": 30,
        "save_draft": True, # Test draft saving as well
        "note": "Raise ceiling for simulation test",
        "created_by": "tester"
    })
    assert resp_sim.status_code == 200
    sim_data = resp_sim.json()
    simulation = sim_data["simulation"]
    draft_version = sim_data["draft_version"]

    # Verify simulation results
    assert simulation["ops_evaluated"] == 2
    # op_above (150 INR) should be newly allowed (BLOCKED -> AUTO)
    assert len(simulation["newly_allowed"]) == 1
    assert simulation["newly_allowed"][0]["op_id"] == "op_above_123"
    assert simulation["newly_allowed"][0]["baseline_requirement"] == "BLOCKED"
    assert simulation["newly_allowed"][0]["proposed_requirement"] == "AUTO"

    # op_within (50 INR) should NOT move (so not in newly_allowed / newly_blocked / etc)
    assert len(simulation["newly_blocked"]) == 0
    assert len(simulation["newly_auto_approved"]) == 0
    assert len(simulation["now_requires_human"]) == 0

    # Verify draft was saved
    assert draft_version is not None
    session.expire_all()
    stmt_draft = select(PolicyVersion).where(PolicyVersion.tenant_id == tid, PolicyVersion.version == draft_version)
    res_draft = await session.execute(stmt_draft)
    draft_policy = res_draft.scalar_one_or_none()
    assert draft_policy is not None
    assert draft_policy.status == "proposed"
    assert draft_policy.params["provision_cost_ceiling_minor"] == 20_000
    assert draft_policy.note == "Raise ceiling for simulation test"
    assert draft_policy.created_by == "tester"

    # 6. Verify Read-Only Guarantee (No side effects on audit head, op states, or outbox)
    # Check audit head remains identical
    res_audit_after = await session.execute(stmt_audit)
    assert res_audit_after.scalar_one().hash == audit_head_before

    # Check Op states are unchanged
    res_ops_after = await session.execute(select(OpRow))
    op_states_after = {op.id: op.state for op in res_ops_after.scalars().all()}
    assert op_states_after == op_states_before

    # Check outbox count unchanged
    res_outbox_after = await session.execute(select(OutboxItem))
    outbox_count_after = len(res_outbox_after.scalars().all())
    assert outbox_count_after == outbox_count_before


@pytest.mark.asyncio
async def test_policy_simulation_deterministic(client, session):
    # Setup
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]

    baseline_policy = PolicyVersion(
        tenant_id=tid,
        version=1,
        status="active",
        params={"provision_cost_ceiling_minor": 10_000}
    )
    session.add(baseline_policy)
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="provision", score=90.0, tier=2))

    op_above = OpRow(
        id="op_above_det",
        tenant_id=tid,
        brand_id=bid,
        domain="provision",
        action="provision.web_host.create",
        state="BLOCKED",
        impact=1,
        reversibility="COMPENSATABLE",
        statutory=False,
        cost_amount_minor=15_000,
        cost_currency="INR",
        idem_key="idem_above_det"
    )
    session.add(op_above)
    await session.commit()

    H = {"X-Tenant-Id": tid}

    # Run twice and verify output is identical
    resp1 = await client.post("/policy-simulate", headers=H, json={
        "proposed_params": {"provision_cost_ceiling_minor": 20_000},
        "save_draft": False
    })
    resp2 = await client.post("/policy-simulate", headers=H, json={
        "proposed_params": {"provision_cost_ceiling_minor": 20_000},
        "save_draft": False
    })

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
