from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import BrandProperty
from app.profit.poas import calculate_campaign_poas
from app.kernel.optypes import OpSpec
from typing import Optional

async def calculate_brand_performance_score(
    s: AsyncSession,
    tenant_id: str,
    brand_id: str,
    w_ux: float = 0.25,
    w_organic: float = 0.25,
    w_paid: float = 0.25,
    w_pr: float = 0.25
) -> dict:
    """Computes the composite Brand Performance Score (B = w1*UX + w2*Organic + w3*Paid + w4*PR).
    
    Advisory metric only; does not gate microkernel execution.
    """
    # Normalize weights so they sum to 1.0
    total_w = w_ux + w_organic + w_paid + w_pr
    if total_w > 0:
        w_ux /= total_w
        w_organic /= total_w
        w_paid /= total_w
        w_pr /= total_w
    else:
        w_ux = w_organic = w_paid = w_pr = 0.25

    # 1. Fetch BrandProperties
    stmt = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id
    )
    res = await s.execute(stmt)
    properties = res.scalars().all()
    
    prop_map = {p.type: p for p in properties}

    # -- Component A: UX (Conversion Rate + GMC Health)
    ux_cr_score = 100.0
    ux_gmc_score = 100.0
    total_clicks = 0
    total_orders = 0
    
    # Calculate Conversion Rate from POAS reports if available
    try:
        poas_reports = await calculate_campaign_poas(s, tenant_id, brand_id)
        paid_campaigns = [r for r in poas_reports if r.get("campaign_id") != "ORGANIC"]
        total_clicks = sum(r.get("clicks", 0) for r in poas_reports)
        total_orders = sum(r.get("orders", 0) for r in poas_reports)
        if total_clicks > 0:
            cr = total_orders / total_clicks
            # 5% conversion rate maps to 100 score
            ux_cr_score = min(100.0, (cr / 0.05) * 100.0)
    except Exception:
        pass

    if "merchant_feed" in prop_map:
        gmc = prop_map["merchant_feed"]
        disapproved = gmc.findings.get("disapproved_products", 0)
        ux_gmc_score = max(0.0, 100.0 - disapproved * 10.0)

    ux_score = (ux_cr_score + ux_gmc_score) / 2.0

    # -- Component B: Organic (Search Console indexing errors)
    organic_score = 100.0
    if "search_console" in prop_map:
        gsc = prop_map["search_console"]
        errors = gsc.findings.get("crawl_errors", 0)
        organic_score = max(0.0, 100.0 - errors * 15.0)

    # -- Component C: Paid (Paid Campaign POAS)
    paid_score = 100.0
    total_spend = 0
    try:
        total_spend = sum(r.get("spend_minor", 0) for r in paid_campaigns)
        total_margin = sum(r.get("contribution_margin_minor", 0) for r in paid_campaigns)
        if total_spend > 0:
            avg_poas = total_margin / total_spend
            # POAS >= 2.0 maps to 100 score
            paid_score = min(100.0, max(0.0, (avg_poas / 2.0) * 100.0))
    except Exception:
        pass

    # -- Component D: PR (Brand Mentions Volume)
    pr_score = 100.0
    if "brand_mentions" in prop_map:
        mentions = prop_map["brand_mentions"]
        count = mentions.findings.get("mentions_count", 0)
        # 1,000 mentions maps to 100 score
        pr_score = min(100.0, (count / 1000.0) * 100.0)

    # Combine
    composite_b = (
        w_ux * ux_score +
        w_organic * organic_score +
        w_paid * paid_score +
        w_pr * pr_score
    )

    return {
        "brand_id": brand_id,
        "composite_b_score": round(composite_b, 2),
        "components": {
            "ux": {
                "score": round(ux_score, 2),
                "details": {"conversion_rate_score": round(ux_cr_score, 2), "gmc_feed_score": round(ux_gmc_score, 2)}
            },
            "organic": {
                "score": round(organic_score, 2),
                "details": {"crawl_errors": prop_map["search_console"].findings.get("crawl_errors", 0) if "search_console" in prop_map else 0}
            },
            "paid": {
                "score": round(paid_score, 2),
                "details": {"spend_minor": total_spend}
            },
            "pr": {
                "score": round(pr_score, 2),
                "details": {"mentions_count": prop_map["brand_mentions"].findings.get("mentions_count", 0) if "brand_mentions" in prop_map else 0}
            }
        },
        "weights": {
            "ux": round(w_ux, 2),
            "organic": round(w_organic, 2),
            "paid": round(w_paid, 2),
            "pr": round(w_pr, 2)
        }
    }
