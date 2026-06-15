from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import BrandProperty
from app.profit.poas import calculate_campaign_poas

async def calculate_brand_score(s: AsyncSession, tenant_id: str, brand_id: str) -> float:
    # 1. Fetch score weights from BrandProperty/findings (type: brand_performance_weights) or use default:
    # w1 (UX) = 0.3, w2 (Organic) = 0.2, w3 (Paid) = 0.4, w4 (PR) = 0.1
    w1, w2, w3, w4 = 0.3, 0.2, 0.4, 0.1
    
    stmt_weights = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "brand_performance_weights"
    ).limit(1)
    res_weights = await s.execute(stmt_weights)
    weights_prop = res_weights.scalar_one_or_none()
    if weights_prop and weights_prop.findings:
        f = weights_prop.findings
        w1 = float(f.get("w_ux", w1))
        w2 = float(f.get("w_organic", w2))
        w3 = float(f.get("w_paid", w3))
        w4 = float(f.get("w_pr", w4))

    # Normalize weights so they sum to 1.0
    total_w = w1 + w2 + w3 + w4
    if total_w > 0:
        w1, w2, w3, w4 = w1 / total_w, w2 / total_w, w3 / total_w, w4 / total_w

    # 2. Extract components
    # - UX Component (storefront conversion rate)
    ux_val = 0.0
    stmt_ux = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "ux_analytics"
    ).limit(1)
    res_ux = await s.execute(stmt_ux)
    ux_prop = res_ux.scalar_one_or_none()
    if ux_prop and ux_prop.findings:
        # e.g., 5% conversion rate (0.05) is perfect 100
        conv_rate = float(ux_prop.findings.get("conversion_rate", 0.0))
        ux_val = min(100.0, conv_rate * 2000.0)

    # - Organic Component (Presence Audit coverage)
    org_val = 0.0
    stmt_org = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "presence_audit"
    ).limit(1)
    res_org = await s.execute(stmt_org)
    org_prop = res_org.scalar_one_or_none()
    if org_prop and org_prop.findings:
        coverage = float(org_prop.findings.get("indexing_coverage_ratio", 0.0))
        org_val = coverage * 100.0

    # - Paid Component (margin-aware POAS)
    paid_val = 0.0
    try:
        reports = await calculate_campaign_poas(s, tenant_id, brand_id)
        paid_reports = [r for r in reports if r["campaign_id"] != "ORGANIC" and r["spend_minor"] > 0]
        if paid_reports:
            # e.g., POAS of 2.0 is 100 points
            avg_poas = sum(r["poas"] for r in paid_reports if r["poas"] is not None) / len(paid_reports)
            paid_val = min(100.0, avg_poas * 50.0)
        else:
            paid_val = 50.0
    except Exception:
        paid_val = 50.0

    # - PR Component (mention volume)
    pr_val = 0.0
    stmt_pr = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "pr_monitoring"
    ).limit(1)
    res_pr = await s.execute(stmt_pr)
    pr_prop = res_pr.scalar_one_or_none()
    if pr_prop and pr_prop.findings:
        pr_val = float(pr_prop.findings.get("mention_volume_normalized", 0.0))

    # 3. Compile B-score
    b_score = (w1 * ux_val) + (w2 * org_val) + (w3 * paid_val) + (w4 * pr_val)
    return round(b_score, 2)
