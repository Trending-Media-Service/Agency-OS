import pytest
import os
import tempfile
import shutil
from app.adapters.build import BuildAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.adapters.build_agent import BuildAgentHarness

@pytest.fixture
def adapter():
    return BuildAdapter()

@pytest.fixture
def build_op(temp_git_remote):
    return OpSpec(
        id="op_build_123",
        tenant_id="t1",
        brand_id="b1",
        domain="build",
        action="build.deliver",
        params={
            "intent": "change hero color to blue",
            "branch_name": "aos-build-test",
            "repo": temp_git_remote
        },
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(amount_minor=1000, currency="INR"),
    )

def test_build_adapter_plan(adapter):
    ops = adapter.plan("change hero color to blue", "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "build.deliver"
    assert "intent" in op.params
    assert op.params["intent"] == "change hero color to blue"
    assert "branch_name" in op.params
    assert op.cost_estimate.amount_minor == 1000

def test_build_adapter_preview(adapter, build_op):
    preview_art = adapter.preview(build_op)
    assert preview_art.kind == "build_preview"
    assert "Staging Preview" in preview_art.summary
    assert "diff" in preview_art.detail
    assert preview_art.detail["branch"] == "aos-build-test"

async def test_build_adapter_execute(adapter, build_op, temp_git_remote, run_git):
    branch_name = build_op.params["branch_name"]
    # 1. Prepare: Run harness to create and push the branch
    with BuildAgentHarness(repo_url=temp_git_remote, branch_name=branch_name) as harness:
        assert harness.clone_and_checkout() is True
        assert harness.apply_edits("some intent") is True
        assert harness.commit_and_push() is True
        
    # 2. Act: Execute merge
    res = await adapter.execute(build_op, "idem_build_123")
    
    # 3. Assert
    assert res.ok is True
    assert "prod_url" in res.detail
    
    # Verify it was merged on remote
    temp_dir = tempfile.mkdtemp()
    try:
        run_git(["clone", temp_git_remote, temp_dir], check=True, capture_output=True)
        with open(os.path.join(temp_dir, "src/App.js"), "r") as f:
            content = f.read()
        assert "color=\"blue\"" in content
    finally:
        shutil.rmtree(temp_dir)

@pytest.mark.asyncio
async def test_build_adapter_verify(adapter, build_op):
    res = await adapter.verify(build_op)
    assert res.ok is True
    assert res.checks["http_ok"] is True
    assert res.checks["version_match"] is True

def test_build_adapter_compensate(adapter, build_op):
    compensations = adapter.compensate(build_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "build.rollback"
    assert comp.parent_op_id == build_op.id
    assert comp.params["revert_branch"] == build_op.params["branch_name"]
    assert comp.params["repo"] == build_op.params["repo"]

async def test_build_adapter_rollback_execution(adapter, build_op, temp_git_remote, run_git):
    branch_name = build_op.params["branch_name"]
    # 1. Prepare: Run harness to create, push branch, and merge it
    with BuildAgentHarness(repo_url=temp_git_remote, branch_name=branch_name) as harness:
        assert harness.clone_and_checkout() is True
        assert harness.apply_edits("some intent") is True
        assert harness.commit_and_push() is True
        
    res_deliver = await adapter.execute(build_op, "idem_deliver_123")
    assert res_deliver.ok is True
    
    # Verify it was merged
    temp_dir = tempfile.mkdtemp()
    try:
        run_git(["clone", temp_git_remote, temp_dir], check=True, capture_output=True)
        with open(os.path.join(temp_dir, "src/App.js"), "r") as f:
            assert "color=\"blue\"" in f.read()
    finally:
        shutil.rmtree(temp_dir)
        
    # 2. Act: Get compensation Op and execute it
    compensations = adapter.compensate(build_op)
    rollback_op = compensations[0]
    
    res_rollback = await adapter.execute(rollback_op, "idem_rollback_123")
    assert res_rollback.ok is True
    
    # 3. Assert: Verify it was reverted on remote (color should be back to red)
    temp_dir = tempfile.mkdtemp()
    try:
        run_git(["clone", temp_git_remote, temp_dir], check=True, capture_output=True)
        with open(os.path.join(temp_dir, "src/App.js"), "r") as f:
            content = f.read()
        assert "color=\"red\"" in content
        assert "color=\"blue\"" not in content
    finally:
        shutil.rmtree(temp_dir)
