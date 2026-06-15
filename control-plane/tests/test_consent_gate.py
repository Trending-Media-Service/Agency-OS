import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models import Tenant, Brand, OpRow, ConsentBasis
from app.kernel import loop
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.kernel.optypes import PreviewArtifact, ExecResult, VerifyResult
from app.kernel.loop import Adapter

class DummyPaymentAdapter(Adapter):
    domain = "payment"
    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        return []
    def preview(self, op: OpSpec) -> PreviewArtifact:
        return PreviewArtifact(kind="payment_preview", summary="Payment Refund", detail={})
    async def execute(self, op: OpSpec, idem_key: str, session=None) -> ExecResult:
        return ExecResult(ok=True, detail={})
    async def verify(self, op: OpSpec) -> VerifyResult:
        return VerifyResult(ok=True, checks={})
    def compensate(self, op: OpSpec) -> list[OpSpec]:
        return []

try:
    loop.register(DummyPaymentAdapter())
except ValueError:
    # Already registered
    pass

@pytest.mark.asyncio
async def test_consent_gate_pii_flow(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Consent Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Consent")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # 2. Propose PII Op: grow.audience.upload
    # Should block immediately due to missing consent
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.audience.upload",
        params={"emails": ["test@test.com"]},
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="test")
        await s.commit()
        op_id = row.id

    # Running preview_and_gate should block it
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        gate, req = await loop.preview_and_gate(s, db_row, tier=2)
        await s.commit()
        
        assert req == "BLOCKED"
        assert db_row.state == "BLOCKED"
        assert any("Missing PII upload consent basis" in v.delta for v in gate.violations)

    # 3. Plan and execute Consent Grant Op
    resp_plan = await client.post("/intents", headers=H, json={
        "domain": "governance",
        "brand_id": brand_id,
        "text": "grant consent for pii_upload grow.audience.upload"
    })
    assert resp_plan.status_code == 200
    data = resp_plan.json()
    assert len(data["cards"]) == 1
    
    grant_card = data["cards"][0]
    grant_op_id = grant_card["op_id"]

    # Approve the grant Op
    resp_dec = await client.post(f"/ops/{grant_op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp",
        "reason": "granting pii upload consent"
    })
    if resp_dec.status_code != 200:
        print("ERROR_DECISION_GRANT:", resp_dec.json())
    assert resp_dec.status_code == 200

    # Refresh DB session to ensure background drain states are sync'd
    async with async_session() as s:
        await s.commit()

    # Verify ConsentBasis was written
    async with async_session() as s:
        res = await s.execute(select(ConsentBasis).where(ConsentBasis.tenant_id == tenant_id))
        consents = res.scalars().all()
        assert len(consents) == 1
        assert consents[0].category == "pii_upload"
        assert consents[0].action_or_vendor == "grow.audience.upload"
        assert consents[0].status == "granted"

    # 4. Now re-propose PII Op - should not block and should be AWAITING_APPROVAL
    op_spec_2 = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.audience.upload",
        params={"emails": ["other@test.com"]},
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
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
        assert len(gate2.violations) == 0

    # 5. Revoke Consent
    resp_plan_rev = await client.post("/intents", headers=H, json={
        "domain": "governance",
        "brand_id": brand_id,
        "text": "revoke consent for pii_upload grow.audience.upload"
    })
    assert resp_plan_rev.status_code == 200
    data_rev = resp_plan_rev.json()
    assert len(data_rev["cards"]) == 1
    
    rev_card = data_rev["cards"][0]
    rev_op_id = rev_card["op_id"]

    # Approve revocation
    await client.post(f"/ops/{rev_op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp",
        "reason": "revoking pii upload consent"
    })

    # Refresh DB session
    async with async_session() as s:
        await s.commit()

    # Verify ConsentBasis is updated to revoked
    async with async_session() as s:
        res = await s.execute(select(ConsentBasis).where(ConsentBasis.tenant_id == tenant_id))
        consents = res.scalars().all()
        assert len(consents) == 1
        assert consents[0].status == "revoked"

    # 6. Propose a third PII Op - should block again
    op_spec_3 = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.audience.upload",
        params={"emails": ["third@test.com"]},
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row3 = await loop.propose(s, op_spec_3, actor="test")
        await s.commit()
        op_id_3 = row3.id

    async with async_session() as s:
        db_row3 = await s.get(OpRow, op_id_3)
        gate3, req3 = await loop.preview_and_gate(s, db_row3, tier=2)
        await s.commit()
        
        assert req3 == "BLOCKED"
        assert db_row3.state == "BLOCKED"


@pytest.mark.asyncio
async def test_consent_gate_vendor_sharing_flow(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Consent Tenant 2", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Vendor")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # Propose Stripe refund Op (payment.refund)
    # Should block due to missing vendor sharing consent basis
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="payment",
        action="payment.refund",
        params={"charge_id": "ch_123", "amount_minor": 100_00},
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="test")
        await s.commit()
        op_id = row.id

    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        gate, req = await loop.preview_and_gate(s, db_row, tier=2)
        await s.commit()
        
        assert req == "BLOCKED"
        assert db_row.state == "BLOCKED"
        assert any("Missing vendor sharing consent basis for vendor 'stripe'" in v.delta for v in gate.violations)

    # Grant vendor sharing consent for stripe
    resp_plan = await client.post("/intents", headers=H, json={
        "domain": "governance",
        "brand_id": brand_id,
        "text": "grant consent for vendor_sharing stripe"
    })
    assert resp_plan.status_code == 200
    
    grant_op_id = resp_plan.json()["cards"][0]["op_id"]
    await client.post(f"/ops/{grant_op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp",
        "reason": "granting stripe vendor consent"
    })

    # Refresh DB session
    async with async_session() as s:
        await s.commit()

    # Re-propose the Stripe refund - should not block and should be AWAITING_APPROVAL
    op_spec2 = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="payment",
        action="payment.refund",
        params={"charge_id": "ch_123", "amount_minor": 100_00},
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row2 = await loop.propose(s, op_spec2, actor="test")
        await s.commit()
        op_id2 = row2.id

    async with async_session() as s:
        db_row2 = await s.get(OpRow, op_id2)
        gate2, req2 = await loop.preview_and_gate(s, db_row2, tier=2)
        await s.commit()
        
        assert req2 == "AUTO"
        assert db_row2.state == "APPROVED"
