import os
import yaml
import pytest

def test_github_actions_workflow_syntax_and_security():
    workflow_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.github/workflows/deploy.yml"))
    assert os.path.exists(workflow_path), f"CD workflow file does not exist at {workflow_path}"
    
    with open(workflow_path, "r") as f:
        workflow = yaml.safe_load(f)
        
    assert workflow is not None
    assert workflow["name"] == "Cloud Run CD"
    
    # Verify trigger
    triggers = workflow.get("on") or workflow.get(True) or {}
    assert "push" in triggers
    assert "main" in triggers["push"].get("branches", [])
    
    # Verify permissions for Workload Identity Federation
    jobs = workflow.get("jobs", {})
    assert "deploy" in jobs
    permissions = jobs["deploy"].get("permissions", {})
    assert permissions.get("id-token") == "write", "id-token: write permission is required for WIF authentication!"
    assert permissions.get("contents") == "read"
    
    # Verify key CD steps are present
    steps = jobs["deploy"].get("steps", [])
    assert len(steps) > 0
    
    uses_clauses = [step.get("uses") for step in steps if "uses" in step]
    assert any(u.startswith("actions/checkout") for u in uses_clauses)
    assert any(u.startswith("google-github-actions/auth") for u in uses_clauses), "google-github-actions/auth is required for WIF!"
    assert any(u.startswith("google-github-actions/deploy-cloudrun") for u in uses_clauses), "google-github-actions/deploy-cloudrun is required!"


def test_github_actions_ci_workflow():
    workflow_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.github/workflows/ci.yml"))
    assert os.path.exists(workflow_path), f"CI workflow file does not exist at {workflow_path}"
    
    with open(workflow_path, "r") as f:
        workflow = yaml.safe_load(f)
        
    assert workflow is not None
    assert workflow["name"] == "ci"
    
    jobs = workflow.get("jobs", {})
    assert "tests" in jobs
    steps = jobs["tests"].get("steps", [])
    
    # Check that it runs pytest with coverage and NOT in quiet mode (-q)
    pytest_step = None
    for step in steps:
        if step.get("name") == "Kernel test suite":
            pytest_step = step
            break
            
    assert pytest_step is not None, "Kernel test suite step must be present!"
    run_cmd = pytest_step.get("run", "")
    assert "pytest" in run_cmd
    assert "-q" not in run_cmd, "The quiet flag (-q) must be removed to output the full coverage table in CI logs!"

