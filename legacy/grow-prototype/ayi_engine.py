"""Agency OS — GSC Organic Lift & Awareness Yield Index (AYI) Engine."""

import dataclasses
import typing


@dataclasses.dataclass
class GscMetric:
    date: str
    query: str
    clicks: int
    impressions: int


class AyiEngine:
    """Calculates organic search lift and the Awareness Yield Index (AYI)."""

    def __init__(
        self,
        brand_keywords: typing.List[str],
        target_value_per_click: float
    ):
        """Initializes the engine.

        Args:
            brand_keywords: List of brand terms to filter query search.
            target_value_per_click: The value assigned to an organic brand
              click, typically based on target Google Ads brand PPC CPC bid.
        """
        self.brand_keywords = [kw.lower() for kw in brand_keywords]
        self.target_value_per_click = target_value_per_click

    def _is_brand_query(self, query: str) -> bool:
        """Helper to determine if a query is a brand query."""
        q_lower = query.lower()
        return any(brand_kw in q_lower for brand_kw in self.brand_keywords)

    def calculate_baseline_clicks(
        self,
        historical_data: typing.List[GscMetric]
    ) -> float:
        """Calculates historical baseline daily clicks for brand queries.

        Args:
            historical_data: List of GSC metric entries over a baseline period.

        Returns:
            Average daily clicks for brand queries.
        """
        brand_clicks_by_date: typing.Dict[str, int] = {}
        for entry in historical_data:
            if self._is_brand_query(entry.query):
                brand_clicks_by_date[entry.date] = (
                    brand_clicks_by_date.get(entry.date, 0) + entry.clicks
                )

        if not brand_clicks_by_date:
            return 0.0

        total_clicks = sum(brand_clicks_by_date.values())
        total_days = len(brand_clicks_by_date)
        return total_clicks / total_days

    def calculate_current_brand_clicks(
        self,
        current_data: typing.List[GscMetric]
    ) -> float:
        """Sums up the brand clicks in the current measurement window.

        Args:
            current_data: GSC metrics for the current window.

        Returns:
            Total brand clicks in this window.
        """
        total_brand_clicks = 0
        for entry in current_data:
            if self._is_brand_query(entry.query):
                total_brand_clicks += entry.clicks
        return float(total_brand_clicks)

    def calculate_organic_lift(
        self,
        current_brand_clicks: float,
        baseline_clicks: float
    ) -> float:
        """Computes organic lift as current clicks minus the baseline.

        Note: baseline_clicks should be scaled to match the duration of the
        current window, or compared on a per-day equivalent rate. Here we
        assume the inputs are already comparable (e.g. daily click totals).

        Args:
            current_brand_clicks: Clicks in current period.
            baseline_clicks: Baseline clicks in comparable period.

        Returns:
            The organic lift value (can be negative if search interest dropped).
        """
        return current_brand_clicks - baseline_clicks

    def calculate_cm3_awareness(self, organic_lift: float) -> float:
        """Calculates CM3 Awareness (Value of brand lift).

        Formula: Organic Lift * Target PPC Value Per Click.

        Args:
            organic_lift: Clicks representing organic brand search lift.

        Returns:
            Imputed financial value of the organic brand lift.
        """
        # We only impute value if lift is positive
        if organic_lift <= 0:
            return 0.0
        return organic_lift * self.target_value_per_click

    def calculate_ayi(
        self,
        cm3_awareness: float,
        net_ad_spend: float
    ) -> float:
        """Calculates Awareness Yield Index (AYI) = CM3 Awareness / Net Ad Spend.

        Args:
            cm3_awareness: Imputed value of organic search lift.
            net_ad_spend: Total net ad spend in the same period.

        Returns:
            AYI ratio. Returns 0.0 if net_ad_spend is zero.
        """
        if net_ad_spend == 0.0:
            return 0.0
        return cm3_awareness / net_ad_spend

    def calculate_sov(
        self,
        brand_impressions: float,
        total_market_impressions: float
    ) -> float:
        """Calculates Share of Voice (SOV) as percentage.

        Args:
            brand_impressions: Impressions served by target brand.
            total_market_impressions: Aggregated total impressions in market.

        Returns:
            SOV percentage.
        """
        if total_market_impressions <= 0.0:
            return 0.0
        return (brand_impressions / total_market_impressions) * 100.0
