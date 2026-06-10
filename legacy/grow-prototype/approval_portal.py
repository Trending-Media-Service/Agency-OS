"""Agency OS — Action Approval Portal & Mutation Webhooks.

Manages manual verification workflows for Action Cards, verifying user roles
before changing statuses and dispatching simulated mutations to ad network APIs.
"""

import typing

class ActionApprovalPortal:
    """Manages approvals, rejections, and mutation webhook dispatching."""

    def __init__(self):
        pass

    def approve_card(
        self,
        card: typing.Dict[str, typing.Any],
        user_role: str
    ) -> typing.Dict[str, typing.Any]:
        """Approves a pending Action Card, simulating API webhook dispatch.

        Args:
            card: Action Card dictionary to approve.
            user_role: Role of the active session user.

        Returns:
            Simulated webhook transmission receipt dict.

        Raises:
            PermissionError: If the role is unauthorized.
            ValueError: If the card is not in a PENDING state.
        """
        # Role verification (Only Owners and DBAs can commit mutations)
        if user_role not in {"AGENCY_OWNER", "CLIENT_DBA"}:
            raise PermissionError(
                f"Role '{user_role}' is unauthorized to approve database mutations."
            )

        if card.get("status") != "PENDING":
            raise ValueError(
                f"Only PENDING cards can be approved (got '{card.get('status')}')"
            )

        # Transition status
        approved_card = card.copy()
        approved_card["status"] = "APPROVED"

        # Resolve webhook URL based on card payload/type
        rec_type = card.get("recommendation_type")
        if rec_type in {"BID_ADJUSTMENT", "BUDGET_REALLOCATION"}:
            webhook_url = "https://ads.googleapis.com/v1/mutations/dispatch"
        else:
            webhook_url = "https://graph.facebook.com/v19.0/custom_mutations"

        return {
            "status": "DISPATCHED",
            "webhook_url": webhook_url,
            "dispatched_by": user_role,
            "updated_card": approved_card,
            "payload_sent": approved_card["payload"]
        }

    def reject_card(
        self,
        card: typing.Dict[str, typing.Any],
        user_role: str
    ) -> typing.Dict[str, typing.Any]:
        """Rejects a pending Action Card.

        Args:
            card: Action Card dictionary to reject.
            user_role: Role of the active session user.

        Returns:
            Outcome receipt.

        Raises:
            PermissionError: If the role is unauthorized.
            ValueError: If the card is not in a PENDING state.
        """
        if user_role not in {"AGENCY_OWNER", "CLIENT_DBA"}:
            raise PermissionError(
                f"Role '{user_role}' is unauthorized to reject cards."
            )

        if card.get("status") != "PENDING":
            raise ValueError(
                f"Only PENDING cards can be rejected (got '{card.get('status')}')"
            )

        rejected_card = card.copy()
        rejected_card["status"] = "REJECTED"

        return {
            "status": "REJECTED_SUCCESSFULLY",
            "updated_card": rejected_card
        }
