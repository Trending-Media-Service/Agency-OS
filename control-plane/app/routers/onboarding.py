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
from app.models import Tenant, Brand, Connection
from app.services.oauth import OauthService, normalize_shopify_domain
from app.auth import verify_operator_auth

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])
logger = logging.getLogger(__name__)

@router.post("/bootstrap", dependencies=[Depends(verify_operator_auth)])
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



@router.post("/connection/direct", dependencies=[Depends(verify_operator_auth)])
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

@router.post("/connection/config", dependencies=[Depends(verify_operator_auth)])
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



