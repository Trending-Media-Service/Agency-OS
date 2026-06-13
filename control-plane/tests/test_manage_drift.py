import pytest
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.adapters.manage import ManageAdapter
from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import OpRow

@pytest.fixture
def manage_adapter():
    return ManageAdapter()

@pytest.fixture
def prov_adapter():
    return ProvisionAdapter()

@pytest.mark.asyncio
async def test_drift_detection_no_drift(manage_adapter, session: AsyncSession):
    # Prepare: Create a completed provision Op in DB
    done_op = OpRow(
        id="op_prov_done_1",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.web_host.create",
        params={
            "recipe": "web-host",
            "version": "0.1.0",
            "domain": "test-drift.in"
        },
        state="DONE", # MUST be DONE to check drift
        impact=2,
        reversibility="COMPENSATABLE",
        idem_key="idem_prov_done_1"
    )
    session.add(done_op)
    await session.commit()
    
    # Act: Run drift check
    drift_op = OpSpec(
        id="op_drift_check",
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.drift.detect",
        params={},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    # Ensure SIMULATE_DRIFT is off
    os.environ["SIMULATE_DRIFT"] = "0"
    
    res = await manage_adapter.execute(drift_op, "idem_drift_1", session=session)
    assert res.ok is True
    assert "No drift detected" in res.detail["message"]
    
    # Assert no new Ops created
    stmt = select(OpRow).where(OpRow.state == "PROPOSED")
    q_res = await session.execute(stmt)
    proposed = q_res.scalars().all()
    assert len(proposed) == 0

@pytest.mark.asyncio
async def test_drift_detection_with_drift(manage_adapter, prov_adapter, session: AsyncSession):
    # Prepare: Create a completed provision Op in DB
    done_op = OpRow(
        id="op_prov_done_2",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.web_host.create",
        params={
            **{"recipe": "web-host", "version": "0.1.0", "domain": "test-drift-active.in", "project_id": "p1"}
        },
        state="DONE",
        impact=2,
        reversibility="COMPENSATABLE",
        idem_key="idem_prov_done_2"
    )
    session.add(done_op)
    await session.commit()
    
    drift_op = OpSpec(
        id="op_drift_check_active",
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.drift.detect",
        params={},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    # Set SIMULATE_DRIFT to 1
    os.environ["SIMULATE_DRIFT"] = "1"
    
    res = await manage_adapter.execute(drift_op, "idem_drift_2", session=session)
    assert res.ok is True
    assert "Drift detected" in res.detail["message"]
    assert "op_prov_done_2" in res.detail["drifted_op_ids"]
    
    # Assert reconciliation Op is created in PROPOSED state
    stmt = select(OpRow).where(OpRow.state == "PROPOSED", OpRow.action == "provision.reconcile.apply")
    q_res = await session.execute(stmt)
    proposed = q_res.scalars().all()
    assert len(proposed) == 1
    reconcile_op = proposed[0]
    assert reconcile_op.params["target_op_id"] == "op_prov_done_2"
    assert reconcile_op.params["domain"] == "test-drift-active.in"
    assert "drift_diff" in reconcile_op.params
    
    # Now run execution of the reconciliation Op in the provision adapter!
    recon_spec = OpSpec(
        id=reconcile_op.id,
        tenant_id=reconcile_op.tenant_id,
        brand_id=reconcile_op.brand_id,
        domain=reconcile_op.domain,
        action=reconcile_op.action,
        params=reconcile_op.params,
        severity=Severity(impact=reconcile_op.impact, reversibility=Reversibility(reconcile_op.reversibility))
    )
    
    # Turn off SIMULATE_DRIFT so the apply itself succeeds and reconciles
    os.environ["SIMULATE_DRIFT"] = "0"
    
    recon_res = await prov_adapter.execute(recon_spec, "idem_recon_1")
    assert recon_res.ok is True

@pytest.mark.asyncio
async def test_diagnostics_OOM_remediation(manage_adapter, session: AsyncSession):
    # Act: Trigger diagnostic check with OOM logs
    diag_op = OpSpec(
        id="op_diag_check",
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.diagnostics.check",
        params={
            "log_source": "cloud-run-logs",
            "log_stream": "[2026-06-11 10:00:00] FATAL: Out of Memory error in container run.app"
        },
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    res = await manage_adapter.execute(diag_op, "idem_diag_1", session=session)
    assert res.ok is True
    assert "Errors detected in logs" in res.detail["message"]
    
    # Assert remediation Op is created
    stmt = select(OpRow).where(OpRow.state == "PROPOSED", OpRow.action == "provision.scale_memory.apply")
    q_res = await session.execute(stmt)
    proposed = q_res.scalars().all()
    assert len(proposed) == 1
    scale_op = proposed[0]
    assert scale_op.params["memory"] == "1Gi"
    assert scale_op.params["recipe"] == "web-host"
