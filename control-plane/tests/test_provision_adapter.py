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


async def test_provision_adapter_execute_create(adapter, create_op):
    res = await adapter.execute(create_op, "idem_123")
    assert res.ok is True
    # Verify outputs are captured
    assert res.detail["outputs"]["service_url"] == "https://web-woktok.in"
    assert res.detail["outputs"]["dns_zone"] == "zone-woktok.in"
    assert res.detail["outputs"]["cert_id"] == "cert-123"


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


@pytest.fixture
def n8n_op(adapter):
    ops = adapter.plan("install n8n", "t1", "b1")
    assert len(ops) == 1
    return ops[0]


def test_provision_adapter_n8n_plan(adapter):
    ops = adapter.plan("install n8n", "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "provision.n8n.create"
    assert op.params["recipe"] == "n8n"
    assert op.params["project_id"] == "aos-shared-tier"
    assert op.params["db_name"] == "db-b1"


def test_provision_adapter_n8n_preview(adapter, n8n_op):
    preview_art = adapter.preview(n8n_op)
    assert preview_art.kind == "terraform_plan"
    assert "Plan: 2 to add" in preview_art.summary
    assert "+ cloud_run n8n-service" in preview_art.summary


async def test_provision_adapter_n8n_execute(adapter, n8n_op):
    res = await adapter.execute(n8n_op, "idem_n8n_123")
    assert res.ok is True
    assert res.detail["outputs"]["service_url"] == "https://n8n-service-123.run.app"


@pytest.mark.asyncio
async def test_provision_adapter_n8n_verify(adapter, n8n_op):
    res = await adapter.verify(n8n_op)
    assert res.ok is True
    assert res.checks["http_200"] is True


def test_provision_adapter_n8n_compensate(adapter, n8n_op):
    compensations = adapter.compensate(n8n_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "provision.n8n.destroy"
    assert comp.params["recipe"] == "n8n"

