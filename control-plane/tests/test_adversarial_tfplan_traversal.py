import os
import pytest
from unittest.mock import MagicMock

from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.mark.asyncio
async def test_provision_adapter_tfplan_path_traversal(tmp_path, monkeypatch):
    # Setup recipes root
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    
    # Create a dummy static-host recipe
    recipe_dir = recipes_dir / "static-host" / "0.1.0"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    with open(recipe_dir / "recipe.yaml", "w") as f:
        f.write("name: static-host\nversion: 0.1.0")
    with open(recipe_dir / "main.tf", "w") as f:
        f.write("output \"static_host\" { value = 1 }")

    adapter = ProvisionAdapter()
    monkeypatch.setattr("app.adapters.provision.RECIPES_ROOT", str(recipes_dir))

    # We want to traverse from TFPLAN_DIR (tmp_path / "aos-tfplans") to tmp_path / "exploit_tfplan.tfplan"
    # base: tmp_path / "aos-tfplans"
    # target: tmp_path / "exploit_tfplan.tfplan"
    # We use tenant_id: "../../exploit_tfplan"
    try:
        op = OpSpec(
            id="op_traversal",
            tenant_id="../../exploit_tfplan",
            brand_id="b1",
            domain="provision",
            action="provision.static_host.create",
            params={
                "recipe": "static-host",
                "version": "0.1.0",
                "domain": "example.com",
                "bucket_name": "test-bucket",
                "project_id": "p1"
            },
            severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
            cost_estimate=Money(amount_minor=0, currency="INR"),
        )
    except ValueError as e:
        # If OpSpec validation raises ValueError, the path traversal is successfully blocked at construction!
        assert "Invalid" in str(e) or "traversal" in str(e) or "tenant_id" in str(e)
        traversal_file = tmp_path / "exploit_tfplan-b1-static-host-default.tfplan"
        assert not traversal_file.exists(), f"Path traversal succeeded! File written to: {traversal_file}"
        return

    # Call preview
    artifact = adapter.preview(op)
    
    # Check if the traversal file was written
    traversal_file = tmp_path / "exploit_tfplan-b1-static-host-default.tfplan"
    
    # If the file exists, the path traversal succeeded!
    # A secure implementation should have blocked this (either raising ValueError or returning an error artifact)
    assert not traversal_file.exists(), f"Path traversal succeeded! File written to: {traversal_file}"
    assert "Invalid path traversal" in artifact.summary or "error" in artifact.kind


@pytest.mark.asyncio
async def test_api_intent_brand_id_path_traversal(client, session, tmp_path, monkeypatch):
    # Setup recipes root
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    
    # Create a dummy static-host recipe
    recipe_dir = recipes_dir / "static-host" / "0.1.0"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    with open(recipe_dir / "recipe.yaml", "w") as f:
        f.write("name: static-host\nversion: 0.1.0")
    with open(recipe_dir / "main.tf", "w") as f:
        f.write("output \"static_host\" { value = 1 }")

    monkeypatch.setattr("app.adapters.provision.RECIPES_ROOT", str(recipes_dir))

    from app.models import Tenant
    # Seed a valid tenant in the DB to satisfy any foreign key checks on tenant_id
    tenant = Tenant(id="t1", name="Test Tenant")
    session.add(tenant)
    await session.commit()

    # We make a POST request to /intents
    # tenant_id (via header) is "t1" (valid)
    # brand_id (in JSON body) is "../../../exploit_api" (malicious traversal)
    H = {"X-Tenant-Id": "t1", "Content-Type": "application/json"}
    r = await client.post("/intents", headers=H, json={
        "brand_id": "../../../exploit_api",
        "text": "provision static website for example.com",
        "domain": "provision"
    })
    
    # We check if the file was written to tmp_path / "exploit_api-static-host-default.tfplan"
    traversal_file = tmp_path / "exploit_api-static-host-default.tfplan"
    
    # We assert that the request was blocked with 400 Bad Request because of path traversal
    # If the file exists, the API-level path traversal succeeded!
    assert r.status_code == 400, f"Expected 400 Bad Request, but got {r.status_code}. Response: {r.text}"
    assert not traversal_file.exists(), f"API-level Path traversal succeeded! File written to: {traversal_file}"
