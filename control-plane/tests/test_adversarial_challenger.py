import pytest
import subprocess
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_regex_newline_bypass_in_promote(client, monkeypatch, tmp_path):
    # Mock git subprocess run to prevent actual git commands
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b"Mocked Git Success", stderr=b""))
    monkeypatch.setattr("app.main.subprocess.run", mock_run)
    
    # Redirect RECIPES_ROOT to isolated tmp_path / "recipes"
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.main.RECIPES_ROOT", str(recipes_dir))

    H = {"Authorization": "Bearer default-dev-token", "X-Tenant-Id": "t1"}

    # We pass recipe_name with a trailing newline: "exploit\n"
    # and version with a trailing newline: "0.1.0\n"
    # If the regex check fails, it returns 400 Bad Request with "Invalid path traversal".
    # If the regex check is bypassed, it will proceed to check if the path exists.
    # Since the path does not exist, it will return 404 Not Found.
    r = await client.post("/recipes/promote", headers=H, json={
        "recipe_name": "exploit\n",
        "version": "0.1.0\n"
    })
    
    # Assert that the regex check successfully blocked the trailing newline bypass!
    assert r.status_code == 400, f"Expected 400 Bad Request indicating the regex successfully blocked the newline exploit, but got {r.status_code}. Response: {r.text}"
    assert "invalid path traversal" in r.text.lower()


@pytest.mark.asyncio
async def test_sense_endpoint_not_found(client):
    H = {"X-Tenant-Id": "t1"}
    
    # Attempt to trigger the claimed POST /brands/{brand_id}/sense endpoint
    r = await client.post("/brands/brand-123/sense", headers=H, json={})
    
    # Assert that it returns 404 because the brand does not exist
    assert r.status_code == 404, f"Expected 404 Not Found for missing brand, but got {r.status_code}"


@pytest.mark.asyncio
async def test_sense_endpoint_success(client, session):
    from app.models import Tenant, Brand, TrustSnapshot
    
    # Seed Tenant & Brand
    tenant = Tenant(id="t_sense", name="Sense Tenant", hosting_tier="shared")
    brand = Brand(id="b_sense", tenant_id="t_sense", name="Sense Brand")
    session.add(tenant)
    session.add(brand)
    
    # Seed TrustSnapshot for manage domain to be Tier 2 (autonomous)
    session.add(TrustSnapshot(
        tenant_id="t_sense", brand_id="b_sense", domain="manage", tier=2, score=95.0
    ))
    await session.commit()

    H = {"X-Tenant-Id": "t_sense"}
    r = await client.post("/brands/b_sense/sense", headers=H, json={})
    assert r.status_code == 200, f"Expected 200 OK, got {r.status_code}. Response: {r.text}"
    assert r.json()["status"] == "accepted"
