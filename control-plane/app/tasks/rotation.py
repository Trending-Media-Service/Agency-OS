import logging
import datetime as dt
from sqlalchemy import select

from app.models import Connection, TrustSnapshot, OpRow
from app.kernel.optypes import OpSpec, Severity, Reversibility
from app.kernel.loop import propose, preview_and_gate
import uuid

logger = logging.getLogger(__name__)

async def rotate_expiring_tokens(session) -> None:
    """Task runner to identify and propose governed rotation Ops for expiring connections."""
    logger.info("Starting periodic token rotation task...")
    
    # 1. Query all active, degraded, or error connections that have a credential reference
    stmt = select(Connection).where(
        Connection.status.in_(["active", "degraded", "error", "unverified"]),
        Connection.credential.isnot(None)
    )
    res = await session.execute(stmt)
    connections = res.scalars().all()
    logger.info(f"Found {len(connections)} connections eligible for rotation scan.")
    
    if not connections:
        logger.info("No connections found needing rotation scan.")
        return
        
    now = dt.datetime.utcnow()
    
    # 2. Iterate and propose rotation Ops for expiring connections
    for conn in connections:
        # Check if the connection has an expiry time, and if it is within the 24-hour buffer.
        # If expires_at is None, we also check it to be safe (or to support mock tests).
        is_expiring = (
            conn.expires_at is None or 
            conn.expires_at <= now + dt.timedelta(hours=24)
        )
        
        if not is_expiring:
            logger.info(f"Connection {conn.id} ({conn.provider}) is not expiring yet (expires at {conn.expires_at}). Skipping.")
            continue
            
        logger.info(f"Proposing governed token rotation Op for connection: id={conn.id}, provider={conn.provider}")
        try:
            op_id = f"op_{uuid.uuid4().hex[:12]}"
            spec = OpSpec(
                id=op_id,
                tenant_id=conn.tenant_id,
                brand_id=conn.brand_id,
                domain="manage",
                action="manage.connection.rotate",
                params={
                    "provider": conn.provider,
                    "old_credential": conn.credential,
                    "old_config": conn.config,
                },
                severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
            )
            
            # Propose the Op
            row = await propose(session, spec, actor="tasks:rotation")
            
            # Derive tier from the latest TrustSnapshot for this brand+domain (default 1).
            stmt_tier = (
                select(TrustSnapshot.tier)
                .where(
                    TrustSnapshot.tenant_id == conn.tenant_id,
                    TrustSnapshot.brand_id == conn.brand_id,
                    TrustSnapshot.domain == "manage",
                )
                .order_by(TrustSnapshot.ts.desc())
                .limit(1)
            )
            t = (await session.execute(stmt_tier)).scalar_one_or_none()
            tier = 1 if t is None else t
            
            # Gate and preview
            await preview_and_gate(session, row, tier=tier, actor="tasks:rotation")
            
            logger.info(f"Successfully proposed rotation Op {op_id} for connection {conn.id}")
            
        except Exception as e:
            logger.error(f"Failed to propose rotation Op for connection id={conn.id}: {e}", exc_info=True)
            # We don't raise here, preserving batch resilience so other connections can still be processed!
            
    # 3. Commit all proposed Ops in a single transaction block
    try:
        await session.commit()
        logger.info("Token rotation task completed and committed successfully.")
    except Exception as e:
        logger.error(f"Database commit failed during token rotation, rolling back: {e}")
        await session.rollback()
        raise
