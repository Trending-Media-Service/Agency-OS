# tests/test_onboarding_flow.py
import pytest
import os
import json
import httpx
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Tenant, Brand, Connection, BrandProperty
from app.services.oauth import generate_oauth_state, verify_oauth_state
from app.routers.onboarding import bootstrap_brand_identity_task

@pytest.fixture
def clean_env():
    old_env = os.environ.copy()
    os.environ["SHOPIFY_CLIENT_ID"] = "test-shopify-id"
    os.environ["SHOPIFY_CLIENT_SECRET"] = "test-shopify-secret"
    os.environ["GOOGLE_CLIENT_ID"] = "test-google-id"
    os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-secret"
    os.environ["AOS_ENV"] = "test"
    yield
    os.environ.clear()
    os.environ.update(old_env)

@pytest.mark.asyncio
async def test_onboarding_bootstrap(client, session: AsyncSession):
    # Test POST /api/v1/onboarding/bootstrap (using async client fixture!)
    resp = await client.post("/api/v1/onboarding/bootstrap?name=LuxeDecor&domain=luxedecor.com&tier=dedicated")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "onboarding_ready"
    assert data["tier"] == "dedicated"
    
    # Verify Tenant and Brand were seeded in database
    stmt_tenant = select(Tenant).where(Tenant.id == data["tenant_id"])
    res_tenant = await session.execute(stmt_tenant)
    tenant = res_tenant.scalar_one_or_none()
    assert tenant is not None
    assert tenant.name == "LuxeDecor"
    assert tenant.hosting_tier == "dedicated"
    
    stmt_brand = select(Brand).where(Brand.id == data["brand_id"])
    res_brand = await session.execute(stmt_brand)
    brand = res_brand.scalar_one_or_none()
    assert brand is not None
    assert brand.name == "LuxeDecor"

@pytest.mark.asyncio
async def test_onboarding_oauth_authorize(clean_env, client):
    # Test GET /api/v1/onboarding/oauth/authorize/shopify
    resp = await client.get(
        "/api/v1/onboarding/oauth/authorize/shopify?"
        "tenant_id=t-1&brand_id=b-1&redirect_uri=http://localhost/callback"
    )
    # FastAPI RedirectResponse returns 307
    assert resp.status_code == 307 or resp.status_code == 200
    redirect_url = resp.headers.get("location") or resp.url
    assert "b-1.myshopify.com/admin/oauth/authorize" in str(redirect_url)
    assert "client_id=test-shopify-id" in str(redirect_url)
    assert "state=" in str(redirect_url)
    
    # Extract state from redirect URL to verify signature
    import urllib.parse as urlparse
    parsed = urlparse.urlparse(str(redirect_url))
    queries = urlparse.parse_qs(parsed.query)
    state_token = queries["state"][0]
    
    payload = verify_oauth_state(state_token)
    assert payload["tenant_id"] == "t-1"
    assert payload["brand_id"] == "b-1"
    assert payload["provider"] == "shopify"

