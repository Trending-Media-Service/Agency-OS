import os
import shutil
import tempfile
import subprocess
import pytest
from app.adapters.build_agent import BuildAgentHarness

def test_build_agent_harness_flow(temp_git_remote, run_git):
    branch_name = "test-agent-branch"
    intent = "change color to blue"
    
    with BuildAgentHarness(repo_url=temp_git_remote, branch_name=branch_name) as harness:
        # 1. Clone and checkout
        assert harness.clone_and_checkout() is True
        assert os.path.exists(os.path.join(harness.repo_path, "src/App.js"))
        
        # Verify we are on the new branch
        res = run_git(
            ["branch", "--show-current"],
            cwd=harness.repo_path, check=True, capture_output=True, text=True
        )
        assert res.stdout.strip() == branch_name
        
        # 2. Apply edits
        assert harness.apply_edits(intent) is True
        
        # Verify file was modified
        with open(os.path.join(harness.repo_path, "src/App.js"), "r") as f:
            content = f.read()
        assert "color=\"blue\"" in content
        
        # 3. Commit and push
        assert harness.commit_and_push() is True
        
        # Verify diff is generated
        diff = harness.get_diff()
        assert "color=\"blue\"" in diff
        assert "color=\"red\"" in diff

    # Verify that the branch was pushed to the remote repo
    temp_dir = tempfile.mkdtemp()
    try:
        run_git(["clone", temp_git_remote, temp_dir], check=True, capture_output=True)
        run_git(["checkout", branch_name], cwd=temp_dir, check=True, capture_output=True)
        with open(os.path.join(temp_dir, "src/App.js"), "r") as f:
            content = f.read()
        assert "color=\"blue\"" in content
    finally:
        shutil.rmtree(temp_dir)
