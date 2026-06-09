"""Agency OS — Financial Formulas Engine.

This module provides standard formulas for contribution margins and POAS.
"""

def calculate_cm1(gross_revenue: float, cogs: float) -> float:
    """Calculates Contribution Margin 1: Gross Revenue (Net of GST) - COGS.

    Args:
        gross_revenue: Gross sales revenue net of tax.
        cogs: Cost of Goods Sold.

    Returns:
        Contribution Margin 1.
    """
    return gross_revenue - cogs


def calculate_cm2(
    cm1: float,
    fulfillment: float,
    payment_gateway: float,
    cod_remittance: float,
    refunds: float
) -> float:
    """Calculates Contribution Margin 2.

    Formula: CM1 - Fulfillment - Payment Gateway - COD - Refunds.

    Args:
        cm1: Contribution Margin 1.
        fulfillment: Fulfillment and shipping costs.
        payment_gateway: Gateway processing fees.
        cod_remittance: COD handling fees.
        refunds: Refunds and reverse logistics.

    Returns:
        Contribution Margin 2.
    """
    return cm1 - fulfillment - payment_gateway - cod_remittance - refunds


def calculate_cm3(
    cm2: float,
    allocated_infra: float,
    allocated_labour: float,
    allocated_support: float,
    allocated_acquisition: float
) -> float:
    """Calculates Contribution Margin 3.

    Formula: CM2 - Infra - Labour - Support - Acquisition.

    Args:
        cm2: Contribution Margin 2.
        allocated_infra: Allocated infrastructure subscriptions.
        allocated_labour: Allocated warehouse/admin labour.
        allocated_support: Customer support agent allocations.
        allocated_acquisition: Referrals, affiliates, acquisition payouts.

    Returns:
        Contribution Margin 3.
    """
    return cm2 - (
        allocated_infra + allocated_labour +
        allocated_support + allocated_acquisition
    )


def calculate_net_ad_spend(
    gross_ad_spend: float,
    tax_divisor: float = 1.18
) -> float:
    """Adjusts gross ad spend to back out local taxes.

    Args:
        gross_ad_spend: Raw ad spend reported by platforms.
        tax_divisor: Divisor to back out taxes (default 1.18 for 18% GST).

    Returns:
        Net ad spend adjusted for local taxes.

    Raises:
        ValueError: If tax_divisor is less than or equal to zero.
    """
    if tax_divisor <= 0:
        raise ValueError("Tax divisor must be greater than zero.")
    return gross_ad_spend / tax_divisor


def calculate_poas(cm3: float, net_ad_spend: float) -> float:
    """Calculates Profit on Ad Spend: CM3 / Net Ad Spend.

    Args:
        cm3: Contribution Margin 3.
        net_ad_spend: Net ad spend net of local taxes.

    Returns:
        POAS ratio. Returns 0.0 if net_ad_spend is zero.
    """
    if net_ad_spend == 0.0:
        return 0.0
    return cm3 / net_ad_spend
