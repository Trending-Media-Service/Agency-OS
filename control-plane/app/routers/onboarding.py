# app/routers/onboarding.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import json
import os
import logging
from typing import Optional

from app.database import get_db, AsyncSessionLocal
from app.models import Tenant, Brand, Connection, BrandProperty
from app.services.oauth import generate_oauth_state, verify_oauth_state, OauthService, normalize_shopify_domain
from app.services.oauth_registry import OauthProviderRegistry

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])
logger = logging.getLogger(__name__)

@router.post("/bootstrap")
async def bootstrap_tenant(
    name: str, 
    domain: str, 
    tier: str = "shared", 
    db: AsyncSession = Depends(get_db)
):
    """Seeds the initial Tenant and Brand database rows.
    
    Prepares the system for OAuth connections and launches the GCP baseline provisioning.
    """
    logger.info(f"Bootstrapping tenant={name}, tier={tier}...")
    tenant = Tenant(name=name, hosting_tier=tier)
    db.add(tenant)
    await db.flush() # Resolve tenant ID
    
    brand = Brand(tenant_id=tenant.id, name=name)
    db.add(brand)
    await db.commit()
    
    # In production, this trigger initiates the asynchronous GCP provision.brand_baseline Saga
    logger.info(f"Tenant {tenant.id} and Brand {brand.id} seeded successfully. Tier: {tier}")
    return {
        "tenant_id": tenant.id, 
        "brand_id": brand.id, 
        "status": "onboarding_ready", 
        "tier": tier
    }

@router.get("/oauth/authorize/{provider}")
async def oauth_authorize(
    provider: str, 
    tenant_id: str, 
    brand_id: str, 
    redirect_uri: str,
    custom_domain: Optional[str] = None,
    shop: Optional[str] = None,
):
    """Generates the signed state token and redirects the merchant to the provider's OAuth page.

    For Shopify, `shop` is the store's myshopify handle/domain (e.g. 'ableys' or
    'ableys.myshopify.com'); it is carried in the signed state so the callback can
    complete the token exchange against the correct store. Falls back to brand_id.
    """
    logger.info(f"Generating OAuth redirect for provider={provider}, tenant={tenant_id}...")
    state = generate_oauth_state(tenant_id, brand_id, redirect_uri, provider)
    
    # Handle Shopify custom store subdomains vs standard providers
    if provider == "shopify":
        shop_domain = normalize_shopify_domain(shop or brand_id)
        # Re-sign the state with the resolved shop so the callback can complete
        # the token exchange against the correct store.
        state = generate_oauth_state(tenant_id, brand_id, redirect_uri, provider, shop=shop_domain)
        client_id = os.getenv("SHOPIFY_CLIENT_ID", "mock-shopify-client-id")
        auth_url = (
            f"https://{shop_domain}/admin/oauth/authorize?"
            f"client_id={client_id}&"
            f"scope=read_products,write_products,read_orders&"
            f"redirect_uri={redirect_uri}&"
            f"state={state}"
        )
    else:
        try:
            auth_url = OauthProviderRegistry.get_authorize_url(provider, state, redirect_uri, custom_domain)
        except Exception as e:
            logger.error(f"Failed to generate authorize URL: {e}")
            raise HTTPException(status_code=400, detail=str(e))
            
    return RedirectResponse(auth_url)

