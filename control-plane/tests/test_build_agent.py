import os
import shutil
import tempfile
import subprocess
import pytest
from unittest.mock import patch
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


@pytest.mark.asyncio
@patch("app.services.llm.VertexAIClient.generate_edits")
async def test_build_agent_harness_dynamic_edits(mock_generate, temp_git_remote, run_git):
    from unittest.mock import patch
    branch_name = "test-agent-dynamic"
    
    # 1. Setup mock response to create a new file and delete an existing one
    mock_generate.return_value = {
        "explanation": "Create new helper and clean old code",
        "edits": [
            {
                "path": "src/Helper.js",
                "action": "create",
                "content": "export const help = () => 'done';"
            },
            {
                "path": "src/App.js",
                "action": "delete",
                "content": ""
            }
        ]
    }
    
    with BuildAgentHarness(repo_url=temp_git_remote, branch_name=branch_name) as harness:
        assert harness.clone_and_checkout() is True
        assert harness.apply_edits("do updates") is True
        
        # Verify Helper.js was created
        assert os.path.exists(os.path.join(harness.repo_path, "src/Helper.js"))
        with open(os.path.join(harness.repo_path, "src/Helper.js"), "r") as f:
            assert f.read() == "export const help = () => 'done';"
            
        # Verify App.js was deleted
        assert not os.path.exists(os.path.join(harness.repo_path, "src/App.js"))


def test_build_agent_harness_url_token_injection():
    with patch("app.adapters.build_agent.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        
        repo_url = "https://git.example.com/Trending-Media-Service/Agency-OS.git"
        token = "ghp_mock_token_12345"
        
        harness = BuildAgentHarness(repo_url=repo_url, branch_name="test-branch", access_token=token)
        
        with harness:
            harness.clone_and_checkout()
            
        # Verify the clone command URL contains the token
        called_args = mock_run.call_args_list[0][0][0]
        assert "git" in called_args
        assert "clone" in called_args
        assert f"https://{token}@git.example.com/Trending-Media-Service/Agency-OS.git" in called_args
