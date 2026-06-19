import logging
import datetime as dt
from sqlalchemy import select

from app.models import Connection
from app.services.oauth import OauthService

logger = logging.getLogger(__name__)

OAUTH_PROVIDERS = {"shopify", "google-ads", "google-search-console", "google-analytics", "meta-ads"}

async def rotate_expiring_tokens(session) -> None:
    """Task runner to identify and rotate expiring or active OAuth credentials."""
    print("DEBUG: rotate_expiring_tokens started", flush=True)
    logger.info("Starting periodic token rotation task...")
    
    # 1. Query all active connections that have a credential reference
    stmt = select(Connection).where(
        Connection.status == "active",
        Connection.credential.isnot(None)
    )
    res = await session.execute(stmt)
    connections = res.scalars().all()
    print(f"DEBUG: rotate_expiring_tokens found {len(connections)} connections", flush=True)
    for c in connections:
        print(f"  Connection: id={c.id}, provider={c.provider}, status={c.status}, credential={c.credential}, expires_at={c.expires_at}", flush=True)
    
    if not connections:
        logger.info("No active connections found needing rotation.")
        return
        
    service = OauthService()
    
    # 2. Iterate and rotate
    for conn in connections:
        if conn.provider not in OAUTH_PROVIDERS:
            print(f"DEBUG: skipping non-oauth provider {conn.provider}", flush=True)
            continue
            
        print(f"DEBUG: rotating connection id={conn.id}, provider={conn.provider}", flush=True)
        logger.info(f"Rotating connection: id={conn.id}, provider={conn.provider}")
        try:
            # Call OAuth service to refresh token
            result = await service.refresh_token(
                conn.tenant_id,
                conn.brand_id,
                conn.provider,
                conn.credential
            )
            print(f"DEBUG: refresh_token returned: {result}", flush=True)
            
            # Update connection metadata
            new_ref = result.get("refresh_token_ref")
            if new_ref:
                conn.credential = new_ref
                
            # Update expires_at
            expires_in = result.get("expires_in", 3600)
            conn.expires_at = dt.datetime.utcnow() + dt.timedelta(seconds=expires_in)
            conn.last_verified_at = dt.datetime.utcnow()
            conn.last_error = None
            conn.status = "active"
            
            # Prune old secret version
            if new_ref:
                await service.prune_old_versions(new_ref)
                
            logger.info(f"Successfully rotated connection: id={conn.id}")
            print(f"DEBUG: successfully rotated connection id={conn.id}, new_credential={conn.credential}", flush=True)
            
        except Exception as e:
            print(f"DEBUG: rotation failed for connection id={conn.id}: {e}", flush=True)
            logger.error(f"Failed to rotate connection id={conn.id}: {e}", exc_info=True)
            # Mark the connection in error state, preserving batch resilience
            conn.status = "error"
            conn.last_error = str(e)
            
    # 3. Commit changes as a single transaction block
    try:
        print("DEBUG: committing session", flush=True)
        await session.commit()
        print("DEBUG: commit succeeded", flush=True)
        logger.info("Token rotation task completed and committed successfully.")
    except Exception as e:
        print(f"DEBUG: commit failed: {e}", flush=True)
        logger.error(f"Database commit failed during token rotation, rolling back: {e}")
        await session.rollback()
        raise
