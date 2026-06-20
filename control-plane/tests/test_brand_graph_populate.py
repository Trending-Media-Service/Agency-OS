import pytest
from httpx import AsyncClient
from sqlalchemy import select
import datetime as dt

from app.models import BrandProperty, Connection, TrustSnapshot
from app.services.secrets import SecretManagerClient
from app.tasks.sense import run_brand_sense

@pytest.mark.asyncio
async def test_brand_graph_sense_and_populate_e2e(client: AsyncClient, session):
    # 1. Onboard a new tenant and brand
    r = await client.post("/tenants", json={"name": "Organics Lab", "brand_name": "Organics Store"})
    assert r.status_code == 200
    res_data = r.json()
    tid = res_data["tenant_id"]
    bid = res_data["brand_id"]
    H = {"X-Tenant-ID": tid}

    # Set brand to Tier 2 (autonomous) for 'manage' domain to allow auto-approval of Sense Op
    snap = TrustSnapshot(
        tenant_id=tid,
        brand_id=bid,
        domain="manage",
        tier=2,
        score=95.0,
        ts=dt.datetime.now(dt.timezone.utc)
    )
    session.add(snap)
    await session.commit()

    # 2. Get initial Brand Graph (no connections exist and no Sense has run yet)
    # The GET endpoint is strictly read-only and does not mutate state or run Sense on-the-fly.
    # It should return an empty list initially.
    graph_res = await client.get(f"/brands/{bid}/graph", headers=H)
    assert graph_res.status_code == 200
    properties = graph_res.json()
    assert len(properties) == 0

    # 3. Establish connections for shopify and google in the DB
    secrets_client = SecretManagerClient()
    shopify_token_ref = await secrets_client.write_secret(f"{tid}-{bid}-shopify-secret", "shpat_test_token_123")
    google_token_ref = await secrets_client.write_secret(f"{tid}-{bid}-google-secret", "mock-google-token")
    
    shopify_conn = Connection(
        tenant_id=tid,
        brand_id=bid,
        provider="shopify",
        credential=shopify_token_ref,
        scope="read",
        config={"url": "organics-store.myshopify.com", "mcp_server_url": "https://mcp-shopify.run.app"},
        status="active"
    )
    google_conn = Connection(
        tenant_id=tid,
        brand_id=bid,
        provider="google",
        credential=google_token_ref,
        scope="search_console,merchant_center",
        config={"scopes": ["search_console", "merchant_center"]},
        status="active"
    )
    session.add_all([shopify_conn, google_conn])
    await session.commit()

    # 4. Explicitly run the Brand Sense background task!
    # This task runner proposes and executes the 'manage.brand.sense' Op,
    # populating the properties in the database under a governed transaction.
    await run_brand_sense(session, tid, bid)
    await session.commit()

    # 5. Fetch the Brand Graph again!
    # The GET endpoint now reads the populated properties from the database and returns them.
    graph_res2 = await client.get(f"/brands/{bid}/graph", headers=H)
    assert graph_res2.status_code == 200
    properties2 = graph_res2.json()
    
    # We expect 6 properties to be created and returned:
    # ux_analytics, search_console, merchant_feed, presence_audit, pr_monitoring, brand_performance_weights
    assert len(properties2) == 6
    prop_types2 = {p["type"]: p for p in properties2}
    
    # Verify Shopify/UX property is connected with findings
    assert prop_types2["ux_analytics"]["status"] == "connected"
    assert prop_types2["ux_analytics"]["connection_ref"] == shopify_token_ref
    assert "conversion_rate" in prop_types2["ux_analytics"]["findings"]
    
    # Verify Google properties are connected with findings
    assert prop_types2["search_console"]["status"] == "connected"
    assert prop_types2["search_console"]["connection_ref"] == google_token_ref
    assert prop_types2["search_console"]["findings"]["indexing_rate"] == 0.95
    
    assert prop_types2["merchant_feed"]["status"] == "connected"
    assert prop_types2["merchant_feed"]["connection_ref"] == google_token_ref
    assert prop_types2["merchant_feed"]["findings"]["active_products"] == 42
    
    assert prop_types2["presence_audit"]["status"] == "connected"
    assert prop_types2["presence_audit"]["connection_ref"] == google_token_ref

    # 6. Test RLS Isolation Boundaries
    H_cross = {"X-Tenant-ID": "tenant_cross_999"}
    cross_res = await client.get(f"/brands/{bid}/graph", headers=H_cross)
    assert cross_res.status_code == 404  # Not found under cross-tenant RLS context!
