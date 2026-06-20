import datetime as dt
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Order,
    OrderLine,
    Refund,
    FulfillmentCost,
    Campaign,
    SpendFact,
    Touchpoint,
    BrandProperty,
    Lead,
    BrandObjective
)

logger = logging.getLogger(__name__)


async def calculate_campaign_poas(
    s: AsyncSession,
    tenant_id: str,
    brand_id: str,
    attribution_window_days: int = 30,
    attribution_model: str = "last_touch"
) -> list[dict]:
    """Computes contribution margin and POAS per campaign in minor units.

    POAS = contribution_margin / spend.
    Organics sit at the top. Other campaigns sorted worst-POAS-first.
    """
    # Fetch incrementality multiplier alpha_inc (default to 1.0)
    alpha_inc = 1.0
    stmt_alpha = select(BrandProperty).where(
        BrandProperty.tenant_id == tenant_id,
        BrandProperty.brand_id == brand_id,
        BrandProperty.type == "attribution_multiplier"
    ).limit(1)
    res_alpha = await s.execute(stmt_alpha)
    alpha_prop = res_alpha.scalar_one_or_none()
    if alpha_prop and alpha_prop.findings and "alpha_inc" in alpha_prop.findings:
        alpha_inc = float(alpha_prop.findings["alpha_inc"])

    # Check Brand Objective
    stmt_obj = select(BrandObjective).where(
        BrandObjective.tenant_id == tenant_id,
        BrandObjective.brand_id == brand_id
    ).limit(1)
    res_obj = await s.execute(stmt_obj)
    objective_row = res_obj.scalar_one_or_none()
    objective = objective_row.objective if objective_row else "retention"

    if objective == "growth": # Lead Gen Brand!
        # Compute CRM Lead POAS instead of E-commerce!
        leads_q = await s.execute(select(Lead).where(Lead.tenant_id == tenant_id, Lead.brand_id == brand_id))
        leads = leads_q.scalars().all()

        campaigns_q = await s.execute(select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.brand_id == brand_id))
        campaigns = campaigns_q.scalars().all()

        spend_facts_q = await s.execute(
            select(SpendFact)
            .join(Campaign, Campaign.id == SpendFact.campaign_id)
            .where(SpendFact.tenant_id == tenant_id, Campaign.brand_id == brand_id)
        )
        spend_facts = spend_facts_q.scalars().all()

        touchpoints_q = await s.execute(
            select(Touchpoint)
            .join(Campaign, Campaign.id == Touchpoint.campaign_id)
            .where(Touchpoint.tenant_id == tenant_id, Campaign.brand_id == brand_id)
        )
        touchpoints = touchpoints_q.scalars().all()

        # Attribution mapping for leads
        touchpoints_by_customer = {}
        for tp in touchpoints:
            if not tp.customer_id:
                continue
            if tp.customer_id not in touchpoints_by_customer:
                touchpoints_by_customer[tp.customer_id] = []
            touchpoints_by_customer[tp.customer_id].append(tp)

        lead_attribution = {}
        window_delta = dt.timedelta(days=attribution_window_days)

        for lead in leads:
            if not lead.email_hashed:
                lead_attribution[lead.id] = "ORGANIC"
                continue

            # We match touchpoints using customer_id (email_hashed is mapped to customer_id in sGTM!)
            customer_tps = touchpoints_by_customer.get(lead.email_hashed, [])
            lead_time = lead.placed_at

            valid_tps = [
                tp for tp in customer_tps
                if tp.occurred_at <= lead_time and tp.occurred_at >= (lead_time - window_delta)
            ]

            if attribution_model == "last_touch":
                valid_tps.sort(key=lambda x: x.occurred_at, reverse=True)

            if valid_tps and valid_tps[0].campaign_id:
                lead_attribution[lead.id] = valid_tps[0].campaign_id
            else:
                lead_attribution[lead.id] = "ORGANIC"

        # Aggregate breakdowns by campaign (deal value of closed_won leads)
        campaign_breakdowns = {}
        for lead in leads:
            campaign_id = lead_attribution.get(lead.id, "ORGANIC")
            if campaign_id not in campaign_breakdowns:
                campaign_breakdowns[campaign_id] = {
                    "gross_revenue_minor": 0,
                    "discount_minor": 0,
                    "cogs_minor": 0,
                    "fulfillment_minor": 0,
                    "marketplace_fee_minor": 0,
                    "refunds_minor": 0,
                    "contribution_margin_minor": 0, # Net deal profit
                    "estimated_cogs": False
                }
            
            if lead.status == "closed_won":
                val = lead.deal_value_minor or 0
                cur = campaign_breakdowns[campaign_id]
                cur["gross_revenue_minor"] += val
                cur["contribution_margin_minor"] += val # Net profit is the deal value for service brands

        # Aggregate Spend, clicks, and generate report
        campaign_spend = {}
        for sf in spend_facts:
            campaign_spend[sf.campaign_id] = campaign_spend.get(sf.campaign_id, 0) + sf.amount_minor

        campaign_clicks = {}
        for tp in touchpoints:
            if tp.type == "click":
                camp_id = tp.campaign_id or "ORGANIC"
                campaign_clicks[camp_id] = campaign_clicks.get(camp_id, 0) + 1

        campaign_leads_count = {}
        for lead_id, camp_id in lead_attribution.items():
            campaign_leads_count[camp_id] = campaign_leads_count.get(camp_id, 0) + 1

        reports = []
        for c in campaigns:
            spend = campaign_spend.get(c.id, 0)
            bd = campaign_breakdowns.get(c.id, {
                "gross_revenue_minor": 0,
                "discount_minor": 0,
                "cogs_minor": 0,
                "fulfillment_minor": 0,
                "marketplace_fee_minor": 0,
                "refunds_minor": 0,
                "contribution_margin_minor": 0,
                "estimated_cogs": False
            })
            poas = round(bd["contribution_margin_minor"] / spend, 2) if spend > 0 else None
            roas = round(bd["gross_revenue_minor"] / spend, 2) if spend > 0 else None
            ipoas = round(poas * alpha_inc, 2) if poas is not None else None
            clicks = campaign_clicks.get(c.id, 0)
            leads_count = campaign_leads_count.get(c.id, 0)

            reports.append({
                "campaign_id": c.id,
                "campaign_name": c.name,
                "platform": c.platform,
                "status": c.status,
                "spend_minor": spend,
                "contribution_margin_minor": bd["contribution_margin_minor"],
                "poas": poas,
                "roas": roas,
                "ipoas": ipoas,
                "alpha_inc": alpha_inc,
                "breakdown": {
                    **bd,
                    "spend_minor": spend
                },
                "clicks": clicks,
                "orders": leads_count # Map leads to "orders" in report to maintain identical schema!
            })

        organic_bd = campaign_breakdowns.get("ORGANIC")
        if organic_bd and (organic_bd["contribution_margin_minor"] > 0 or organic_bd["gross_revenue_minor"] > 0):
            reports.append({
                "campaign_id": "ORGANIC",
                "campaign_name": "Organic Traffic (Unattributed)",
                "platform": "organic",
                "status": "active",
                "spend_minor": 0,
                "contribution_margin_minor": organic_bd["contribution_margin_minor"],
                "poas": None,
                "roas": None,
                "ipoas": None,
                "alpha_inc": alpha_inc,
                "breakdown": {
                    **organic_bd,
                    "spend_minor": 0
                },
                "clicks": campaign_clicks.get("ORGANIC", 0),
                "orders": campaign_leads_count.get("ORGANIC", 0)
            })

        def sort_key(report):
            is_organic = 0 if report["campaign_id"] == "ORGANIC" else 1
            poas_val = report["poas"] if report["poas"] is not None else -1e9
            spend_val = report["spend_minor"]
            return (is_organic, poas_val, -spend_val)

        reports.sort(key=sort_key)
        return reports

    # 1. Fetch all relevant tables
    orders_q = await s.execute(select(Order).where(Order.tenant_id == tenant_id, Order.brand_id == brand_id))
    orders = orders_q.scalars().all()

    order_lines_q = await s.execute(
        select(OrderLine)
        .join(Order, Order.id == OrderLine.order_id)
        .where(OrderLine.tenant_id == tenant_id, Order.brand_id == brand_id)
    )
    order_lines = order_lines_q.scalars().all()

    refunds_q = await s.execute(
        select(Refund)
        .join(OrderLine, OrderLine.id == Refund.order_line_id)
        .join(Order, Order.id == OrderLine.order_id)
        .where(Refund.tenant_id == tenant_id, Order.brand_id == brand_id)
    )
    refunds = refunds_q.scalars().all()

    fulfillment_q = await s.execute(
        select(FulfillmentCost)
        .join(Order, Order.id == FulfillmentCost.order_id)
        .where(FulfillmentCost.tenant_id == tenant_id, Order.brand_id == brand_id)
    )
    fulfillment_costs = fulfillment_q.scalars().all()

    campaigns_q = await s.execute(select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.brand_id == brand_id))
    campaigns = campaigns_q.scalars().all()

    spend_facts_q = await s.execute(
        select(SpendFact)
        .join(Campaign, Campaign.id == SpendFact.campaign_id)
        .where(SpendFact.tenant_id == tenant_id, Campaign.brand_id == brand_id)
    )
    spend_facts = spend_facts_q.scalars().all()

    touchpoints_q = await s.execute(
        select(Touchpoint)
        .join(Campaign, Campaign.id == Touchpoint.campaign_id)
        .where(Touchpoint.tenant_id == tenant_id, Campaign.brand_id == brand_id)
    )
    touchpoints = touchpoints_q.scalars().all()

    # 2. Build refund mapping by order_line_id
    refund_map = {}
    for r in refunds:
        refund_map[r.order_line_id] = refund_map.get(r.order_line_id, 0) + r.amount_minor

    # 3. Build fulfillment cost mapping by order_id
    fulfillment_map = {}
    for fc in fulfillment_costs:
        fulfillment_map[fc.order_id] = {
            "shipping": fc.shipping_cost_minor,
            "marketplace": fc.marketplace_fee_minor
        }

    # 4. Group order lines by order_id and compute line-level gross metrics
    order_lines_by_order = {}
    for ol in order_lines:
        discount = ol.line_discount_minor
        qty = ol.qty
        gross_revenue = (ol.unit_price_minor - discount) * qty
        unit_cost = ol.unit_cost_minor or 0
        gross_margin = (ol.unit_price_minor - discount - unit_cost) * qty
        discount_amount = discount * qty
        cogs = unit_cost * qty
        estimated_cogs = ol.unit_cost_minor is None

        line_info = {
            "line_id": ol.id,
            "gross_revenue": gross_revenue,
            "gross_margin": gross_margin,
            "discount_amount": discount_amount,
            "cogs": cogs,
            "estimated_cogs": estimated_cogs
        }
        if ol.order_id not in order_lines_by_order:
            order_lines_by_order[ol.order_id] = []
        order_lines_by_order[ol.order_id].append(line_info)

    # 5. Compute order-level cost breakdown
    order_breakdown_map = {}
    for order in orders:
        lines = order_lines_by_order.get(order.id, [])
        order_gross_revenue = sum(l["gross_revenue"] for l in lines)

        fc = fulfillment_map.get(order.id, {"shipping": 0, "marketplace": 0})
        total_fulfillment = fc["shipping"] + fc["marketplace"]

        order_contribution = 0
        order_cogs = 0
        order_discount = 0
        order_refund = 0
        estimated_cogs_flag = False

        positive_lines = [l for l in lines if l["gross_revenue"] > 0]
        sum_positive_gross_rev = sum(l["gross_revenue"] for l in positive_lines)

        allocated_fulfillment_map = {}
        if sum_positive_gross_rev > 0:
            floored_allocations = []
            leftover = total_fulfillment
            for l in positive_lines:
                val = (l["gross_revenue"] / sum_positive_gross_rev) * total_fulfillment
                base = int(val)
                rem = val - base
                floored_allocations.append({
                    "line_id": l["line_id"],
                    "base": base,
                    "rem": rem
                })
                leftover -= base
            
            floored_allocations.sort(key=lambda x: x["rem"], reverse=True)
            for i in range(leftover):
                floored_allocations[i]["base"] += 1
            
            allocated_fulfillment_map = {x["line_id"]: x["base"] for x in floored_allocations}
        elif len(lines) > 0:
            base = total_fulfillment // len(lines)
            leftover = total_fulfillment % len(lines)
            for idx, l in enumerate(lines):
                allocated_fulfillment_map[l["line_id"]] = base + (1 if idx < leftover else 0)

        for line in lines:
            refunded = refund_map.get(line["line_id"], 0)
            allocated_fulfillment = allocated_fulfillment_map.get(line["line_id"], 0)

            line_contribution = line["gross_margin"] - refunded - allocated_fulfillment
            order_contribution += line_contribution
            order_cogs += line["cogs"]
            order_discount += line["discount_amount"]
            order_refund += refunded
            if line["estimated_cogs"]:
                estimated_cogs_flag = True

        order_breakdown_map[order.id] = {
            "gross_revenue_minor": order_gross_revenue,
            "discount_minor": order_discount,
            "cogs_minor": order_cogs,
            "fulfillment_minor": fc["shipping"],
            "marketplace_fee_minor": fc["marketplace"],
            "refunds_minor": order_refund,
            "contribution_margin_minor": order_contribution,
            "estimated_cogs": estimated_cogs_flag
        }

    # 6. Attribution (configurable lookup window)
    touchpoints_by_customer = {}
    for tp in touchpoints:
        if not tp.customer_id:
            continue
        if tp.customer_id not in touchpoints_by_customer:
            touchpoints_by_customer[tp.customer_id] = []
        touchpoints_by_customer[tp.customer_id].append(tp)

    order_attribution = {}
    window_delta = dt.timedelta(days=attribution_window_days)

    for order in orders:
        if not order.customer_id:
            order_attribution[order.id] = "ORGANIC"
            continue

        customer_tps = touchpoints_by_customer.get(order.customer_id, [])
        order_time = order.placed_at

        # Filter valid touchpoints
        valid_tps = [
            tp for tp in customer_tps
            if tp.occurred_at <= order_time and tp.occurred_at >= (order_time - window_delta)
        ]

        # Apply attribution model
        if attribution_model == "last_touch":
            valid_tps.sort(key=lambda x: x.occurred_at, reverse=True)
        # (Could support other attribution models here in the future)

        if valid_tps and valid_tps[0].campaign_id:
            order_attribution[order.id] = valid_tps[0].campaign_id
        else:
            order_attribution[order.id] = "ORGANIC"

    # 7. Aggregate breakdowns by campaign
    campaign_breakdowns = {}
    for order_id, bd in order_breakdown_map.items():
        campaign_id = order_attribution.get(order_id, "ORGANIC")
        if campaign_id not in campaign_breakdowns:
            campaign_breakdowns[campaign_id] = {
                "gross_revenue_minor": 0,
                "discount_minor": 0,
                "cogs_minor": 0,
                "fulfillment_minor": 0,
                "marketplace_fee_minor": 0,
                "refunds_minor": 0,
                "contribution_margin_minor": 0,
                "estimated_cogs": False
            }
        cur = campaign_breakdowns[campaign_id]
        cur["gross_revenue_minor"] += bd["gross_revenue_minor"]
        cur["discount_minor"] += bd["discount_minor"]
        cur["cogs_minor"] += bd["cogs_minor"]
        cur["fulfillment_minor"] += bd["fulfillment_minor"]
        cur["marketplace_fee_minor"] += bd["marketplace_fee_minor"]
        cur["refunds_minor"] += bd["refunds_minor"]
        cur["contribution_margin_minor"] += bd["contribution_margin_minor"]
        cur["estimated_cogs"] = cur["estimated_cogs"] or bd["estimated_cogs"]

    # 8. Spend facts mapping
    campaign_spend = {}
    for sf in spend_facts:
        campaign_spend[sf.campaign_id] = campaign_spend.get(sf.campaign_id, 0) + sf.amount_minor

    # 9. Click and orders counts
    campaign_clicks = {}
    for tp in touchpoints:
        if tp.type == "click":
            camp_id = tp.campaign_id or "ORGANIC"
            campaign_clicks[camp_id] = campaign_clicks.get(camp_id, 0) + 1

    campaign_orders_count = {}
    for order_id, camp_id in order_attribution.items():
        campaign_orders_count[camp_id] = campaign_orders_count.get(camp_id, 0) + 1

    # 10. Generate final reports
    reports = []
    for c in campaigns:
        spend = campaign_spend.get(c.id, 0)
        bd = campaign_breakdowns.get(c.id, {
            "gross_revenue_minor": 0,
            "discount_minor": 0,
            "cogs_minor": 0,
            "fulfillment_minor": 0,
            "marketplace_fee_minor": 0,
            "refunds_minor": 0,
            "contribution_margin_minor": 0,
            "estimated_cogs": False
        })
        
        # Compute POAS and ROAS
        poas = round(bd["contribution_margin_minor"] / spend, 2) if spend > 0 else None
        roas = round(bd["gross_revenue_minor"] / spend, 2) if spend > 0 else None
        ipoas = round(poas * alpha_inc, 2) if poas is not None else None
        clicks = campaign_clicks.get(c.id, 0)
        orders_count = campaign_orders_count.get(c.id, 0)

        reports.append({
            "campaign_id": c.id,
            "campaign_name": c.name,
            "platform": c.platform,
            "status": c.status,
            "spend_minor": spend,
            "contribution_margin_minor": bd["contribution_margin_minor"],
            "poas": poas,
            "roas": roas,
            "ipoas": ipoas,
            "alpha_inc": alpha_inc,
            "breakdown": {
                **bd,
                "spend_minor": spend
            },
            "clicks": clicks,
            "orders": orders_count
        })

    # Add ORGANIC pseudo-campaign report
    organic_bd = campaign_breakdowns.get("ORGANIC")
    if organic_bd and (organic_bd["contribution_margin_minor"] > 0 or organic_bd["gross_revenue_minor"] > 0):
        reports.append({
            "campaign_id": "ORGANIC",
            "campaign_name": "Organic Traffic (Unattributed)",
            "platform": "organic",
            "status": "active",
            "spend_minor": 0,
            "contribution_margin_minor": organic_bd["contribution_margin_minor"],
            "poas": None,
            "roas": None,
            "ipoas": None,
            "alpha_inc": alpha_inc,
            "breakdown": {
                **organic_bd,
                "spend_minor": 0
            },
            "clicks": campaign_clicks.get("ORGANIC", 0),
            "orders": campaign_orders_count.get("ORGANIC", 0)
        })

    # Sort logic: Organic (Null poas) at top, then POAS ASC, then Spend DESC
    def sort_key(report):
        is_organic = 0 if report["campaign_id"] == "ORGANIC" else 1
        poas_val = report["poas"] if report["poas"] is not None else -1e9
        spend_val = report["spend_minor"]
        # Python sort ascending:
        # Tuple: (is_organic, poas_val, -spend_val)
        return (is_organic, poas_val, -spend_val)

    reports.sort(key=sort_key)
    return reports
