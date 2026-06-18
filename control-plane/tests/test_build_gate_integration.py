import pytest
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import Tenant, Brand, OpRow, TrustSnapshot, OpTrace
from app.kernel import loop
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.mark.asyncio
async def test_build_gate_blocked_by_protected_paths(client, db_engine, temp_git_remote):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Build Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Build")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # 2. Seed a TrustSnapshot as Tier 2 to allow auto-approvals
    # We want to verify that even at Tier 2 (which normally auto-approves),
    # a blocking policy violation like protected paths STILL blocks the Op.
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id=tenant_id, brand_id=brand_id, domain="build", score=90.0, tier=2))
        await s.commit()

    # 3. Mock VertexAIClient to return a malicious edit touching control-plane
    mock_edits = {
        "explanation": "Attempting to modify control plane",
        "edits": [
            {
                "path": "control-plane/app/main.py",
                "action": "modify",
                "content": "# Malicious change\n"
            }
        ]
    }

    with patch("app.services.llm.VertexAIClient.generate_edits", return_value=mock_edits):
        # Propose the build Op
        op_spec = OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="build",
            action="build.deliver",
            params={
                "intent": "hack control plane",
                "branch_name": "malicious-branch",
                "repo": temp_git_remote
            },
            severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
            cost_estimate=Money(amount_minor=1000, currency="INR"),
        )
        
        async with async_session() as s:
            row = await loop.propose(s, op_spec, actor="test")
            await s.commit()
            op_id = row.id

        # Run preview_and_gate.
        # This will run BuildAdapter.preview (which clones temp repo, applies our mocked edits,
        # gets the diff, and sets it in params), then runs evaluate_gates.
        async with async_session() as s:
            db_row = await s.get(OpRow, op_id)
            gate, req = await loop.preview_and_gate(s, db_row, tier=2)
            await s.commit()

            # Assertions
            assert req == "BLOCKED"
            assert db_row.state == "BLOCKED"
            assert any(v.rule_id == "build_protected_paths" for v in gate.violations)
            assert "control-plane/app/main.py" in gate.violations[0].attempted
            
            # Verify that a transition trace to BLOCKED was written
            traces_res = await s.execute(select(OpTrace).where(OpTrace.op_id == op_id, OpTrace.kind == "transition").order_by(OpTrace.id.desc()).limit(1))
            last_trace = traces_res.scalar_one_or_none()
            assert last_trace is not None
            assert last_trace.detail["to"] == "BLOCKED"
