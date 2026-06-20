import logging
from sqlalchemy import select
from app.models import Brand, Tenant
from app.kernel.optypes import OpSpec, Severity, Reversibility
from app.kernel.loop import propose, preview_and_gate
from app.kernel.services import resolve_brand_tier
import uuid

logger = logging.getLogger(__name__)

async def run_drift_detection_sweep(session) -> None:
    """Task runner to periodically scan all active brands and propose governed drift detection Ops.
    
    Bypasses RLS since it is run by the background worker.
    """
    logger.info("Starting periodic drift detection sweep...")
    
    # Query all brands belonging to active tenants
    stmt = select(Brand).join(Tenant).where(Tenant.is_active == True)
    res = await session.execute(stmt)
    brands = res.scalars().all()
    logger.info(f"Found {len(brands)} active brands eligible for drift scan.")
    
    for brand in brands:
        logger.info(f"Proposing governed drift detection Op for brand: id={brand.id}, name={brand.name}")
        try:
            op_id = f"op_{uuid.uuid4().hex[:12]}"
            spec = OpSpec(
                id=op_id,
                tenant_id=brand.tenant_id,
                brand_id=brand.id,
                domain="manage",
                action="manage.drift.detect",
                params={},
                severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
            )
            
            # Propose the Op
            row = await propose(session, spec, actor="tasks:drift_sweep")
            
            # Resolve brand tier
            tier = await resolve_brand_tier(session, tenant_id=brand.tenant_id, brand_id=brand.id, domain="manage")
            
            # Gate and preview
            await preview_and_gate(session, row, tier=tier, actor="tasks:drift_sweep")
            
            logger.info(f"Successfully proposed drift detection Op {op_id} for brand {brand.id}")
        except Exception as e:
            logger.error(f"Failed to propose drift detection Op for brand id={brand.id}: {e}", exc_info=True)
            
    try:
        await session.commit()
        logger.info("Drift detection sweep completed and committed successfully.")
    except Exception as e:
        logger.error(f"Database commit failed during drift detection sweep, rolling back: {e}")
        await session.rollback()
        raise
