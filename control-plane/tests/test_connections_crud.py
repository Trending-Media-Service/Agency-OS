import pytest
from httpx import AsyncClient
from app.models import Connection

@pytest.mark.asyncio
async def test_connections_crud_endpoints(client: AsyncClient, session):
    # 1. Create tenant and brand
    r = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert r.status_code == 200
    tid = r.json()["tenant_id"]
    bid = r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    # 2. List connections - should be empty initially
    r = await client.get("/connections", headers=H)
    assert r.status_code == 200
    assert len(r.json()) == 0

    # 3. Create a connection manually
    conn_data = {
        "brand_id": bid,
        "provider": "google-ads",
        "scope": "read,write",
        "secret_ref": "projects/test-project/secrets/google-ads-token",
        "config": {"client_id": "12345"}
    }
    r = await client.post("/connections", headers=H, json=conn_data)
    assert r.status_code == 201
    created_conn = r.json()
    assert created_conn["brand_id"] == bid
    assert created_conn["provider"] == "google-ads"
    assert created_conn["scope"] == "read,write"
    assert created_conn["secret_ref"] == "projects/test-project/secrets/google-ads-token"
    assert created_conn["config"] == {"client_id": "12345"}
    assert "id" in created_conn

    conn_id = created_conn["id"]

    # 4. List connections - should now have 1 connection
    r = await client.get("/connections", headers=H)
    assert r.status_code == 200
    conns = r.json()
    assert len(conns) == 1
    assert conns[0]["id"] == conn_id

    # 5. Update the connection
    update_data = {
        "scope": "read",
        "secret_ref": "projects/test-project/secrets/google-ads-token-v2",
        "config": {"client_id": "12345", "developer_token": "dev123"}
    }
    r = await client.put(f"/connections/{conn_id}", headers=H, json=update_data)
    assert r.status_code == 200
    updated_conn = r.json()
    assert updated_conn["scope"] == "read"
    assert updated_conn["secret_ref"] == "projects/test-project/secrets/google-ads-token-v2"
    assert updated_conn["config"] == {"client_id": "12345", "developer_token": "dev123"}

    # 6. Delete the connection
    r = await client.delete(f"/connections/{conn_id}", headers=H)
    assert r.status_code == 200
    assert r.json() == {"status": "deleted", "id": conn_id}

    # 7. List connections - should be empty again
    r = await client.get("/connections", headers=H)
    assert r.status_code == 200
    assert len(r.json()) == 0


@pytest.mark.asyncio
async def test_connections_validation(client: AsyncClient):
    # 1. Create tenant A and brand A
    r = await client.post("/tenants", json={"name": "Tenant A", "brand_name": "Brand A"})
    tid_a = r.json()["tenant_id"]
    bid_a = r.json()["brand_id"]
    
    # 2. Create tenant B and brand B
    r = await client.post("/tenants", json={"name": "Tenant B", "brand_name": "Brand B"})
    tid_b = r.json()["tenant_id"]
    bid_b = r.json()["brand_id"]

    # Try to create connection in Tenant A referencing Brand B (should fail)
    conn_data = {
        "brand_id": bid_b,
        "provider": "meta-ads",
        "secret_ref": "some-ref"
    }
    r = await client.post("/connections", headers={"X-Tenant-ID": tid_a}, json=conn_data)
    assert r.status_code == 404
    assert "Brand not found for this tenant" in r.json()["detail"]
