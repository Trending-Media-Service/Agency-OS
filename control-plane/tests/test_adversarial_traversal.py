import pytest
import os
import shutil
import tempfile
from unittest.mock import MagicMock

from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.mark.asyncio
async def test_sibling_directory_traversal(client, monkeypatch, tmp_path):
    import subprocess
    from unittest.mock import MagicMock

    # Mock git subprocess run
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b"Mocked Git Success", stderr=b""))
    monkeypatch.setattr("app.main.subprocess.run", mock_run)
    
    # Redirect RECIPES_ROOT to isolated tmp_path / "recipes"
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    monkeypatch.setattr("app.main.RECIPES_ROOT", str(recipes_dir))

    # Sibling directory that starts with recipes_dir prefix
    sibling_dir = tmp_path / "recipes-sibling"

    # Create the experimental recipe at the path where experimental_path resolves:
    # recipes_dir/experimental/../recipes-sibling/exploit/0.1.0 -> recipes_dir/recipes-sibling/exploit/0.1.0
    exp_recipe_dir = recipes_dir / "recipes-sibling" / "exploit" / "0.1.0"
    exp_recipe_dir.mkdir(parents=True, exist_ok=True)
    with open(exp_recipe_dir / "recipe.yaml", "w") as f:
        f.write("name: exploit\nversion: 0.1.0")
    with open(exp_recipe_dir / "main.tf", "w") as f:
        f.write("output \"exploit\" { value = 1 }")

    # Call the promote endpoint with the sibling traversal payload
    H = {"X-Tenant-Id": "t1"}
    r = await client.post("/recipes/promote", headers=H, json={
        "recipe_name": "../recipes-sibling/exploit",
        "version": "0.1.0"
    })

    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

    # Assert that sibling directory traversal is blocked and returns 400 Bad Request
    assert r.status_code == 400
    assert "Invalid path traversal" in r.json()["detail"]
    assert not (sibling_dir / "exploit" / "0.1.0" / "recipe.yaml").exists()


@pytest.mark.asyncio
async def test_provision_adapter_path_traversal_rce(tmp_path, monkeypatch):
    # 1. Create an attacker-controlled directory outside RECIPES_ROOT
    attacker_dir = tmp_path / "attacker_controlled"
    attacker_dir.mkdir()
    
    # Write a malicious checks.py file
    sentinel_file = tmp_path / "rce_executed.txt"
    checks_code = f"""
def verify(params, outputs):
    with open(r"{sentinel_file}", "w") as f:
        f.write("RCE Success")
    return {{"rce_check": True}}
"""
    with open(attacker_dir / "checks.py", "w") as f:
        f.write(checks_code)
        
    # Also write a dummy main.tf and recipe.yaml to satisfy any basic file checks if needed
    with open(attacker_dir / "recipe.yaml", "w") as f:
        f.write("name: malicious\nversion: 0.1.0")
    with open(attacker_dir / "main.tf", "w") as f:
        f.write("output \"malicious\" { value = 1 }")

    # 2. Set up ProvisionAdapter with a known RECIPES_ROOT
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    
    # We want to traverse from recipes_dir to attacker_dir
    # Relative path from recipes_dir to attacker_dir:
    # since both are under tmp_path, we can use "../attacker_controlled"
    
    adapter = ProvisionAdapter()
    
    # Monkeypatch RECIPES_ROOT inside app.adapters.provision
    monkeypatch.setattr("app.adapters.provision.RECIPES_ROOT", str(recipes_dir))

    # 3. Create OpSpec with path traversal in 'recipe'
    op = OpSpec(
        id="op_malicious",
        tenant_id="t1",
        brand_id="b1",
        domain="provision",
        action="provision.malicious.create",
        params={
            "recipe": "../attacker_controlled",
            "version": "."
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR"),
    )

    # 4. Call verify (which loads checks.py dynamically)
    # Note: we need to mock the terraform output command or run it,
    # but verify in conftest's mock_terraform_cli will intercept 'terraform' run
    # and return a mock output. Let's see if conftest mock_terraform_cli works.
    # In conftest.py, mock_terraform_cli intercepts subprocess.run for "terraform"
    # and returns a mock result based on the recipe. Since our recipe is "../attacker_controlled",
    # it won't match any specific recipe name and will return output={}.
    
    # Assert that path traversal attempt raises ValueError and RCE is blocked
    with pytest.raises(ValueError) as excinfo:
        await adapter.verify(op)
    assert "Invalid path traversal" in str(excinfo.value)
    assert not sentinel_file.exists()
