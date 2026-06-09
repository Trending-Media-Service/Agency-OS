"""Agency OS — Action Card Generator & Schema Validator.

Defines schemas and validates Action Card payloads before database writes
to ensure structural integrity and execution safety.
"""

import typing

VALID_REC_TYPES = {
    "BID_ADJUSTMENT",
    "BUDGET_REALLOCATION",
    "PAUSE_CAMPAIGN",
    "ALERT_DISPATCH",
}
VALID_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


def validate_action_card(
    card: typing.Dict[str, typing.Any]
) -> typing.Tuple[bool, typing.List[str]]:
    """Validates the structure and payload schema of an Action Card.

    Args:
        card: Dictionary containing Action Card fields.

    Returns:
        A tuple of (is_valid, list_of_errors).
    """
    errors = []

    # 1. Base Field Verification
    required_fields = {
        "id": str,
        "tenant_id": str,
        "recommendation_type": str,
        "impact_score": (int, float),
        "description": str,
        "payload": dict,
        "created_at": str,
        "status": str
    }

    for field, expected_type in required_fields.items():
        if field not in card:
            errors.append(f"Missing required base field: '{field}'")
            continue
        val = card[field]
        if not isinstance(val, expected_type):
            errors.append(
                f"Field '{field}' has invalid type. "
                f"Expected {expected_type}, got {type(val)}"
            )

    if errors:
        return False, errors

    # 2. Value Range and Enum Validations
    rec_type = card["recommendation_type"]
    if rec_type not in VALID_REC_TYPES:
        errors.append(
            f"Invalid recommendation_type: '{rec_type}'. "
            f"Must be one of {VALID_REC_TYPES}"
        )

    status = card["status"]
    if status not in VALID_STATUSES:
        errors.append(
            f"Invalid status: '{status}'. Must be one of {VALID_STATUSES}"
        )

    impact = card["impact_score"]
    if not (0.0 <= impact <= 10.0):
        errors.append(
            f"impact_score must be between 0.0 and 10.0 (got {impact})"
        )

    # 3. Payload Schema Validation based on Recommendation Type
    payload = card["payload"]
    if rec_type == "BID_ADJUSTMENT":
        _validate_payload_fields(
            payload,
            {
                "campaign_id": str,
                "ad_group_id": str,
                "old_bid": (int, float),
                "new_bid": (int, float),
            },
            "BID_ADJUSTMENT",
            errors
        )
    elif rec_type == "BUDGET_REALLOCATION":
        _validate_payload_fields(
            payload,
            {
                "source_campaign_id": str,
                "target_campaign_id": str,
                "amount": (int, float),
            },
            "BUDGET_REALLOCATION",
            errors
        )
    elif rec_type == "PAUSE_CAMPAIGN":
        _validate_payload_fields(
            payload,
            {"campaign_id": str, "reason": str},
            "PAUSE_CAMPAIGN",
            errors
        )
    elif rec_type == "ALERT_DISPATCH":
        _validate_payload_fields(
            payload,
            {"alert_type": str, "severity": str},
            "ALERT_DISPATCH",
            errors
        )

    return len(errors) == 0, errors


def _validate_payload_fields(
    payload: typing.Dict[str, typing.Any],
    expected_fields: typing.Dict[str, typing.Any],
    rec_type_name: str,
    errors: typing.List[str]
) -> None:
    """Helper to validate keys and types in recommendation payloads."""
    for field, expected_type in expected_fields.items():
        if field not in payload:
            errors.append(f"[{rec_type_name}] Missing payload field: '{field}'")
            continue
        val = payload[field]
        if not isinstance(val, expected_type):
            errors.append(
                f"[{rec_type_name}] Payload field '{field}' has invalid type. "
                f"Expected {expected_type}, got {type(val)}"
            )
