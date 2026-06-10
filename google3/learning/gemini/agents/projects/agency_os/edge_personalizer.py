"""Agency OS — Edge-Based Personalization Engine.

Resolves dynamic website layout variants (headlines, coupons) based on UTM
parameters parsed from the landing page URL at the network edge.
"""

import dataclasses
import typing

@dataclasses.dataclass
class PersonalizationRule:
    utm_param: str       # e.g., 'utm_content'
    trigger_value: str   # e.g., 'discount20'
    variant_payload: typing.Dict[str, typing.Any]  # e.g., {'headline': 'Get 20% off!'}


class EdgePersonalizer:
    """Matches UTM parameters to custom variant payloads at edge."""

    def __init__(self, rules: typing.List[PersonalizationRule]):
        self.rules = rules
        self.default_variant = {
            "headline": "Welcome to Abley's Premium Sweaters",
            "coupon_code": None
        }

    def resolve_variant(
        self,
        query_params: typing.Dict[str, str]
    ) -> typing.Dict[str, typing.Any]:
        """Scans query params and returns first matching variant.

        Args:
            query_params: Extracted query arguments from request URL.

        Returns:
            Resolved variant details.
        """
        # Make comparison case-insensitive for robustness
        params_lower = {k.lower(): v.lower() for k, v in query_params.items()}

        for rule in self.rules:
            param_key = rule.utm_param.lower()
            if param_key in params_lower:
                if params_lower[param_key] == rule.trigger_value.lower():
                    return rule.variant_payload

        return self.default_variant
