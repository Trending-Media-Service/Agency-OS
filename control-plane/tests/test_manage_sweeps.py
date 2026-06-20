import pytest
import os
import datetime as dt
from sqlalchemy import select
from app.models import OpRow, Tenant, Brand, TrustSnapshot

@pytest.mark.asyncio
async def test_drift_detection_sweep_creates_reconciliation(client, session):
    """Test that the drift detection sweep scans active brands, detects Terraform drift,
    and automatically proposes provision.reconcile.apply operations in the queue.
    """
    # 1. Prepare: Bootstrap a tenant and brand
    r = await client.post("/tenants", json={"name": "DriftSweepTenant", "brand_name": "DriftBrand"})
    assert r.status_code == 200
    data = r.json()
    tid, bid = data["tenant_id"], data["brand_id"]

    # Seed a TrustSnapshot to establish Tier 2 (Autonomous) so that the sweep Op auto-approves
    snapshot = TrustSnapshot(
        tenant_id=tid,
        brand_id=bid,
        domain="manage",
        score=100.0,
        tier=2,
        ts=dt.datetime.now(dt.timezone.utc)
    )
    session.add(snapshot)

    # 2. Seed a completed provision Op in the DB (must be state == DONE and not brand-bootstrap to be scanned)
    done_op = OpRow(
        id="op_prov_done_sweep",
        tenant_id=tid,
        brand_id=bid,
        domain="provision",
        action="provision.web_host.create",
        params={
            "recipe": "web-host",
            "version": "0.1.0",
            "domain": "swept-drift-site.in",
            "project_id": "proj-sweep-1"
        },
        state="DONE",
        impact=2,
        reversibility="COMPENSATABLE",
        idem_key="idem_prov_done_sweep"
    )
    session.add(done_op)
    await session.commit()

    # 3. Turn on drift simulation (so mock terraform plan returns exit code 2 - drifted!)
    os.environ["SIMULATE_DRIFT"] = "1"

    try:
        # 4. Act: Trigger the periodic drift detection sweep task endpoint
        r_sweep = await client.post("/tasks/drift-detect")
        assert r_sweep.status_code == 200, r_sweep.text
        assert r_sweep.json()["status"] == "ok"

        # Drain the outbox to execute the auto-approved manage.drift.detect Op!
        r_drain = await client.post("/tasks/drain-outbox")
        assert r_drain.status_code == 200, r_drain.text

        # 5. Assert: Verify that a drift check Op was executed and a reconciliation Op was enqueued!
        stmt = select(OpRow).where(
            OpRow.tenant_id == tid,
            OpRow.brand_id == bid,
            OpRow.action == "provision.reconcile.apply",
            OpRow.state == "PROPOSED"
        )
        res = await session.execute(stmt)
        reconciliations = res.scalars().all()
        
        assert len(reconciliations) == 1, "Should have created exactly 1 reconciliation Op"
        recon_op = reconciliations[0]
        assert recon_op.params["target_op_id"] == "op_prov_done_sweep"
        assert recon_op.params["domain"] == "swept-drift-site.in"
        assert "drift_diff" in recon_op.params
        assert "TTL = 300 -> 3600 (drifted)" in recon_op.params["drift_diff"]

    finally:
        # Clean up environment variable
        os.environ["SIMULATE_DRIFT"] = "0"


@pytest.mark.asyncio
async def test_diagnostics_sweep_creates_scale_remediation(client, session):
    """Test that the diagnostics sweep scans active brands, detects Out-Of-Memory (OOM) anomalies
    in the logs of 'OOMBrand', and automatically proposes memory scale-up remediation Ops.
    """
    # 1. Prepare: Bootstrap a tenant and brand with the name 'OOMBrand'
    r = await client.post("/tenants", json={"name": "DiagSweepTenant", "brand_name": "OOMBrand"})
    assert r.status_code == 200
    data = r.json()
    tid, bid = data["tenant_id"], data["brand_id"]

    # Seed a TrustSnapshot to establish Tier 2 (Autonomous) so that the sweep Op auto-approves
    snapshot = TrustSnapshot(
        tenant_id=tid,
        brand_id=bid,
        domain="manage",
        score=100.0,
        tier=2,
        ts=dt.datetime.now(dt.timezone.utc)
    )
    session.add(snapshot)
    await session.commit()

    # 2. Act: Trigger the periodic diagnostics logs sweep task endpoint
    r_sweep = await client.post("/tasks/run-diagnostics")
    assert r_sweep.status_code == 200, r_sweep.text
    assert r_sweep.json()["status"] == "ok"

    # Drain the outbox to execute the auto-approved manage.diagnostics.check Op!
    r_drain = await client.post("/tasks/drain-outbox")
    assert r_drain.status_code == 200, r_drain.text

    # 3. Assert: Verify that a diagnostics check occurred and enqueued a scale memory remediation Op!
    stmt = select(OpRow).where(
        OpRow.tenant_id == tid,
        OpRow.brand_id == bid,
        OpRow.action == "provision.scale_memory.apply",
        OpRow.state == "PROPOSED"
    )
    res = await session.execute(stmt)
    remediations = res.scalars().all()
    
    assert len(remediations) == 1, "Should have created exactly 1 scale_memory remediation Op"
    scale_op = remediations[0]
    assert scale_op.params["memory"] == "1Gi"
    assert scale_op.params["recipe"] == "web-host"
    assert "Increase Cloud Run instance memory limit to 1Gi" in scale_op.preview_summary
