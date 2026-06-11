import pytest
import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant, Brand, Cadence, OpRow, TrustSnapshot, AuditEvent

@pytest.mark.asyncio
async def test_process_cadences_triggers_op(client, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    one_day_ago = now - dt.timedelta(days=1)

    # 1. Bootstrap Tenant, Brand and Trust Tier
    async with async_session() as s:
        tenant = Tenant(name="Scheduler Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Scheduled")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        # Trust Tier 2 (to verify if proposed Ops get gated automatically)
        s.add(TrustSnapshot(tenant_id=tenant_id, brand_id=brand_id, domain="presence", tier=2, score=90.0))
        await s.commit()

        # 2. Add Cadence that is due (next_run in the past)
        cadence = Cadence(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="presence",
            action="presence.search_console.audit",
            schedule="weekly",
            next_run=one_day_ago,
            status="on_track"
        )
        s.add(cadence)
        await s.commit()
        cadence_id = cadence.id

    # 3. Act: Trigger /tasks/process-cadences endpoint
    resp = await client.post("/tasks/process-cadences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["proposed_ops_count"] == 1

    # 4. Assertions
    async with async_session() as s:
        # Verify Cadence row has been updated
        stmt_cad = select(Cadence).where(Cadence.id == cadence_id)
        res_cad = await s.execute(stmt_cad)
        updated_cad = res_cad.scalar_one()

        assert updated_cad.last_run is not None
        # next_run should be ~6 days in the future (one_day_ago + 7 days = now + 6 days)
        # Or more accurately, since we computed delta from 'now': now + 7 days
        diff = updated_cad.next_run - now
        assert 6.9 < diff.days <= 7.0

        # Verify OpRow was proposed and gated to AWAITING_APPROVAL (since presence audits require HUMAN approval)
        # Wait, does presence.search_console.audit require human approval?
        # Yes, we set blocking=False on statutory region lock, but for Presence audits:
        # Are there rules blocking it? No.
        # But wait! Does it auto-approve at Tier 2?
        # Let's check:
        # OpSpec has severity = Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        # And no violations since there are no rules for presence!
        # So it should transition to APPROVED!
        stmt_op = select(OpRow).where(OpRow.brand_id == brand_id, OpRow.action == "presence.search_console.audit")
        res_op = await s.execute(stmt_op)
        op = res_op.scalar_one()
        
        # It has no violations and is low severity, so at Tier 2 it auto-approves!
        assert op.state == "APPROVED"

        # Verify proposing actor from AuditEvent
        stmt_audit = select(AuditEvent).where(AuditEvent.op_id == op.id, AuditEvent.action == "op.proposed")
        res_audit = await s.execute(stmt_audit)
        audit_event = res_audit.scalar_one()
        assert audit_event.actor == "scheduler"

        assert "Scan GSC index rates" in op.preview_summary or "Search Console" in op.preview_summary

@pytest.mark.asyncio
async def test_process_cadences_skips_future(client, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    one_day_future = now + dt.timedelta(days=1)

    # 1. Bootstrap Tenant, Brand
    async with async_session() as s:
        tenant = Tenant(name="Scheduler Tenant 2", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Scheduled 2")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        # 2. Add Cadence that is in the future
        cadence = Cadence(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="presence",
            action="presence.merchant_center.audit",
            schedule="daily",
            next_run=one_day_future,
            status="on_track"
        )
        s.add(cadence)
        await s.commit()

    # 3. Act: Trigger /tasks/process-cadences
    resp = await client.post("/tasks/process-cadences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposed_ops_count"] == 0

    # 4. Assert: No Ops were created for this brand
    async with async_session() as s:
        stmt_op = select(OpRow).where(OpRow.brand_id == brand_id)
        res_op = await s.execute(stmt_op)
        ops = res_op.scalars().all()
        assert len(ops) == 0
