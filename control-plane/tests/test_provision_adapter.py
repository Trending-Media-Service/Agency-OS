import pytest
import os
from unittest.mock import patch, MagicMock

from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money, OpState

RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../recipes"))


@pytest.fixture
def adapter():
    return ProvisionAdapter()


@pytest.fixture
def create_op():
    return OpSpec(
        id="op_123",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.web_host.create",
        params={"domain": "woktok.in", "recipe": "web-host", "version": "0.1.0"},
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=250_000, currency="INR"),
    )


@pytest.fixture
def destroy_op(create_op):
    return OpSpec(
        id="op_456",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.web_host.destroy",
        params=create_op.params,
        severity=Severity(impact=2, reversibility=Reversibility.IRREVERSIBLE),
        parent_op_id=create_op.id,
    )


def test_provision_adapter_plan(adapter):
    ops = adapter.plan("host test.com please", "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "provision.web_host.create"
    assert op.params["domain"] == "test.com"
    assert op.params["recipe"] == "web-host"
    assert op.params["version"] == "0.1.0"
    assert op.cost_estimate.amount_minor == 250_000
    assert op.severity.reversibility == Reversibility.COMPENSATABLE


def test_provision_adapter_preview(adapter, create_op):
    preview_art = adapter.preview(create_op)
    assert preview_art.kind == "terraform_plan"
    assert "Plan: 5 to add" in preview_art.summary
    assert "stdout" in preview_art.detail


@pytest.mark.asyncio
async def test_provision_adapter_execute_create(adapter, create_op):
    res = await adapter.execute(create_op, "idem_123")
    assert res.ok is True
    # Verify outputs are captured
    assert res.detail["outputs"]["service_url"] == "https://web-woktok.in"
    assert res.detail["outputs"]["dns_zone"] == "zone-woktok.in"
    assert res.detail["outputs"]["cert_id"] == "cert-123"


@pytest.mark.asyncio
async def test_provision_adapter_execute_destroy(adapter, destroy_op):
    res = await adapter.execute(destroy_op, "idem_456")
    assert res.ok is True
    # Verify destroy ran (mock_terraform_cli returns Apply/Destroy completed)
    assert "Destroy complete!" in res.detail["stdout"]


@pytest.mark.asyncio
async def test_provision_adapter_verify_success(adapter, create_op):
    # Execute first to write outputs (mocked, but verify reads mock output)
    # Verify runs checks.py
    res = await adapter.verify(create_op)
    assert res.ok is True
    assert res.checks["dns_resolves"] is True
    assert res.checks["cert_issued"] is True
    assert res.checks["http_200"] is True


@pytest.mark.asyncio
async def test_provision_adapter_verify_destroy(adapter, destroy_op):
    res = await adapter.verify(destroy_op)
    assert res.ok is True
    assert res.checks["destroyed"] is True


def test_provision_adapter_compensate(adapter, create_op):
    compensations = adapter.compensate(create_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "provision.web_host.destroy"
    assert comp.parent_op_id == create_op.id
    assert comp.params == create_op.params
    assert comp.severity.reversibility == Reversibility.IRREVERSIBLE


@pytest.fixture
def brand_baseline_op():
    return OpSpec(
        id="op_789",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.brand_baseline.create",
        params={"brand_id": "b1", "tenant_id": "t1", "tier": "shared", "recipe": "brand-baseline", "version": "0.1.0"},
        severity=Severity(impact=3, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR"),
    )


def test_provision_adapter_brand_baseline_preview(adapter, brand_baseline_op):
    preview_art = adapter.preview(brand_baseline_op)
    assert preview_art.kind == "terraform_plan"
    assert "Plan: 3 to add" in preview_art.summary
    assert "+ database db-b1" in preview_art.summary


@pytest.mark.asyncio
async def test_provision_adapter_brand_baseline_execute(adapter, brand_baseline_op):
    res = await adapter.execute(brand_baseline_op, "idem_789")
    assert res.ok is True
    assert res.detail["outputs"]["project_id"] == "aos-shared-tier"
    assert "shared-sa@aos-shared-tier" in res.detail["outputs"]["service_account_email"]


@pytest.mark.asyncio
async def test_provision_adapter_brand_baseline_verify(adapter, brand_baseline_op):
    res = await adapter.verify(brand_baseline_op)
    assert res.ok is True
    assert res.checks["sa_exists"] is True
    assert res.checks["db_reachable"] is True


@pytest.mark.asyncio
async def test_provision_adapter_email_dns_and_static_host_lifecycle(adapter):
    # 1. Test email-dns create
    op_dns = OpSpec(
        id="op_dns_123", tenant_id="t1", brand_id="b1", domain="provision",
        action="provision.email_dns.create",
        params={
            "domain": "woktok.co", "project_id": "aos-brand-b1",
            "dkim_record": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ",
            "recipe": "email-dns", "version": "0.1.0"
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR")
    )
    res_dns = await adapter.execute(op_dns, "idem_dns")
    assert res_dns.ok is True
    assert res_dns.detail["outputs"]["dns_verified"] is True
    
    ver_dns = await adapter.verify(op_dns)
    assert ver_dns.ok is True
    assert ver_dns.checks["mx_valid"] is True
    assert ver_dns.checks["spf_valid"] is True
    
    # 2. Test static-host create
    op_static = OpSpec(
        id="op_static_123", tenant_id="t1", brand_id="b1", domain="provision",
        action="provision.static_host.create",
        params={
            "domain": "static.woktok.co", "project_id": "aos-brand-b1",
            "bucket_name": "woktok-static-bucket",
            "recipe": "static-host", "version": "0.1.0"
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=50_000, currency="INR")
    )
    res_static = await adapter.execute(op_static, "idem_static")
    assert res_static.ok is True
    assert "woktok-static-bucket" in res_static.detail["outputs"]["bucket_url"]
    
    ver_static = await adapter.verify(op_static)
    assert ver_static.ok is True
    assert ver_static.checks["http_200"] is True
    assert ver_static.checks["cdn_up"] is True


@pytest.mark.asyncio
async def test_provision_adapter_failed_check_and_compensation(adapter):
    # 1. Test failed-check (verify returns false)
    op_dns_fail = OpSpec(
        id="op_dns_fail", tenant_id="t1", brand_id="b1", domain="provision",
        action="provision.email_dns.create",
        params={
            "domain": "fail-verify.in", "project_id": "aos-brand-b1",
            "dkim_record": "mock-key",
            "recipe": "email-dns", "version": "0.1.0"
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR")
    )
    res = await adapter.execute(op_dns_fail, "idem_dns_fail")
    assert res.ok is True

    ver = await adapter.verify(op_dns_fail)
    assert ver.ok is False
    assert ver.checks["mx_valid"] is False

    # 2. Test compensation planning (generates compensating destroy Op)
    compensations = adapter.compensate(op_dns_fail)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "provision.email_dns.destroy"
    assert comp.parent_op_id == op_dns_fail.id
    assert comp.params == op_dns_fail.params
    assert comp.severity.reversibility == Reversibility.IRREVERSIBLE

