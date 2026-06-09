# Agency OS — VAR Reconciliation & Offline Conversion Tracking (OCT)
import dataclasses
import typing

@dataclasses.dataclass
class Opportunity:
    deal_id: str
    tenant_id: str
    value: float
    stage: str
    gclid: typing.Optional[str] = None  # Google Click ID for attribution retargeting
    updated_at: str = "now"


class VarReconciler:
    """Calculates VAR and generates conversion adjustment payloads for ad APIs."""

    def __init__(self, stage_probabilities: typing.Dict[str, float]):
        self.stage_probabilities = stage_probabilities

    def get_probability(self, stage: str) -> float:
        """Returns the win probability for a given CRM stage."""
        return self.stage_probabilities.get(stage, 0.0)

    def calculate_var(self, opportunities: typing.List[Opportunity]) -> float:
        """Calculates total Value-Adjusted Revenue (VAR)."""
        var_total = 0.0
        for opp in opportunities:
            prob = self.get_probability(opp.stage)
            var_total += opp.value * prob
        return var_total

    def calculate_lqs(
        self,
        email: str,
        form_submission_speed_sec: float,
        sentiment_score: float
    ) -> float:
        """Calculates Lead Quality Score (LQS) out of 100.0.

        Args:
            email: Candidate lead email.
            form_submission_speed_sec: Time in seconds to complete the form.
            sentiment_score: Initial conversational tone (-1.0 to 1.0).

        Returns:
            LQS score value.
        """
        score = 0.0

        # 1. Email Domain Authority Check (+50 for business, +10 for personal)
        free_domains = {
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
            "aol.com",
        }
        domain = email.split("@")[-1].strip().lower()
        if domain not in free_domains:
            score += 50.0
        else:
            score += 10.0

        # 2. Bot/Submission Speed Check
        if form_submission_speed_sec >= 2.0:
            if form_submission_speed_sec <= 30.0:
                score += 20.0  # Human pace
            else:
                score += 10.0  # Slow submitter

        # 3. Sentiment Tone mapping (+30 max)
        if sentiment_score > 0.0:
            score += min(30.0, sentiment_score * 30.0)

        return min(100.0, score)

    def reconcile_and_retrain(
        self,
        old_opportunities: typing.List[Opportunity],
        new_opportunities: typing.List[Opportunity]
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Identifies stage transitions and yields conversion adjustments for OCT.
        
        Compares old and new states of opportunities. If a stage changes,
        it calculates the delta in value-adjusted revenue and yields
        an adjustment event to be pushed to the ad networks.
        """
        old_map = {opp.deal_id: opp for opp in old_opportunities}
        adjustment_events = []

        for new_opp in new_opportunities:
            old_opp = old_map.get(new_opp.deal_id)
            if not old_opp:
                # New deal discovered: Initial VAR creation
                old_prob = 0.0
                old_var = 0.0
            else:
                old_prob = self.get_probability(old_opp.stage)
                old_var = old_opp.value * old_prob

            new_prob = self.get_probability(new_opp.stage)
            new_var = new_opp.value * new_prob

            # If probability changed (stage transitioned) or deal value was updated
            old_value = old_opp.value if old_opp else 0.0
            if old_prob != new_prob or old_value != new_opp.value:
                adjustment_delta = new_var - old_var
                
                # We only trigger OCT adjustments if there is a tracking ID (gclid)
                if new_opp.gclid:
                    adjustment_events.append({
                        "gclid": new_opp.gclid,
                        "deal_id": new_opp.deal_id,
                        "tenant_id": new_opp.tenant_id,
                        "old_stage": old_opp.stage if old_opp else "NEW",
                        "new_stage": new_opp.stage,
                        "adjustment_value": adjustment_delta,
                        "action_type": "AMPLIFY" if adjustment_delta > 0 else "RETRACT"
                    })
        
        return adjustment_events
