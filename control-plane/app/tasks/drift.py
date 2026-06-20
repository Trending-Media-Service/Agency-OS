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
    
    CHUNK_SIZE = 50
    offset = 0
    total_proposed = 0
    
    while True:
        # Deterministically fetch a chunk of active brands ordered by ID
        stmt = (
            select(Brand)
            .join(Tenant)
            .where(Tenant.is_active == True)
            .order_by(Brand.id)
            .limit(CHUNK_SIZE)
            .offset(offset)
        )
        res = await session.execute(stmt)
        chunk_brands = res.scalars().all()
        
        if not chunk_brands:
            break
            
        logger.info(f"Processing drift detection chunk of {len(chunk_brands)} brands (offset={offset})")
        
        for brand in chunk_brands:
            # Check if there is already an active drift detection Op for this brand to guarantee idempotency
            from app.models import OpRow
            active_stmt = select(OpRow.id).where(
                OpRow.tenant_id == brand.tenant_id,
                OpRow.brand_id == brand.id,
                OpRow.action == "manage.drift.detect",
                OpRow.state.notin_(["DONE", "REJECTED", "EXPIRED", "ROLLED_BACK"])
            )
            active_res = await session.execute(active_stmt)
            if active_res.first() is not None:
                logger.info(f"Idempotency Guard: Skipping drift detection for brand {brand.id} (active sweep already in-flight)")
                continue

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
                total_proposed += 1
            except Exception as e:
                logger.error(f"Failed to propose drift detection Op for brand id={brand.id}: {e}", exc_info=True)
                
        try:
            await session.commit()
            logger.info(f"Successfully committed drift sweep chunk offset={offset}")
        except Exception as e:
            logger.error(f"Database commit failed during drift sweep chunk offset={offset}, rolling back this chunk: {e}")
            await session.rollback()
            raise
            
        offset += CHUNK_SIZE
        
    logger.info(f"Drift detection sweep completed. Total proposed: {total_proposed}")
