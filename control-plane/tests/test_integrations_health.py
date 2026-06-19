import pytest
from httpx import AsyncClient
from app.integrations import get_provider_adapter


def test_provider_adapter_factory():
    # Verify we can resolve MetaAdapter
    meta_adapter = get_provider_adapter("meta-ads", {"token": "mock-token", "ad_account_id": "123"})
    assert meta_adapter.provider_name == "meta"
    
    # Verify we can resolve stubs (e.g. Stripe)
    stripe_adapter = get_provider_adapter("stripe", {"token": "mock-stripe-token"})
    assert stripe_adapter.provider_name == "stripe"
    
    # Verify unsupported provider raises ValueError
    with pytest.raises(ValueError):
        get_provider_adapter("unknown-provider", {})


@pytest.mark.asyncio
async def test_integrations_health_endpoint(client: AsyncClient, session):
    # 1. Create tenant and brand
    r = await client.post("/tenants", json={"name": "Attribution Co", "brand_name": "Attribution Brand"})
    assert r.status_code == 200
    tid = r.json()["tenant_id"]
    bid = r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    # 2. Create a Meta Ads connection (uses the fully fleshed MetaAdapter)
    meta_conn = {
        "brand_id": bid,
        "provider": "meta",
        "secret_ref": "mock-meta-token",
        "config": {"ad_account_id": "act_99999"}
    }
    r = await client.post("/connections", headers=H, json=meta_conn)
    assert r.status_code == 201

    # 3. Create a Google Ads connection (uses GoogleAdsAdapter stub)
    google_conn = {
        "brand_id": bid,
        "provider": "google-ads",
        "secret_ref": "mock-google-token",
        "config": {"developer_token": "dev_token_stub"}
    }
    r = await client.post("/connections", headers=H, json=google_conn)
    assert r.status_code == 201

    # 4. Call health check endpoint
    r = await client.get("/health/integrations", headers=H)
    assert r.status_code == 200
    
    health_results = r.json()
    assert len(health_results) == 2
    
    # Verify Meta health status
    meta_res = next(x for x in health_results if x["provider"] == "meta")
    assert meta_res["is_healthy"] is True
    assert meta_res["status_code"] == 200
    assert "last_checked" in meta_res
    
    # Verify Google Ads health status
    google_res = next(x for x in health_results if x["provider"] == "google-ads")
    assert google_res["is_healthy"] is True
    assert google_res["status_code"] == 200
    assert "last_checked" in google_res
