"""Agency OS — Agency Trust Score (ATS) Calculator.

Calculates the active trust score for a brand tenant based on technical audit
results, catalog feed alignment, and brand reputation alerts. Maps this score
to an operational AI Autonomy Tier (Tier 0, 1, or 2).
"""

class AtsCalculator:
    """Computes the Agency Trust Score and recommends the autonomy tier."""

    def __init__(self):
        pass

    def calculate_score(
        self,
        gtm_present: bool,
        pixel_present: bool,
        capi_dedup_rate: float,  # 0.0 to 1.0
        gmc_critical_mismatch_count: int,
        gmc_warning_count: int,
        reputation_alert_count: int
    ) -> float:
        """Calculates the Trust Score out of 100.0 with safety deductions."""
        score = 100.0

        # 1. Technical Tag Deductions
        if not gtm_present:
            score -= 30.0
        if not pixel_present:
            score -= 30.0

        # CAPI deduplication deduction (max -20 points if matching is 0%)
        capi_mismatch_rate = 1.0 - max(0.0, min(1.0, capi_dedup_rate))
        score -= capi_mismatch_rate * 20.0

        # 2. FeedX Catalog Deductions
        price_deduction = min(40.0, gmc_critical_mismatch_count * 10.0)
        score -= price_deduction

        warnings_deduction = min(20.0, gmc_warning_count * 5.0)
        score -= warnings_deduction

        # 3. Reputation Deductions
        reputation_deduction = min(45.0, reputation_alert_count * 15.0)
        score -= reputation_deduction

        return max(0.0, min(100.0, score))

    def calculate_dynamic_ats(
        self,
        total_proposed: int,
        approved: int,
        total_auto: int,
        success_auto: int,
        overrides: int,
        days_since_last_override: float
    ) -> float:
        """Calculates Agency Trust Score (ATS) based on historical performance.

        Formula:
          ATS = (approved / total_proposed) * 60.0 +
                (success_auto / total_auto) * 40.0 -
                (overrides * 20.0 * decay_factor)

        Args:
            total_proposed: Total Tier 1/2 cards proposed.
            approved: Tier 1/2 cards approved by user.
            total_auto: Total Tier 0 cards executed.
            success_auto: Tier 0 cards executed without overrides.
            overrides: Client manual rollbacks counts.
            days_since_last_override: Age of the last override in days.

        Returns:
            Calculated score [0.0, 100.0].
        """
        ratio_approved = approved / total_proposed if total_proposed > 0 else 1.0
        ratio_auto = success_auto / total_auto if total_auto > 0 else 1.0

        # Calculate decay factor: Overrides fade over 30 days
        decay_factor = max(0.0, 1.0 - (days_since_last_override / 30.0))
        override_penalty = overrides * 20.0 * decay_factor

        score = (ratio_approved * 60.0) + (ratio_auto * 40.0) - override_penalty
        return max(0.0, min(100.0, score))

    def resolve_autonomy_tier(self, trust_score: float) -> int:
        """Enforces operational graduation restrictions.

        Args:
            trust_score: Calculated ATS score.

        Returns:
            Autonomy Tier:
              2: Full Autonomy (Auto-pilot execution).
              1: Semi-Autonomy (Draft and verify, manual approval needed).
              0: Locked Autonomy (All changes paused, dashboard locked).
        """
        if trust_score >= 85.0:
            return 2
        elif trust_score >= 60.0:
            return 1
        else:
            return 0
