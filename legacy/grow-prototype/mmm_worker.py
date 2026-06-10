"""Agency OS — Marketing Mix Modeling (MMM) Worker.

Calculates Incremental POAS (iPOAS) by subtracting baseline organic click values
and generates budget reallocation recommendations across campaign channels.
"""

import typing

class MmmWorker:
    """Calculates incrementality metrics and makes cross-channel budget shifts."""

    def __init__(self):
        pass

    def calculate_ipoas(
        self,
        cm3: float,
        baseline_clicks: float,
        target_value_per_click: float,
        net_ad_spend: float
    ) -> float:
        """Calculates Incremental POAS (iPOAS).

        Formula: (CM3 - (Baseline Clicks * Target Value Per Click)) / Net Ad Spend.

        Args:
            cm3: Contribution Margin 3 (including ad effects).
            baseline_clicks: Historical daily baseline clicks.
            target_value_per_click: Assigned PPC value of organic click.
            net_ad_spend: Tax-adjusted ad spend.

        Returns:
            iPOAS ratio. Returns 0.0 if net_ad_spend is zero.
        """
        if net_ad_spend <= 0:
            return 0.0

        baseline_value = baseline_clicks * target_value_per_click
        incremental_margin = cm3 - baseline_value

        return incremental_margin / net_ad_spend

    def generate_reallocation_recommendations(
        self,
        campaigns: typing.List[typing.Dict[str, typing.Any]],
        target_ipoas: float = 1.2
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Identifies budget reallocations based on campaign iPOAS performance.

        Args:
            campaigns: List of campaigns containing 'campaign_id', 'name',
              'net_spend', and 'ipoas'.
            target_ipoas: Minimum threshold to receive budget boosts.

        Returns:
            List of proposed BUDGET_REALLOCATION payload parameters.
        """
        underperforming = []
        scaling_candidates = []

        for camp in campaigns:
            c_id = camp["campaign_id"]
            ipoas = camp["ipoas"]
            spend = camp["net_spend"]

            if ipoas < 1.0 and spend > 0:
                underperforming.append(camp)
            elif ipoas >= target_ipoas:
                scaling_candidates.append(camp)

        reallocations = []
        # Pair underperforming spends with scaling candidates to shift budgets
        for low_camp in underperforming:
            if not scaling_candidates:
                break
            # Pick the best performing target
            target_camp = max(scaling_candidates, key=lambda c: c["ipoas"])

            # Recommend shifting 20% of underperforming budget to the scaling candidate
            shift_amount = low_camp["net_spend"] * 0.20
            if shift_amount > 0:
                reallocations.append({
                    "source_campaign_id": low_camp["campaign_id"],
                    "target_campaign_id": target_camp["campaign_id"],
                    "amount": round(shift_amount, 2),
                    "reason": (
                        f"Cannibalization protection: campaign '{low_camp['name']}' "
                        f"has iPOAS {low_camp['ipoas']:.2f} < 1.0 (unprofitable). "
                        f"Reallocating 20% of spend to '{target_camp['name']}' "
                        f"with iPOAS {target_camp['ipoas']:.2f}."
                    )
                })

        return reallocations
