import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from app.adapters.build_agent import BuildAgentHarness
from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.mark.asyncio
@patch("app.services.llm.VertexAIClient.generate_edits")
async def test_build_agent_harness_path_traversal(mock_generate, tmp_path):
    # Setup a dummy local git repository to clone
    remote_dir = tmp_path / "remote_repo"
    remote_dir.mkdir()
    
    # Initialize git repo and commit a dummy file
    import subprocess
    subprocess.run(["git", "init"], cwd=remote_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=remote_dir, check=True)
    
    dummy_file = remote_dir / "README.md"
    with open(dummy_file, "w") as f:
        f.write("# Dummy Repo")
    subprocess.run(["git", "add", "README.md"], cwd=remote_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=remote_dir, check=True)

    # Setup mock LLM response with a path traversal edit
    # We attempt to write a file outside the repository directory (which is temp_dir/repo)
    # temp_dir is /tmp/.../
    # repo is /tmp/.../repo/
    # So "../../outside_exploit.txt" should be written to /tmp/.../outside_exploit.txt
    mock_generate.return_value = {
        "explanation": "Attempt path traversal",
        "edits": [
            {
                "path": "../../outside_exploit.txt",
                "action": "create",
                "content": "EXPLOIT_SUCCESSFUL"
            }
        ]
    }

    branch_name = "exploit-branch"
    with BuildAgentHarness(repo_url=str(remote_dir), branch_name=branch_name) as harness:
        assert harness.clone_and_checkout() is True
        
        # Apply the edits
        # Since path traversal is blocked, apply_edits should return False (due to ValueError)
        assert harness.apply_edits("inject exploit") is False
        
        # Verify the file was NOT written to the traversal path
        expected_traversal_path = os.path.abspath(os.path.join(harness.repo_path, "../../outside_exploit.txt"))
        assert not os.path.exists(expected_traversal_path), "VULNERABILITY: Path traversal file WAS created!"
        print("\n[SUCCESS] Path traversal vulnerability successfully blocked!")


def test_provision_adapter_name_error_under_gcs(tmp_path, monkeypatch):
    # Setup isolated recipes root
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    
    # Create a dummy recipe
    recipe_dir = recipes_dir / "web-host" / "0.1.0"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    with open(recipe_dir / "recipe.yaml", "w") as f:
        f.write("inputs:\n  domain: {}\n")
    with open(recipe_dir / "main.tf", "w") as f:
        f.write("resource \"random_id\" \"id\" {}\n")
        
    adapter = ProvisionAdapter()
    monkeypatch.setattr("app.adapters.provision.RECIPES_ROOT", str(recipes_dir))
    
    # Set the environment variable AOS_STATE_BUCKET to trigger the GCS backend block
    monkeypatch.setenv("AOS_STATE_BUCKET", "my-test-state-bucket")
    
    op = OpSpec(
        id="op_test",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.web_host.create",
        params={"domain": "test.com", "recipe": "web-host", "version": "0.1.0"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    
    # When _prepare_dir is called, it should execute successfully without raising NameError
    with tempfile.TemporaryDirectory() as temp_dir:
        adapter._prepare_dir(op, temp_dir)
        # Verify that the recipe folder files (like main.tf) are copied and backend.tf is prepared
        assert os.path.exists(os.path.join(temp_dir, "main.tf"))
        assert os.path.exists(os.path.join(temp_dir, "backend.tf"))
        print("\n[SUCCESS] NameError bug successfully resolved in _prepare_dir!")
