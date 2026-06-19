import logging
import datetime as dt
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, Order, OpRow, Brand
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.kernel import loop

logger = logging.getLogger(__name__)

GRADUATION_THRESHOLD_MINOR = 5_000_000  # 500,000 INR = 5,000,000 minor units
LOOKBACK_DAYS = 30

async def check_and_propose_graduations(s: AsyncSession):
    """Scans for shared-tier tenants exceeding the revenue threshold and proposes graduation."""
    logger.info("Starting tenant hosting tier graduation check...")
    
    # 1. Fetch all tenants on the shared tier
    stmt = select(Tenant).where(Tenant.hosting_tier == "shared")
    res = await s.execute(stmt)
    tenants = res.scalars().all()
    
    now = dt.datetime.now(dt.timezone.utc)
    lookback_limit = now - dt.timedelta(days=LOOKBACK_DAYS)
    
    proposed_count = 0
    
    for tenant in tenants:
        # 2. Sum sales (Order amount_minor) for this tenant in the last 30 days
        sales_stmt = (
            select(func.sum(Order.amount_minor))
            .where(
                Order.tenant_id == tenant.id,
                Order.placed_at >= lookback_limit
            )
        )
        sales_res = await s.execute(sales_stmt)
        total_sales = sales_res.scalar() or 0
        
        logger.info(f"Tenant {tenant.id} ('{tenant.name}') 30-day sales: {total_sales / 100:.2f} INR (threshold: {GRADUATION_THRESHOLD_MINOR / 100:.2f} INR)")
        
        if total_sales >= GRADUATION_THRESHOLD_MINOR:
            # 3. Check if there is an active/proposed graduation Op already to avoid duplicate proposals
            active_op_stmt = (
                select(OpRow)
                .where(
                    OpRow.tenant_id == tenant.id,
                    OpRow.action == "provision.brand_baseline.update",
                    OpRow.state.in_(["PROPOSED", "PREVIEWED", "AWAITING_APPROVAL", "APPROVED", "EXECUTING", "VERIFYING"])
                )
            )
            active_op_res = await s.execute(active_op_stmt)
            existing_op = active_op_res.scalar_one_or_none()
            
            if existing_op:
                logger.info(f"Tenant {tenant.id} already has active graduation Op {existing_op.id} ({existing_op.state})")
                continue
                
            # 4. Propose graduation Op!
            brand_stmt = select(Brand).where(Brand.tenant_id == tenant.id).limit(1)
            brand_res = await s.execute(brand_stmt)
            brand = brand_res.scalar_one_or_none()
            brand_id = brand.id if brand else "default"
            
            spec = OpSpec(
                tenant_id=tenant.id,
                brand_id=brand_id,
                domain="provision",
                action="provision.brand_baseline.update",
                params={
                    "tenant_id": tenant.id,
                    "brand_id": brand_id,
                    "tier": "dedicated",
                    "recipe": "brand-baseline",
                    "version": "0.1.0",
                    "billing_account": "012E0F-7A4F33-26EDD8",
                    "folder_id": "338402544084"
                },
                severity=Severity(impact=3, reversibility=Reversibility.COMPENSATABLE),
                cost_estimate=Money(amount_minor=0, currency="INR"),
            )
            
            # Propose via loop under the tenant's RLS context (simulate scheduler action)
            row = await loop.propose(s, spec, actor="scheduler:graduation")
            await loop.preview_and_gate(s, row, tier=1)
            
            logger.info(f"✓ Proposed graduation Op {row.id} for Tenant {tenant.id} (Sales: {total_sales / 100:.2f} INR)")
            proposed_count += 1
            
    logger.info(f"Tenant graduation check complete. Proposed {proposed_count} graduations.")
