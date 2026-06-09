"""Agency OS — Predictive LTV (pLTV) Cohort Engine.

Groups customer transaction values into cohorts and calculates LTV expansion
multipliers to project long-term values of newer cohorts.
"""

import dataclasses
import typing

@dataclasses.dataclass
class Cohort:
    cohort_name: str  # e.g., '2026-01'
    day30_value: float
    day90_value: float = 0.0
    projected_ltv: float = 0.0


class PltvEngine:
    """Calculates historical cohort multipliers and projects future LTV."""

    def __init__(self):
        pass

    def calculate_historical_multipliers(
        self,
        mature_cohorts: typing.List[Cohort]
    ) -> float:
        """Computes the Day 90 LTV expansion multiplier from mature cohorts.

        Multiplier = Day 90 Value / Day 30 Value.

        Args:
            mature_cohorts: Cohorts that have completed their Day 90 window.

        Returns:
            Average expansion multiplier. Returns 1.0 if no cohorts are mature
            or if division is invalid.
        """
        valid_multipliers = []
        for c in mature_cohorts:
            if c.day30_value > 0 and c.day90_value > 0:
                valid_multipliers.append(c.day90_value / c.day30_value)

        if not valid_multipliers:
            return 1.0

        return sum(valid_multipliers) / len(valid_multipliers)

    def project_cohort_ltv(
        self,
        active_cohorts: typing.List[Cohort],
        multiplier: float
    ) -> typing.List[Cohort]:
        """Projects the Day 90 LTV for newer cohorts based on Day 30 performance.

        Args:
            active_cohorts: List of newer cohorts to project.
            multiplier: The resolved LTV multiplier to apply.

        Returns:
            Updated cohorts list with projected_ltv fields set.
        """
        projected = []
        for c in active_cohorts:
            projected_c = dataclasses.replace(c)
            # If the cohort already has actual day90 value, use that as the target,
            # otherwise project it.
            if projected_c.day90_value > 0:
                projected_c.projected_ltv = projected_c.day90_value
            else:
                projected_c.projected_ltv = projected_c.day30_value * multiplier
            projected.append(projected_c)
        return projected
