from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import BrandProperty
from app.profit.poas import calculate_campaign_poas

async def calculate_brand_performance_score(
    s: AsyncSession,
    tenant_id: str,
    brand_id: str,
    w_ux: float | None = None,
    w_organic: float | None = None,
    w_paid: float | None = None,
    w_pr: float | None = None
) -> dict:
    """Computes the composite Brand Performance Score (B = w1*UX + w2*Organic + w3*Paid + w4*PR).

    Advisory metric only; does not gate microkernel execution.
    """
    # 1. Load weights (either from arguments, stored brand properties, or default)
    dw_ux, dw_organic, dw_paid, dw_pr = 0.3, 0.2, 0.4, 0.1
    
    # Try to load from stored BrandProperty if not all weights are supplied as arguments
    if w_ux is None or w_organic is None or w_paid is None or w_pr is None:
        stmt_weights = select(BrandProperty).where(
            BrandProperty.tenant_id == tenant_id,
            BrandProperty.brand_id == brand_id,
            BrandProperty.type == "brand_performance_weights"
        ).limit(1)
        res_weights = await s.execute(stmt_weights)
        weights_prop = res_weights.scalar_one_or_none()
        if weights_prop and weights_prop.findings:
            f = weights_prop.findings
            dw_ux = float(f.get("w_ux", dw_ux))
            dw_organic = float(f.get("w_organic", dw_organic))
            dw_paid = float(f.get("w_paid", dw_paid))
            dw_pr = float(f.get("w_pr", dw_pr))

    final_w_ux = w_ux if w_ux is not None else dw_ux
    final_w_organic = w_organic if w_organic is not None else dw_organic
    final_w_paid = w_paid if w_paid is not None else dw_paid
    final_w_pr = w_pr if w_pr is not None else dw_pr

    # Normalize weights so they sum to 1.0
    total_w = final_w_ux + final_w_organic + final_w_paid + final_w_pr
    if total_w > 0:
        final_w_ux /= total_w
        final_w_organic /= total_w
        final_w_paid /= total_w
        final_w_pr /= total_w
    else:
        final_w_ux = final_w_organic = final_w_paid = final_w_pr = 0.25

    # 2. Extract components
    
    # -- Component A: UX (storefront conversion rate from ux_analytics)
    ux_val = 0.0
    conversion_rate = 0.0
    stmt_ux = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "ux_analytics"
    ).limit(1)
    res_ux = await s.execute(stmt_ux)
    ux_prop = res_ux.scalar_one_or_none()
    if ux_prop and ux_prop.findings:
        conversion_rate = float(ux_prop.findings.get("conversion_rate", 0.0))
        # 5% conversion rate maps to 100 score
        ux_val = min(100.0, conversion_rate * 2000.0)

    # -- Component B: Organic (Presence Audit coverage from presence_audit)
    org_val = 0.0
    coverage_ratio = 0.0
    stmt_org = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "presence_audit"
    ).limit(1)
    res_org = await s.execute(stmt_org)
    org_prop = res_org.scalar_one_or_none()
    if org_prop and org_prop.findings:
        coverage_ratio = float(org_prop.findings.get("indexing_coverage_ratio", 0.0))
        org_val = coverage_ratio * 100.0

    # -- Component C: Paid (Paid Campaign POAS from calculate_campaign_poas)
    paid_val = 50.0 # Default fallback
    avg_poas = 0.0
    try:
        poas_reports = await calculate_campaign_poas(s, tenant_id, brand_id)
        paid_reports = [r for r in poas_reports if r.get("campaign_id") != "ORGANIC" and r.get("spend_minor", 0) > 0]
        if paid_reports:
            valid_poas = [r["poas"] for r in paid_reports if r.get("poas") is not None]
            if valid_poas:
                avg_poas = sum(valid_poas) / len(valid_poas)
                # POAS of 2.0 maps to 100 score
                paid_val = min(100.0, avg_poas * 50.0)
    except Exception:
        pass

    # -- Component D: PR (Brand Mentions normalized volume from pr_monitoring)
    pr_val = 0.0
    mention_volume = 0.0
    stmt_pr = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "pr_monitoring"
    ).limit(1)
    res_pr = await s.execute(stmt_pr)
    pr_prop = res_pr.scalar_one_or_none()
    if pr_prop and pr_prop.findings:
        mention_volume = float(pr_prop.findings.get("mention_volume_normalized", 0.0))
        pr_val = mention_volume

    # Combine
    composite_b = (final_w_ux * ux_val) + (final_w_organic * org_val) + (final_w_paid * paid_val) + (final_w_pr * pr_val)

    return {
        "brand_id": brand_id,
        "composite_b_score": round(composite_b, 2),
        "components": {
            "ux": {
                "score": round(ux_val, 2),
                "details": {"conversion_rate": conversion_rate}
            },
            "organic": {
                "score": round(org_val, 2),
                "details": {"indexing_coverage_ratio": coverage_ratio}
            },
            "paid": {
                "score": round(paid_val, 2),
                "details": {"average_poas": round(avg_poas, 4)}
            },
            "pr": {
                "score": round(pr_val, 2),
                "details": {"mention_volume_normalized": mention_volume}
            }
        },
        "weights": {
            "ux": round(final_w_ux, 4),
            "organic": round(final_w_organic, 4),
            "paid": round(final_w_paid, 4),
            "pr": round(final_w_pr, 4)
        }
    }

async def calculate_brand_score(s: AsyncSession, tenant_id: str, brand_id: str) -> float:
    """Legacy backward-compatible wrapper returning only the float score."""
    report = await calculate_brand_performance_score(s, tenant_id, brand_id)
    return report["composite_b_score"]
