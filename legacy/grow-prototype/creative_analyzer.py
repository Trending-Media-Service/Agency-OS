"""Agency OS — Creative Vision/Copy Feature Tagging Pipeline.

Aggregates conversion rate (CVR) statistics by creative attribute tags
(e.g., visual colors, copy hooks) to identify winning and losing features.
"""

import dataclasses
import typing

@dataclasses.dataclass
class AdPerformance:
    ad_id: str
    campaign_id: str
    spend: float
    conversions: int
    clicks: int
    attributes: typing.Dict[str, typing.Any]  # e.g. {'color': 'red', 'hook': 'question'}


class CreativeAnalyzer:
    """Analyzes ad creative features and recommends copy/visual pauses."""

    def __init__(self):
        pass

    def analyze_features(
        self,
        ads: typing.List[AdPerformance]
    ) -> typing.Dict[str, typing.Dict[typing.Any, typing.Dict[str, float]]]:
        """Aggregates performance stats by creative attribute values.

        Args:
            ads: List of historical ad performances.

        Returns:
            Dictionary structure mapping attributes to stats:
              { attribute_name: { value: { 'cvr': float, 'spend': float } } }
        """
        stats: typing.Dict[str, typing.Dict[typing.Any, typing.Dict[str, float]]] = {}

        for ad in ads:
            cvr = ad.conversions / ad.clicks if ad.clicks > 0 else 0.0
            for attr_name, attr_val in ad.attributes.items():
                if attr_name not in stats:
                    stats[attr_name] = {}
                if attr_val not in stats[attr_name]:
                    stats[attr_name][attr_val] = {
                        "total_spend": 0.0,
                        "total_clicks": 0.0,
                        "total_conversions": 0.0
                    }

                stats[attr_name][attr_val]["total_spend"] += ad.spend
                stats[attr_name][attr_val]["total_clicks"] += ad.clicks
                stats[attr_name][attr_val]["total_conversions"] += ad.conversions

        # Normalize metrics to get CVR
        normalized: typing.Dict[str, typing.Dict[typing.Any, typing.Dict[str, float]]] = {}
        for attr_name, val_map in stats.items():
            normalized[attr_name] = {}
            for attr_val, aggregates in val_map.items():
                clicks = aggregates["total_clicks"]
                conversions = aggregates["total_conversions"]
                avg_cvr = conversions / clicks if clicks > 0 else 0.0
                
                normalized[attr_name][attr_val] = {
                    "cvr": avg_cvr,
                    "spend": aggregates["total_spend"]
                }

        return normalized

    def recommend_pauses(
        self,
        features_report: typing.Dict[str, typing.Dict[typing.Any, typing.Dict[str, float]]],
        cvr_threshold: float = 0.015,
        min_spend: float = 300.0
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Recommends pausing ad attributes that fall below target CVR.

        Args:
            features_report: Result of analyze_features.
            cvr_threshold: CVR boundary (default 1.5%).
            min_spend: Minimum spend to assert statistical significance (default $300).

        Returns:
            List of optimization payloads.
        """
        recommendations = []
        for attr_name, val_map in features_report.items():
            for attr_val, metrics in val_map.items():
                cvr = metrics["cvr"]
                spend = metrics["spend"]

                if cvr < cvr_threshold and spend >= min_spend:
                    recommendations.append({
                        "attribute": attr_name,
                        "value": attr_val,
                        "cvr": cvr,
                        "spend": spend,
                        "action": "PAUSE_CREATIVE_FEATURE",
                        "reason": (
                            f"Underperforming creative asset: feature '{attr_name}: {attr_val}' "
                            f"has CVR {cvr*100:.2f}% below threshold {cvr_threshold*100:.2f}% "
                            f"(spend ${spend:.2f}). Pause corresponding creatives."
                        )
                    })
        return recommendations
