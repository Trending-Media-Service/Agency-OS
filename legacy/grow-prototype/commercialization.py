"""Agency OS — GaaS Commercialization & Saved Spend Yield (SSY) Engine.

Calculates the value-capture pricing fees (1.5% saved spend) and evaluates
monthly pricing tiers for client tenants.
"""

import typing


class CommercializationEngine:
    """Computes Saved Spend Yield and GaaS client subscription fees."""

    def __init__(self):
        pass

    def calculate_saved_spend(
        self,
        daily_ad_group_budgets: typing.Dict[str, float],
        paused_duration_days: typing.Dict[str, float]
    ) -> float:
        """Calculates total Saved Spend Yield (SSY).

        Formula: Sum of (Daily budget of ad group * duration of pause in days)

        Args:
            daily_ad_group_budgets: Map of ad group IDs to daily budget values.
            paused_duration_days: Map of ad group IDs to duration of active pause.

        Returns:
            Saved spend amount.
        """
        total_saved = 0.0
        for ad_group_id, daily_budget in daily_ad_group_budgets.items():
            duration = paused_duration_days.get(ad_group_id, 0.0)
            total_saved += daily_budget * duration
        return total_saved

    def calculate_monthly_fee(
        self,
        tier: str,
        saved_spend: float
    ) -> float:
        """Calculates value-capture pricing fee invoice for a client tenant.

        Tiers:
          - 'STARTER': $299.0 base fee + 1.5% of Saved Spend.
          - 'PROFESSIONAL': $999.0 base fee + 1.0% of Saved Spend.
          - 'ENTERPRISE': $2499.0 base fee + 0.5% of Saved Spend.

        Args:
            tier: Client subscription tier name.
            saved_spend: Calculated Saved Spend value.

        Returns:
            Monthly fee invoice amount.
        """
        base_fee: float
        fee_percentage: float

        tier_upper = tier.upper().strip()
        if tier_upper == "STARTER":
            base_fee = 299.0
            fee_percentage = 0.015
        elif tier_upper == "PROFESSIONAL":
            base_fee = 999.0
            fee_percentage = 0.010
        elif tier_upper == "ENTERPRISE":
            base_fee = 2499.0
            fee_percentage = 0.005
        else:
            raise ValueError(f"Unknown subscription tier '{tier}'.")

        saved_spend_yield_fee = saved_spend * fee_percentage
        return base_fee + saved_spend_yield_fee
