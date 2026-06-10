"""Agency OS — Autonomy Graduation Runner.

Orchestrates the trust score calculations and resolves action card execution
states according to active Autonomy Tiers (Tier 0, 1, or 2), enforcing OPA safety
rules and stateful resumption queues.
"""

import typing
from google3.learning.gemini.agents.projects.agency_os import action_card_validator
from google3.learning.gemini.agents.projects.agency_os import ats_calculator
from google3.learning.gemini.agents.projects.agency_os import context_constructor


@typing.final
class RunResults(typing.NamedTuple):
    trust_score: float
    autonomy_tier: int
    context_prompt: str
    processed_cards: typing.List[typing.Dict[str, typing.Any]]
    lockout_active: bool
    needs_cogs: bool


class AutonomyGraduationRunner:
    """Executes the state verification cycle for a brand tenant."""

    def __init__(self):
        self.ats_calc = ats_calculator.AtsCalculator()
        self.context_const = context_constructor.ContextConstructor()
        # Stateful Resumption Queue to preserve contexts
        self.stateful_queue: typing.Dict[str, typing.Dict[str, typing.Any]] = {}

    def evaluate_opa_policy(
        self,
        card: typing.Dict[str, typing.Any]
    ) -> typing.Tuple[bool, typing.List[str]]:
        """Enforces shadow governance boundary checks on action card payloads."""
        violations = []
        payload = card.get("payload", {})
        rec_type = card.get("recommendation_type")

        if rec_type == "BID_ADJUSTMENT":
            new_bid = payload.get("new_bid", 0.0)
            old_bid = payload.get("old_bid", 0.0)
            # Bid Cap Ceilings
            if new_bid > 10.0:
                violations.append(
                    f"OPA: new_bid {new_bid} exceeds maximum ceiling cap ($10.00)."
                )
            if old_bid > 0.0 and new_bid > (old_bid * 2.0):
                violations.append(
                    f"OPA: new_bid {new_bid} is more than double the old_bid {old_bid}."
                )

        elif rec_type == "BUDGET_REALLOCATION":
            amount = payload.get("amount", 0.0)
            # Budget Cap Ceilings
            if amount > 5000.0:
                violations.append(
                    f"OPA: budget amount {amount} exceeds safety ceiling ($5000.00)."
                )

        return (len(violations) == 0, violations)

    def queue_approval(
        self,
        card_id: str,
        card: typing.Dict[str, typing.Any],
        context: typing.Dict[str, typing.Any]
    ) -> None:
        """Stores execution context of pending cards in stateful queue."""
        self.stateful_queue[card_id] = {
            "card": card,
            "context": context
        }

    def resume_and_execute(
        self,
        card_id: str,
        user_role: str
    ) -> typing.Dict[str, typing.Any]:
        """Resumes background execution, applying role checks and OPA policies."""
        if card_id not in self.stateful_queue:
            raise KeyError(f"Card ID '{card_id}' not found in stateful queue.")

        # Enforce role matrix checks
        if user_role not in {"CLIENT_EXECUTIVE", "AGENCY_OWNER"}:
            raise PermissionError(
                f"Role '{user_role}' is unauthorized to resume approval queue."
            )

        saved = self.stateful_queue[card_id]
        card = saved["card"].copy()

        # Re-verify OPA rules at time of execution
        is_allowed, violations = self.evaluate_opa_policy(card)
        if not is_allowed:
            card["status"] = "REJECTED"
            card["description"] = f"[REJECTED: OPA Violations: {violations}] {card.get('description', '')}"
            # Evict from queue
            del self.stateful_queue[card_id]
            return {"status": "REJECTED", "card": card}

        card["status"] = "APPROVED"
        # Evict from queue upon success
        del self.stateful_queue[card_id]
        return {"status": "SUCCESS", "card": card}

    def run_autonomy_cycle(
        self,
        tenant_id: str,
        brand_name: str,
        gtm_present: bool,
        pixel_present: bool,
        capi_dedup_rate: float,
        gmc_critical_mismatch_count: int,
        gmc_warning_count: int,
        reputation_alert_count: int,
        financial_metrics: typing.Dict[str, float],
        open_alerts: typing.List[typing.Dict[str, typing.Any]],
        proposed_cards: typing.List[typing.Dict[str, typing.Any]]
    ) -> RunResults:
        """Runs one lifecycle sweep, updating proposed Action Card states.

        Args:
            tenant_id: Active tenant ID.
            brand_name: Brand identifier.
            gtm_present: Google Tag Manager health status.
            pixel_present: Meta Pixel health status.
            capi_dedup_rate: Conversions API event match rate.
            gmc_critical_mismatch_count: Price feed discrepancies.
            gmc_warning_count: Availability feed discrepancies.
            reputation_alert_count: Threat review incidents found.
            financial_metrics: Active margins and ROI stats dictionary.
            open_alerts: Open alerts list.
            proposed_cards: Action cards suggested by AI optimizing run.

        Returns:
            A RunResults named tuple with active statuses and updated card enums.
        """
        # 1. Zero-Order Cold Start Logic check
        needs_cogs = False
        if "COGS" not in financial_metrics or financial_metrics["COGS"] is None:
            needs_cogs = True

        # 2. Resolve trust level
        score = self.ats_calc.calculate_score(
            gtm_present,
            pixel_present,
            capi_dedup_rate,
            gmc_critical_mismatch_count,
            gmc_warning_count,
            reputation_alert_count
        )
        tier = self.ats_calc.resolve_autonomy_tier(score)
        lockout = (tier == 0)

        # 3. Build system prompt context
        prompt = self.context_const.construct_agent_context(
            tenant_id,
            brand_name,
            score,
            tier,
            financial_metrics,
            open_alerts
        )

        # 4. Process proposed optimizations
        processed_cards = []
        for raw_card in proposed_cards:
            card = raw_card.copy()
            # Verify schema
            is_valid, validation_errors = (
                action_card_validator.validate_action_card(card)
            )
            if not is_valid:
                card["status"] = "REJECTED"
                card["description"] = (
                    f"[REJECTED: Schema Errors: {validation_errors}] "
                    f"{card.get('description', '')}"
                )
                processed_cards.append(card)
                continue

            # Evaluate OPA boundary check policy
            is_allowed, OPA_violations = self.evaluate_opa_policy(card)
            if not is_allowed:
                card["status"] = "REJECTED"
                card["description"] = (
                    f"[REJECTED: OPA Violations: {OPA_violations}] "
                    f"{card.get('description', '')}"
                )
                processed_cards.append(card)
                continue

            # Apply Cold Start Fallback tags if needed
            if needs_cogs:
                card["description"] = f"[COLD_START: marginBasis fallback] {card.get('description', '')}"

            # Route based on Autonomy Tier
            if tier == 2:
                # Full Autonomy: Auto-approve high-impact items (>= 7.0)
                if card["impact_score"] >= 7.0:
                    card["status"] = "APPROVED"
                else:
                    card["status"] = "PENDING"
                    # Queue in stateful queue for manual approval
                    self.queue_approval(card["id"], card, {"active_tier": 2})
            elif tier == 1:
                card["status"] = "PENDING"
                self.queue_approval(card["id"], card, {"active_tier": 1})
            else:
                # Lockout: Discard all optimizations
                card["status"] = "REJECTED"

            processed_cards.append(card)

        return RunResults(
            trust_score=score,
            autonomy_tier=tier,
            context_prompt=prompt,
            processed_cards=processed_cards,
            lockout_active=lockout,
            needs_cogs=needs_cogs
        )
