import logging
from app.kernel.optypes import OpSpec, Severity, Reversibility, OpState
from app.kernel.loop import propose, preview_and_gate, _execute_and_verify
from app.kernel.services import resolve_brand_tier
import uuid

logger = logging.getLogger(__name__)

async def run_brand_sense(session, tenant_id: str, brand_id: str) -> None:
    """Task runner to propose and execute a governed Brand Sense Op to safely update the Brand Graph."""
    logger.info(f"Starting brand sense task for brand={brand_id} (tenant={tenant_id})...")
    
    try:
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        spec = OpSpec(
            id=op_id,
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="manage",
            action="manage.brand.sense",
            params={},
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        )
        
        # 1. Propose the Op
        row = await propose(session, spec, actor="tasks:sense")
        
        # 2. Derive tier
        tier = await resolve_brand_tier(session, tenant_id=tenant_id, brand_id=brand_id, domain="manage")
        
        # 3. Gate and preview the Op
        await preview_and_gate(session, row, tier=tier, actor="tasks:sense")
        
        # 4. If autonomous (auto-approved), execute synchronously so the GET request gets updated data
        if row.state == OpState.APPROVED.value:
            logger.info(f"Brand sense Op {op_id} was auto-approved. Executing synchronously...")
            await _execute_and_verify(session, row)
            logger.info(f"Brand sense Op {op_id} executed synchronously successfully.")
        else:
            logger.warning(f"Brand sense Op {op_id} not auto-approved (state={row.state}). Execution deferred.")
            
    except Exception as e:
        logger.error(f"Failed to run brand sense task: {e}", exc_info=True)
        raise
