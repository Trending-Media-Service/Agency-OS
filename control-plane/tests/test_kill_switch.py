import pytest
import os
from sqlalchemy import select
from app.kernel import loop
from app.kernel.optypes import OpSpec, Severity, Reversibility, OpState
from app.models import OpRow, OpTrace, Tenant, Brand, OutboxItem
from app.services.marketing import MockMarketingClient

@pytest.fixture(autouse=True)
def cleanup_registry():
    """Ensure any test domains registered during tests are cleaned up."""
    yield
    if "disabled_test_domain" in loop.REGISTRY:
        del loop.REGISTRY["disabled_test_domain"]


@pytest.fixture
async def setup_tenant_brand(session):
    """Create a tenant and brand in the DB for RLS and foreign keys."""
    tenant = Tenant(id="t_kill", name="Kill Tenant", hosting_tier="shared")
    brand = Brand(id="b_kill", tenant_id="t_kill", name="Kill Brand")
    session.add(tenant)
    session.add(brand)
    await session.commit()
    return tenant, brand


def test_is_domain_disabled_helper(monkeypatch):
    """Verify that the is_domain_disabled helper correctly parses the env var."""
    monkeypatch.delenv("AOS_DISABLED_DOMAINS", raising=False)
    assert not loop.is_domain_disabled("grow")
    assert not loop.is_domain_disabled("presence")

    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "grow")
    assert loop.is_domain_disabled("grow")
    assert not loop.is_domain_disabled("presence")

    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "grow, presence , build")
    assert loop.is_domain_disabled("grow")
    assert loop.is_domain_disabled("presence")
    assert loop.is_domain_disabled("build")
    assert not loop.is_domain_disabled("provision")


def test_adapter_registration_kill_switch(monkeypatch):
    """Verify that an adapter is not registered if its domain is disabled."""
    class DummyAdapter:
        domain = "disabled_test_domain"
        def plan(self, *args, **kwargs): return []
        def preview(self, *args, **kwargs): return None
        async def execute(self, *args, **kwargs): return None
        async def verify(self, *args, **kwargs): return None
        def compensate(self, *args, **kwargs): return []

    adapter = DummyAdapter()

    # 1. Register with env set
    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "disabled_test_domain")
    loop.register(adapter)
    assert "disabled_test_domain" not in loop.REGISTRY

    # 2. Register with env cleared
    monkeypatch.delenv("AOS_DISABLED_DOMAINS", raising=False)
    loop.register(adapter)
    assert "disabled_test_domain" in loop.REGISTRY
    assert loop.REGISTRY["disabled_test_domain"] == adapter


@pytest.mark.asyncio
async def test_preview_and_gate_graceful_block(session, setup_tenant_brand, monkeypatch):
    """Verify that proposing/gating an Op for a disabled domain gracefully blocks it with a violation."""
    tenant, brand = setup_tenant_brand
    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "grow")

    spec = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={"campaign_id": "c-kill-1", "name": "kill-test", "budget_minor": 1000},
        severity=Severity(1, Reversibility.COMPENSATABLE)
    )

    # Propose the Op
    row = await loop.propose(session, spec, actor="test")
    assert row.state == OpState.PROPOSED.value

    # Run preview and gate — should gracefully block without throwing KeyError!
    gate, requirement = await loop.preview_and_gate(session, row, tier=1, actor="test")

    # Assertions
    assert requirement == "BLOCKED"
    assert row.state == OpState.BLOCKED.value
    assert "disabled" in row.preview_summary.lower()
    
    # Verify the structured violation
    assert gate.blocked
    assert len(gate.violations) == 1
    violation = gate.violations[0]
    assert violation.rule_id == "kill_switch"
    assert "disabled" in violation.message.lower()


@pytest.mark.asyncio
async def test_outbox_drain_kill_switch_blocking(session, setup_tenant_brand, monkeypatch):
    """Verify that an APPROVED Op in the outbox is blocked and marked DEAD on drain if its domain is disabled."""
    tenant, brand = setup_tenant_brand
    
    # 1. Propose and approve an Op while grow is enabled
    monkeypatch.delenv("AOS_DISABLED_DOMAINS", raising=False)
    spec = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={"campaign_id": "c-kill-2", "name": "kill-test-2", "budget_minor": 1000, "provider": "mock"},
        severity=Severity(1, Reversibility.COMPENSATABLE)
    )
    row = await loop.propose(session, spec, actor="test")
    
    # Move to APPROVED and enqueue
    await loop.transition(session, row, OpState.PREVIEWED, actor="test")
    await loop.transition(session, row, OpState.APPROVED, actor="test")
    loop.enqueue(session, row.id, tenant.id)
    await session.commit()

    # Verify it is in outbox as pending
    stmt = select(OutboxItem).where(OutboxItem.op_id == row.id)
    res = await session.execute(stmt)
    item = res.scalar_one()
    assert item.status == "PENDING"

    # 2. Disable 'grow' before draining the outbox!
    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "grow")

    # 3. Drain the outbox
    processed = await loop.drain_once(session)
    assert processed == 1

    # 4. Verify that the Op was BLOCKED and the outbox item is DEAD (no execution!)
    await session.refresh(row)
    await session.refresh(item)
    assert row.state == OpState.BLOCKED.value
    assert item.status == "DEAD"
    
    # Verify the transition trace contains the disabled domain message
    stmt_trace = select(OpTrace).where(OpTrace.op_id == row.id, OpTrace.kind == "transition")
    res_trace = await session.execute(stmt_trace)
    traces = res_trace.scalars().all()
    blocked_trace = next(t for t in traces if t.detail.get("to") == OpState.BLOCKED.value)
    assert "disabled" in blocked_trace.detail.get("error", "").lower()


@pytest.mark.asyncio
async def test_api_endpoints_domain_disabled_error(client, monkeypatch):
    """Verify that API endpoints return a descriptive 400 error when the domain is disabled."""
    # 1. POST /intents
    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "grow")
    
    headers = {"X-Tenant-Id": "t_kill"}
    payload = {
        "brand_id": "b_kill",
        "text": "create campaign c-kill-api",
        "domain": "grow"
    }
    
    response = await client.post("/intents", json=payload, headers=headers)
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"].lower()

    # 2. POST /chat
    payload_chat = {
        "brand_id": "b_kill",
        "text": "host ableys.in"  # maps to 'provision' domain
    }
    # Disable 'provision'
    monkeypatch.setenv("AOS_DISABLED_DOMAINS", "provision")
    response_chat = await client.post("/chat", json=payload_chat, headers=headers)
    assert response_chat.status_code == 400
    assert "disabled" in response_chat.json()["detail"].lower()
