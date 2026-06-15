import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.kernel import loop
from app.kernel.optypes import Money, OpSpec, OpState, Reversibility, Severity
from app.models import Brand, Tenant, OpRow, AuditEvent, TrustEvent
from app.kernel.services import audit_append

@pytest.mark.asyncio
async def test_dr_restore_drill_success(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap tenant and brand
    async with async_session() as s:
        tenant = Tenant(name="DR Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra DR")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        # Write some initial audit events to hash-chain
        await audit_append(s, tenant_id=tenant_id, actor="tester", action="test.boot")
        await audit_append(s, tenant_id=tenant_id, actor="tester", action="test.config")
        await s.commit()

    # 2. Plan and propose the OpSpec
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="dr",
        action="dr.restore_verify",
        params={"brand_id": brand_id},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="tester")
        await s.commit()
        op_id = row.id

    # 3. Transition to APPROVED via decide
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        await loop.transition(s, db_row, OpState.PREVIEWED, actor="tester")
        await loop.decide(s, db_row, decision="approve", actor="chandan", role="AGENCY_OWNER", surface="web")
        await s.commit()

    # 4. Drain once (runs execute and verify)
    async with async_session() as s:
        processed = await loop.drain_once(s)
        await s.commit()
        assert processed == 1

    # 5. Verify the Op has been completed successfully and is DONE
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        assert db_row.state == "DONE"


@pytest.mark.asyncio
async def test_dr_restore_drill_failure_simulated_execution(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap
    async with async_session() as s:
        tenant = Tenant(name="DR Tenant Fail", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra DR Fail")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    # 2. Propose with simulate_failure
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="dr",
        action="dr.restore_verify",
        params={"brand_id": brand_id, "simulate_failure": True},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="tester")
        await s.commit()
        op_id = row.id

    # Transition to APPROVED
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        await loop.transition(s, db_row, OpState.PREVIEWED, actor="tester")
        await loop.decide(s, db_row, decision="approve", actor="chandan", role="AGENCY_OWNER", surface="web")
        await s.commit()

    # 3. Drain background task
    async with async_session() as s:
        processed = await loop.drain_once(s)
        await s.commit()
        assert processed == 1

    # 4. Verify Op state is ROLLED_BACK
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        assert db_row.state == "ROLLED_BACK"
        
        # Verify a trust verify_failure event was emitted
        stmt = select(TrustEvent).where(
            TrustEvent.tenant_id == tenant_id,
            TrustEvent.brand_id == brand_id,
            TrustEvent.kind == "verify_failure"
        )
        res = await s.execute(stmt)
        assert res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_dr_restore_drill_failure_simulated_verification(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap
    async with async_session() as s:
        tenant = Tenant(name="DR Tenant Fail 2", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra DR Fail 2")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    # 2. Propose with simulate_verify_failure
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="dr",
        action="dr.restore_verify",
        params={"brand_id": brand_id, "simulate_verify_failure": True},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="tester")
        await s.commit()
        op_id = row.id

    # Transition to APPROVED
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        await loop.transition(s, db_row, OpState.PREVIEWED, actor="tester")
        await loop.decide(s, db_row, decision="approve", actor="chandan", role="AGENCY_OWNER", surface="web")
        await s.commit()

    # 3. Drain background task
    async with async_session() as s:
        processed = await loop.drain_once(s)
        await s.commit()
        assert processed == 1

    # 4. Verify Op state is ROLLED_BACK due to verification checks failing
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        assert db_row.state == "ROLLED_BACK"
        
        # Verify a trust verify_failure event was emitted
        stmt = select(TrustEvent).where(
            TrustEvent.tenant_id == tenant_id,
            TrustEvent.brand_id == brand_id,
            TrustEvent.kind == "verify_failure"
        )
        res = await s.execute(stmt)
        assert res.scalar_one_or_none() is not None
