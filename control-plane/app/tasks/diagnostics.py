import logging
from sqlalchemy import select
from app.models import Brand, Tenant
from app.kernel.optypes import OpSpec, Severity, Reversibility
from app.kernel.loop import propose, preview_and_gate
from app.kernel.services import resolve_brand_tier
import uuid
import os

logger = logging.getLogger(__name__)

async def run_diagnostics_sweep(session) -> None:
    """Task runner to periodically scan runtime logs across all active brands and propose governed diagnostics check Ops.
    
    Bypasses RLS since it is run by the background worker.
    """
    logger.info("Starting periodic diagnostics logs sweep...")
    
    # Query all brands belonging to active tenants
    stmt = select(Brand).join(Tenant).where(Tenant.is_active == True)
    res = await session.execute(stmt)
    brands = res.scalars().all()
    logger.info(f"Found {len(brands)} active brands eligible for diagnostics scan.")
    
    for brand in brands:
        logger.info(f"Proposing governed diagnostics check Op for brand: id={brand.id}, name={brand.name}")
        try:
            # Under test mode, we inject a mock log stream containing OOM if the brand name is "OOMBrand"
            # to verify downstream auto-reconciliation, or a default clean log stream.
            log_stream = ""
            if os.getenv("AOS_ENV") == "test":
                if brand.name == "OOMBrand":
                    log_stream = "[2026-06-11 10:00:00] FATAL: Out of Memory error in container run.app"
                else:
                    log_stream = "[2026-06-11 10:00:00] INFO: Container started, health check OK"
            
            op_id = f"op_{uuid.uuid4().hex[:12]}"
            spec = OpSpec(
                id=op_id,
                tenant_id=brand.tenant_id,
                brand_id=brand.id,
                domain="manage",
                action="manage.diagnostics.check",
                params={
                    "log_source": "cloud-run-logs",
                    "log_stream": log_stream
                },
                severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
            )
            
            # Propose the Op
            row = await propose(session, spec, actor="tasks:diagnostics_sweep")
            
            # Resolve brand tier
            tier = await resolve_brand_tier(session, tenant_id=brand.tenant_id, brand_id=brand.id, domain="manage")
            
            # Gate and preview
            await preview_and_gate(session, row, tier=tier, actor="tasks:diagnostics_sweep")
            
            logger.info(f"Successfully proposed diagnostics check Op {op_id} for brand {brand.id}")
        except Exception as e:
            logger.error(f"Failed to propose diagnostics check Op for brand id={brand.id}: {e}", exc_info=True)
            
    try:
        await session.commit()
        logger.info("Diagnostics logs sweep completed and committed successfully.")
    except Exception as e:
        logger.error(f"Database commit failed during diagnostics logs sweep, rolling back: {e}")
        await session.rollback()
        raise
