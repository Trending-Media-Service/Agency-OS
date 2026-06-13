import pytest
from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.fixture
def adapter():
    return ProvisionAdapter()

@pytest.fixture
def db_op():
    return OpSpec(
        id="op_db_123",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.postgres_db.create",
        params={
            "recipe": "postgres-db",
            "version": "0.1.0",
            "db_name": "db_b1",
            "tier": "shared"
        },
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR"),
    )

def test_db_provision_plan(adapter):
    ops = adapter.plan("please provision a postgres db", "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "provision.postgres_db.create"
    assert op.params["recipe"] == "postgres-db"
    assert op.params["version"] == "0.1.0"
    assert op.params["db_name"] == "db_b1"
    assert op.cost_estimate.amount_minor == 0

def test_db_provision_preview(adapter, db_op):
    preview_art = adapter.preview(db_op)
    assert preview_art.kind == "terraform_plan"
    assert "+ neon_database db_b1" in preview_art.summary

@pytest.mark.asyncio
async def test_db_provision_execute_and_verify(adapter, db_op):
    # 1. Execute
    res = await adapter.execute(db_op, "idem_db_123")
    assert res.ok is True
    
    # 2. Verify
    verify_res = await adapter.verify(db_op)
    assert verify_res.ok is True
    assert verify_res.checks["db_connectable"] is True
    assert verify_res.checks["schema_query_ok"] is True
