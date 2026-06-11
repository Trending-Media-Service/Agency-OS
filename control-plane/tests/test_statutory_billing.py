import pytest
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.kernel.optypes import OpSpec, Severity, Reversibility, OpState, Money
from app.kernel.services import evaluate_gates, approval_requirement, get_tenant_cost_rollup
from app.models import OpRow, TrustSnapshot, CostEntry
from app.adapters.provision import ProvisionAdapter

@pytest.fixture
def prov_adapter():
    return ProvisionAdapter()

@pytest.mark.asyncio
async def test_statutory_region_lock_violation(prov_adapter):
    # Prepare: Create provision Op targeting us-central1 (non-compliant region)
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.web_host.create",
        params={
            "recipe": "web-host",
            "version": "0.1.0",
            "domain": "statutory-test.in",
            "region": "us-central1" # compliant is asia-south1
        },
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(250_000)
    )
    
    # Act: Evaluate gates
    gate = evaluate_gates(op)
    
    # Assert: Should trigger statutory_region_lock violation
    assert len(gate.violations) == 1
    v = gate.violations[0]
    assert v.rule_id == "statutory_region_lock"
    assert v.attempted == "us-central1"
    assert "asia-south1" in v.limit
    
    # Assert: Even at Tier 2 trust snapshot, statutory violations require HUMAN approval
    req = approval_requirement(op, tier=2, gate=gate)
    assert req == "HUMAN" # blocked from AUTO approval

@pytest.mark.asyncio
async def test_compliant_region_and_billing_ledger(prov_adapter, session: AsyncSession):
    # Prepare: Create provision Op targeting asia-south1 (compliant region)
    op_spec = OpSpec(
        tenant_id="t2",
        brand_id="b2",
        domain="provision",
        action="provision.web_host.create",
        params={
            "recipe": "web-host",
            "version": "0.1.0",
            "domain": "compliant-test.in",
            "region": "asia-south1",
            "project_id": "compliant-proj-123"
        },
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(250_000)
    )
    
    # Act: Evaluate gates
    gate = evaluate_gates(op_spec)
    assert len(gate.violations) == 0 # no violations!
    
    req = approval_requirement(op_spec, tier=2, gate=gate)
    assert req == "AUTO" # allowed to auto-approve at Tier 2
    
    # Propose OpRow in DB
    from app.kernel import loop
    row = await loop.propose(session, op_spec, actor="test")
    
    # Evaluate gate and transition to approved
    await loop.preview_and_gate(session, row, tier=2)
    await session.commit()
    
    assert row.state == "APPROVED"
    
    # Execute the Op via drain_once
    processed = await loop.drain_once(session)
    assert processed == 1
    await session.commit()
    
    # Verify the Op completed successfully
    assert row.state == "DONE"
    
    # Assert: Verify billing cost ledger entry was written grouped by gcp_resource
    stmt = select(CostEntry).where(CostEntry.tenant_id == "t2")
    q_res = await session.execute(stmt)
    entries = q_res.scalars().all()
    
    # Should contain:
    # - api_call (20.00 INR)
    # - api_call (1.50 INR)
    # - gcp_resource (2,500.00 INR parsed from recipes/web-host/0.1.0/recipe.yaml)
    assert len(entries) == 3
    
    gcp_res_entry = next(e for e in entries if e.kind == "gcp_resource")
    assert gcp_res_entry.amount_minor == 250_000 # 2500 INR
    assert gcp_res_entry.meta["recipe"] == "web-host"
    
    # Verify cost rollups utility
    rollups = await get_tenant_cost_rollup(session, "t2")
    assert rollups["gcp_resource"] == 250_000
    assert rollups["api_call"] == 2150 # 2000 + 150
