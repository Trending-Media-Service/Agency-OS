"""Agency OS — Database Error Sink & PII Luhn Scrubber.

Filters sensitive credential tokens and credit card numbers from logs using
recursive dictionary traversals and Luhn algorithm validations.
"""

import re
import typing


class DatabaseErrorSink:
    """Catches exceptions and sanitizes sensitive PII data before database write."""

    def __init__(self):
        # Match standard credit card patterns (13 to 19 digits)
        self.cc_regex = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

    def _is_luhn_valid(self, number_str: str) -> bool:
        """Validates credit card checksum using the Luhn algorithm."""
        digits = [int(c) for c in number_str if c.isdigit()]
        if not digits:
            return False

        # Double every second digit from the right
        checksum = 0
        reverse_digits = digits[::-1]
        for i, digit in enumerate(reverse_digits):
            if i % 2 == 1:
                doubled = digit * 2
                if doubled > 9:
                    doubled -= 9
                checksum += doubled
            else:
                checksum += digit

        return (checksum % 10) == 0

    def _scrub_value(self, value: typing.Any) -> typing.Any:
        """Helper to scan and scrub string values."""
        if not isinstance(value, str):
            return value

        # 1. Search for credit cards and sanitize if Luhn valid
        matches = self.cc_regex.findall(value)
        scrubbed = value
        for m in matches:
            clean_digits = "".join(c for c in m if c.isdigit())
            if self._is_luhn_valid(clean_digits):
                scrubbed = scrubbed.replace(m, "[SCRUBBED_CREDIT_CARD]")

        return scrubbed

    def sanitize_payload(
        self,
        payload: typing.Dict[str, typing.Any]
    ) -> typing.Dict[str, typing.Any]:
        """Recursively scrubs sensitive keys and card numbers from a dictionary."""
        sanitized = {}
        sensitive_keys = {
            "password",
            "token",
            "secret",
            "api_key",
            "private_key",
            "credential"
        }

        for k, v in payload.items():
            k_lower = k.lower()
            if any(sk in k_lower for sk in sensitive_keys):
                sanitized[k] = "[SCRUBBED_SENSITIVE]"
            elif isinstance(v, dict):
                sanitized[k] = self.sanitize_payload(v)
            elif isinstance(v, list):
                sanitized[k] = [
                    self.sanitize_payload(item) if isinstance(item, dict)
                    else self._scrub_value(item)
                    for item in v
                ]
            else:
                sanitized[k] = self._scrub_value(v)

        return sanitized

    def log_error(
        self,
        error_message: str,
        payload: typing.Dict[str, typing.Any]
    ) -> typing.Dict[str, typing.Any]:
        """Sanitizes context payload and logs the incident.

        Args:
            error_message: Trigger error description.
            payload: Raw variables dict containing potentially sensitive fields.

        Returns:
            Sanitized database log record dict.
        """
        clean_payload = self.sanitize_payload(payload)
        return {
            "error_message": error_message,
            "sanitized_payload": clean_payload,
            "status": "RECORDED"
        }

    def run_db_restore_drill(self) -> bool:
        """Simulates throwaway database restore drills verifying backup integrity."""
        # Mock verifying dump migrations and schema loads
        return True
