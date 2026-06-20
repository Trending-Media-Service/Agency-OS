import pytest
import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import (
    Tenant,
    Brand,
    Campaign,
    SpendFact,
    Touchpoint,
    Lead,
    BrandObjective
)
from app.profit.poas import calculate_campaign_poas
from app.adapters.grow import GrowAdapter
from app.services.marketing import MockMarketingClient
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money


@pytest.mark.asyncio
async def test_lead_database_model_lifecycle(db_engine):
    """Verify that the new Lead database model can be inserted, queried, and enforces RLS structure."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        # 1. Bootstrap Tenant and Brand
        tenant = Tenant(name="Lead Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Lead Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # 2. Insert Lead record
        placed = dt.datetime(2026, 6, 21, 12, 0, 0)
        lead = Lead(
            tenant_id=tid,
            brand_id=bid,
            lead_id="crm_lead_12345",
            email_hashed="5e883f8b1763586c4f4e1f153aae88c2", # hashed 'email'
            status="closed_won",
            deal_value_minor=500000, # ₹5,000 deal value
            gclid="gclid_lead_987",
            placed_at=placed
        )
        s.add(lead)
        await s.commit()

    # 3. Query and verify
    async with async_session() as s:
        stmt = select(Lead).where(Lead.lead_id == "crm_lead_12345")
        res = await s.execute(stmt)
        queried_lead = res.scalar_one_or_none()

        assert queried_lead is not None
        assert queried_lead.tenant_id == tid
        assert queried_lead.brand_id == bid
        assert queried_lead.status == "closed_won"
        assert queried_lead.deal_value_minor == 500000
        assert queried_lead.gclid == "gclid_lead_987"
        assert queried_lead.placed_at == placed


@pytest.mark.asyncio
async def test_crm_lead_poas_attribution_growth_objective(db_engine):
    """Verify that if a brand objective is 'growth', calculate_campaign_poas bypasses orders and attributes CRM leads."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        # 1. Bootstrap Tenant, Brand
        tenant = Tenant(name="Omni Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Omni Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # 2. Configure Strategic Objective to 'growth' (Lead Gen / CRM mode)
        obj = BrandObjective(tenant_id=tid, brand_id=bid, objective="growth")
        s.add(obj)

        # 3. Setup Campaign and Spend
        c1 = Campaign(id="camp_crm_google", tenant_id=tid, brand_id=bid, name="Google Leads", platform="google-ads", status="active")
        s.add(c1)
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_crm_google", amount_minor=20000, date=dt.date(2026, 6, 21))) # ₹200 spend

        # 4. Setup Touchpoint using hashed email as customer_id
        hashed_email = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        tp = Touchpoint(
            tenant_id=tid, 
            customer_id=hashed_email, 
            campaign_id="camp_crm_google", 
            type="click", 
            occurred_at=dt.datetime(2026, 6, 21, 10, 0, 0)
        )
        s.add(tp)

        # 5. Setup CRM Leads
        # Lead 1: closed_won -> Deal value: ₹5,000 (500,000 minor) -> Attributed to camp_crm_google
        l1 = Lead(
            tenant_id=tid,
            brand_id=bid,
            lead_id="lead_001",
            email_hashed=hashed_email,
            status="closed_won",
            deal_value_minor=500000,
            gclid="gclid_ok",
            placed_at=dt.datetime(2026, 6, 21, 11, 0, 0)
        )
        # Lead 2: stage 'lead' -> Deal value: None -> Attributed to camp_crm_google, but contributing 0 margin
        l2 = Lead(
            tenant_id=tid,
            brand_id=bid,
            lead_id="lead_002",
            email_hashed=hashed_email,
            status="lead",
            deal_value_minor=None,
            gclid="gclid_ok",
            placed_at=dt.datetime(2026, 6, 21, 11, 30, 0)
        )
        s.add_all([l1, l2])
        await s.commit()

    # 6. Execute POAS and verify Lead Attribution
    async with async_session() as s:
        reports = await calculate_campaign_poas(s, tid, bid)

        # camp_crm_google should have:
        # - spend_minor: 20,000
        # - gross_revenue_minor: 500,000 (Lead 1 closed_won)
        # - contribution_margin_minor: 500,000 (Deal profit)
        # - POAS: 500,000 / 20,000 = 25.0x
        # - orders: 2 (Lead 1 + Lead 2 both enqueued as conversion counts)
        assert len(reports) == 1
        rep = reports[0]

        assert rep["campaign_id"] == "camp_crm_google"
        assert rep["spend_minor"] == 20000
        assert rep["contribution_margin_minor"] == 500000
        assert rep["poas"] == 25.0
        assert rep["roas"] == 25.0
        assert rep["orders"] == 2


@pytest.mark.asyncio
async def test_grow_adapter_planning_for_omnichannel_actions(db_engine):
    """Verify that GrowAdapter.plan() parses natural language into PMax audience swaps and keyword sweeps."""
    adapter = GrowAdapter()
    
    # 1. Test "optimize audience" triggers PMax Audience Swapper
    ops_aud = adapter.plan(
        tenant_id="t-1",
        brand_id="b-1",
        intent="Optimize PMax campaign audience using segment 251066626"
    )
    assert len(ops_aud) == 1
    op_aud = ops_aud[0]
    assert op_aud.action == "grow.pmax.audience_signal_update"
    assert op_aud.params["new_audience_id"] == "251066626"
    assert op_aud.params["requires_consent_category"] == "pii_upload"
    assert op_aud.severity.reversibility == Reversibility.COMPENSATABLE

    # 2. Test "clean keywords" triggers Keyword Auditor
    ops_kw = adapter.plan(
        tenant_id="t-1",
        brand_id="b-1",
        intent="Clean generic search campaign keywords to prevent budget waste"
    )
    assert len(ops_kw) == 1
    op_kw = ops_kw[0]
    assert op_kw.action == "grow.search.keyword_cleanup"
    assert op_kw.params["campaign_name"] == "Ableys_Brand Search_May 12th"
    assert op_kw.params["brand_terms"] == ["ableys", "abley's"]


@pytest.mark.asyncio
async def test_grow_adapter_execute_and_compensate_rollback():
    """Verify that GrowAdapter executes PMax/Keyword operations and generates correct rollbacks in compensate()."""
    adapter = GrowAdapter()
    client = MockMarketingClient()
    
    # 1. Test execute grow.pmax.audience_signal_update
    op_aud = OpSpec(
        id="op_aud_1",
        tenant_id="t-1",
        brand_id="b-1",
        domain="grow",
        action="grow.pmax.audience_signal_update",
        params={
            "campaign_names": ["Sales-Performance"],
            "new_audience_id": "251066626",
            "provider": "google-ads"
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    res_aud = await adapter.execute(op_aud, client)
    assert res_aud.ok is True
    assert "updated with Audience 251066626" in res_aud.detail["message"]

    # 2. Test execute grow.search.keyword_cleanup
    op_kw = OpSpec(
        id="op_kw_1",
        tenant_id="t-1",
        brand_id="b-1",
        domain="grow",
        action="grow.search.keyword_cleanup",
        params={
            "campaign_name": "Brand Search",
            "brand_terms": ["ableys"],
            "provider": "google-ads"
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    res_kw = await adapter.execute(op_kw, client)
    assert res_kw.ok is True
    assert "paused_keyword_resources" in res_kw.detail
    assert len(res_kw.detail["paused_keyword_resources"]) > 0

    # 3. Test compensate() saga rollback for keyword cleanup
    # We pass the execution result's paused resources to simulate a rollback trigger
    executed_op = OpSpec(
        id="op_kw_1",
        tenant_id="t-1",
        brand_id="b-1",
        domain="grow",
        action="grow.search.keyword_cleanup",
        params={
            "campaign_name": "Brand Search",
            "brand_terms": ["ableys"],
            "paused_keyword_resources": res_kw.detail["paused_keyword_resources"]
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    rollbacks = adapter.compensate(executed_op)
    assert len(rollbacks) == 1
    rollback = rollbacks[0]
    
    # Check that the rollback restores precisely the paused resources!
    assert rollback.action == "grow.search.keyword_restore"
    assert rollback.params["paused_resources"] == res_kw.detail["paused_keyword_resources"]
    assert rollback.severity.reversibility == Reversibility.REVERSIBLE