@router.get("/oauth/callback")
async def oauth_callback(
    code: str, 
    state: str, 
    background_tasks: BackgroundTasks, 
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Receives the redirect callback, exchanges code, seeds Connection, and triggers RAG scan."""
    logger.info("Received OAuth callback redirect...")
    try:
        payload = verify_oauth_state(state)
    except Exception as e:
        logger.error(f"OAuth State verification failed: {e}")
        raise HTTPException(status_code=400, detail=f"OAuth State verification failed: {str(e)}")
        
    tenant_id = payload["tenant_id"]
    brand_id = payload["brand_id"]
    provider = payload.get("provider", "shopify")
    shop = payload.get("shop")

    oauth_service = OauthService()

    # 1. Exchange the authorization code for access/refresh tokens
    try:
        creds = await oauth_service.exchange_code_for_token(tenant_id, brand_id, provider, code, shop=shop, redirect_uri=payload.get("redirect_uri"))
    except Exception as e:
        logger.error(f"OAuth token exchange failed: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth token exchange failed: {str(e)}")
        
    # 2. Seed or update the Connection row
    stmt = select(Connection).where(
        Connection.tenant_id == tenant_id,
        Connection.brand_id == brand_id,
        Connection.provider == provider
    )
    res = await db.execute(stmt)
    conn = res.scalar_one_or_none()
    
    if not conn:
        conn = Connection(
            tenant_id=tenant_id,
            brand_id=brand_id,
            provider=provider,
            credential=creds["refresh_token_ref"],
            config={"access_token_ref": creds["access_token_ref"]},
            status="active"
        )
        db.add(conn)
    else:
        conn.credential = creds["refresh_token_ref"]
        conn.config = {"access_token_ref": creds["access_token_ref"]}
        conn.status = "active"
        
    await db.commit()
    logger.info(f"Connection seeded successfully for provider={provider}, brand={brand_id}")
    
    # 3. Trigger autonomous background RAG bootstrapping if Shopify is connected
    if provider == "shopify":
        session_maker = getattr(request.app.state, "db_session_maker", AsyncSessionLocal)
        background_tasks.add_task(bootstrap_brand_identity_task, tenant_id, brand_id, creds["access_token"], session_maker, shop)
        
    return {
        "status": "connection_established", 
        "tenant_id": tenant_id, 
        "brand_id": brand_id,
        "provider": provider
    }

@router.post("/connection/direct")
async def connect_direct_api_key(
    tenant_id: str,
    brand_id: str,
    provider: str,
    api_key: str,
    config: Optional[dict] = None,
    db: AsyncSession = Depends(get_db)
):
    """Directly registers permanent API keys (Stripe, Klaviyo, Shopify Private Apps) securely in Secret Manager."""
    logger.info(f"Directly registering API key for tenant={tenant_id}, provider={provider}...")
    secret_id = f"{tenant_id}-{brand_id}-{provider}-secret"
    
    oauth_service = OauthService()
    credential_ref = await oauth_service.secrets_client.write_secret(secret_id, api_key)
    
    conn = Connection(
        tenant_id=tenant_id,
        brand_id=brand_id,
        provider=provider,
        credential=credential_ref,
        config=config or {},
        status="active"
    )
    db.add(conn)
    await db.commit()
    
    logger.info(f"Direct connection established successfully for provider={provider}")
    return {"status": "direct_connection_established", "provider": provider}

@router.post("/connection/config")
async def configure_connection(
    tenant_id: str,
    brand_id: str,
    provider: str,
    config: dict,
    db: AsyncSession = Depends(get_db)
):
    """Merges additional non-secret config into an existing Connection.

    Used to supply provider settings not captured by OAuth — notably the Google Ads
    `developer_token` (read by app/services/google_ads.py from the connection config).
    """
    logger.info(f"Configuring connection for tenant={tenant_id}, provider={provider}...")
    stmt = select(Connection).where(
        Connection.tenant_id == tenant_id,
        Connection.brand_id == brand_id,
        Connection.provider == provider,
    )
    res = await db.execute(stmt)
    conn = res.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    merged = dict(conn.config or {})
    merged.update(config or {})
    conn.config = merged
    await db.commit()

    logger.info(f"Connection config updated for provider={provider}: keys={list((config or {}).keys())}")
    return {"status": "connection_configured", "provider": provider}


async def bootstrap_brand_identity_task(tenant_id: str, brand_id: str, shopify_token: str, session_maker, shop: str = None):
    """Background task: Scans Shopify catalog, calls Gemini, and seeds the Brand RAG Profile."""
    logger.info(f"Starting autonomous RAG bootstrapping for brand {brand_id}...")

    # A. Fetch Shop and Product metadata from Shopify (prefer the explicit shop
    #    handle/domain resolved during onboarding; fall back to brand_id).
    shop_domain = normalize_shopify_domain(shop or brand_id)
    shop_url = f"https://{shop_domain}/admin/api/2024-01/products.json?limit=5"
    headers = {
        "X-Shopify-Access-Token": shopify_token,
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(shop_url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                products_data = resp.json().get("products", [])
            else:
                logger.error(f"Shopify catalog fetch failed with status: {resp.status_code}")
                products_data = []
        except Exception as e:
            logger.error(f"Failed to scan Shopify catalog during RAG bootstrap: {e}")
            return
            
    # B. Compile catalog context
    catalog_summary = []
    for p in products_data:
        catalog_summary.append(
            f"Title: {p.get('title')}\n"
            f"Type: {p.get('product_type')}\n"
            f"Description: {p.get('body_html', '')[:200]}"
        )
    catalog_context = "\n---\n".join(catalog_summary)
    
    # C. Call Gemini to synthesize Tone of Voice, Target Persona, and Guidelines
    from app.services.llm import VertexAIClient
    llm_client = VertexAIClient()
    
    prompt = (
        f"Analyze this e-commerce product catalog and synthesize a highly accurate Brand Identity profile. "
        f"Determine:\n"
        f"1. Tone of Voice (TOV) (e.g. empathetic, sensory-friendly, highly professional, playful).\n"
        f"2. Target Audience Personas (e.g. ADHD parents, outdoor enthusiasts).\n"
        f"3. Key copy guidelines (what terms to focus on, what to avoid).\n\n"
        f"Catalog Context:\n{catalog_context}"
    )
    
    try:
        # Generate the structured profile using Gemini
        identity_json_str = await llm_client.generate_personalized_content(
            tenant_id=tenant_id,
            brand_id=brand_id,
            prompt=prompt,
            session=None, # pass None or use a dedicated session factory
            system_instruction=(
                "You are a senior brand consultant. Respond ONLY with a valid JSON object containing: "
                "'tone_of_voice', 'target_persona', and 'past_experience' keys."
            )
        )
        identity_data = json.loads(identity_json_str)
    except Exception as e:
        logger.error(f"Failed to synthesize brand identity via LLM: {e}")
        # Seeding defaults to ensure tenant has at least some RAG entries
        identity_data = {
            "tone_of_voice": "Friendly, modern, and direct",
            "target_persona": "General e-commerce consumers",
            "past_experience": "No performance logs recorded yet."
        }
        
    # D. Write the RAG profile directly to the database using local session
    async with session_maker() as db_session:
        # Clean up any existing brand_identity entries
        stmt_cleanup = select(BrandProperty).where(
            BrandProperty.tenant_id == tenant_id,
            BrandProperty.brand_id == brand_id,
            BrandProperty.type == "brand_identity"
        )
        res = await db_session.execute(stmt_cleanup)
        existing = res.scalars().all()
        for prop in existing:
            await db_session.delete(prop)
            
        rag_prop = BrandProperty(
            tenant_id=tenant_id,
            brand_id=brand_id,
            type="brand_identity",
            provider="internal",
            status="active",
            findings=identity_data
        )
        db_session.add(rag_prop)
        await db_session.commit()
        
    logger.info(f"Autonomous RAG profile successfully bootstrapped for brand {brand_id}! TOV: {identity_data.get('tone_of_voice')}")
