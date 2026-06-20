import pytest
import subprocess
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_recipe_promotion_sibling_directory_bypass_is_blocked(client, monkeypatch, tmp_path):
    # Mock git subprocess run to prevent actual git commands
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b"Mocked Git Success", stderr=b""))
    monkeypatch.setattr("app.main.subprocess.run", mock_run)
    
    # Redirect RECIPES_ROOT to isolated tmp_path / "recipes"
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.main.RECIPES_ROOT", str(recipes_dir))

    H = {"X-Tenant-Id": "t1"}

    # Set up source (experimental) path inside the recipes root
    # Since recipe_name is "../recipes-sibling/exploit" and version is "0.1.0",
    # experimental_path resolves to RECIPES_ROOT / "experimental" / "../recipes-sibling/exploit" / "0.1.0"
    # which is RECIPES_ROOT / "recipes-sibling" / "exploit" / "0.1.0"
    exp_dir = recipes_dir / "recipes-sibling" / "exploit" / "0.1.0"
    exp_dir.mkdir(parents=True, exist_ok=True)
    
    # Write required files
    with open(exp_dir / "recipe.yaml", "w") as f:
        f.write("recipe content")
    with open(exp_dir / "main.tf", "w") as f:
        f.write("terraform content")

    # Attempt sibling directory bypass in recipe name (starts with "recipes")
    # This should be BLOCKED with a 400 status code because it traverses to a sibling directory!
    r = await client.post("/recipes/promote", headers=H, json={
        "recipe_name": "../recipes-sibling/exploit",
        "version": "0.1.0"
    })
    
    assert r.status_code == 400, f"Expected 400 Bad Request, but got {r.status_code}. Sibling directory bypass succeeded!"
    assert "Invalid path traversal" in r.json()["detail"]