@pytest.mark.asyncio
@patch("app.services.oauth.SecretManagerClient")
async def test_onboarding_oauth_callback(mock_secrets_cls, clean_env, client, session: AsyncSession):
    # 1. Seed Tenant and Brand first
    tenant = Tenant(id="t-2", name="FitWear", hosting_tier="shared")
    brand = Brand(id="b-2", tenant_id="t-2", name="FitWear")
    session.add(tenant)
    session.add(brand)
    await session.commit()
    
    # Mock Secret Manager client behavior
    mock_secrets = MagicMock()
    mock_secrets.write_secret = AsyncMock(side_effect=lambda sid, val: f"projects/test/secrets/{sid}/versions/1")
    mock_secrets_cls.return_value = mock_secrets
    
    # Generate valid state token
    state = generate_oauth_state(tenant_id="t-2", brand_id="b-2", redirect_uri="http://localhost/callback", provider="shopify")
    
    # Mock Shopify Access Token HTTP post response
    with patch("httpx.AsyncClient.post") as mock_post, \
         patch("app.routers.onboarding.bootstrap_brand_identity_task") as mock_bg_task:
         
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "shpat_mocked_token_123456",
            "scope": "read_products"
        }
        mock_post.return_value = mock_resp
        
        # Call the callback redirect endpoint
        resp = await client.get(f"/api/v1/onboarding/oauth/callback?code=code-abc-123&state={state}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connection_established"
        assert data["provider"] == "shopify"
        
        # Verify Connection row was seeded in database
        stmt_conn = select(Connection).where(
            Connection.tenant_id == "t-2",
            Connection.brand_id == "b-2",
            Connection.provider == "shopify"
        )
        res_conn = await session.execute(stmt_conn)
        conn = res_conn.scalar_one_or_none()
        assert conn is not None
        assert conn.status == "active"
        assert "t-2-b-2-shopify-secret" in conn.credential
        
        # Verify background catalog RAG bootstrapping task was triggered
        mock_bg_task.assert_called_once()
        args = mock_bg_task.call_args[0]
        assert args[:3] == ("t-2", "b-2", "shpat_mocked_token_123456")

@pytest.mark.asyncio
async def test_onboarding_connection_direct(client, session: AsyncSession):
    # Test POST /api/v1/onboarding/connection/direct for Klaviyo API key
    with patch("app.services.oauth.SecretManagerClient") as mock_secrets_cls:
        mock_secrets = MagicMock()
        mock_secrets.write_secret = AsyncMock(return_value="projects/test/secrets/t-3-b-3-klaviyo-secret/versions/1")
        mock_secrets_cls.return_value = mock_secrets
        
        resp = await client.post(
            "/api/v1/onboarding/connection/direct?"
            "tenant_id=t-3&brand_id=b-3&provider=klaviyo&api_key=pk_test_klaviyo_key_987"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "direct_connection_established"
        assert resp.json()["provider"] == "klaviyo"
        
        # Verify Connection table contains the active row
        stmt_conn = select(Connection).where(
            Connection.tenant_id == "t-3",
            Connection.brand_id == "b-3",
            Connection.provider == "klaviyo"
        )
        res_conn = await session.execute(stmt_conn)
        conn = res_conn.scalar_one_or_none()
        assert conn is not None
        assert conn.status == "active"
        assert conn.credential == "projects/test/secrets/t-3-b-3-klaviyo-secret/versions/1"

@pytest.mark.asyncio
@patch("app.services.llm.VertexAIClient")
async def test_bootstrap_brand_identity_task(mock_llm_cls, clean_env, db_engine, session: AsyncSession):
    # Mock Shopify catalog products fetch
    shopify_products_response = {
        "products": [
            {
                "title": "Weighted Sensory Blanket",
                "product_type": "Sensory Toy",
                "body_html": "<p>Empathy-centered calming blanket for sensory seeking toddlers.</p>"
            },
            {
                "title": "Noise Cancelling Toddler Headphones",
                "product_type": "Hearing Protection",
                "body_html": "<p>Sensory-friendly hearing protection for hyper-acusis children.</p>"
            }
        ]
    }
    
    # Mock Gemini brand identity synthesis response
    gemini_identity_response = {
        "tone_of_voice": "Empathetic, sensory-friendly, clinical",
        "target_persona": "Parents of sensory-seeking children, neurodivergent families",
        "past_experience": "Avoid using aggressive words like 'Discounts'."
    }
    
    # Setup Mock LLM client
    mock_llm = MagicMock()
    async def mock_generate(*args, **kwargs):
        return json.dumps(gemini_identity_response)
    mock_llm.generate_personalized_content.side_effect = mock_generate
    mock_llm_cls.return_value = mock_llm
    
    # Mock the HTTPX GET call to Shopify Admin API
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = shopify_products_response
        mock_get.return_value = mock_resp
        
        # Instantiate test SQLite sessionmaker
        async_session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
        
        # Execute the background task
        await bootstrap_brand_identity_task("t-4", "b-4", "mock_shopify_token_abc", async_session_maker)
        
        # Verify that the BrandProperty (type: brand_identity) was seeded in the database
        stmt_prop = select(BrandProperty).where(
            BrandProperty.tenant_id == "t-4",
            BrandProperty.brand_id == "b-4",
            BrandProperty.type == "brand_identity"
        )
        res_prop = await session.execute(stmt_prop)
        bp = res_prop.scalar_one_or_none()
        
        assert bp is not None
        assert bp.status == "active"
        assert bp.findings["tone_of_voice"] == "Empathetic, sensory-friendly, clinical"
        assert bp.findings["target_persona"] == "Parents of sensory-seeking children, neurodivergent families"
        assert "Discounts" in bp.findings["past_experience"]
        
        # Verify Shopify API was indeed queried
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "b-4.myshopify.com/admin/api/2024-01/products.json" in args[0]
