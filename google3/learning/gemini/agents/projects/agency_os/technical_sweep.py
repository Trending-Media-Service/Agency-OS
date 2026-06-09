"""Agency OS — Technical Sweep Simulator.

Validates the presence of advertising pixels and measures Conversions API
(CAPI) deduplication metrics between client (browser) and server.
"""

import re
import typing

@typing.final
class AuditReport(typing.NamedTuple):
    url: str
    gtm_present: bool
    pixel_present: bool
    capi_dedup_score: float  # Percentage of CAPI events matched with browser
    warnings: typing.List[str]
    healthy: bool


class TechnicalSweepSimulator:
    """Simulates auditing target landing pages and API event deduplication."""

    def __init__(self):
        pass

    def audit_page_source(self, url: str, html_content: str) -> AuditReport:
        """Audits raw HTML content of a landing page for required tags.

        Args:
            url: The page URL.
            html_content: The raw HTML source code.

        Returns:
            An AuditReport instance containing results and warnings.
        """
        warnings = []
        gtm_present = bool(re.search(r"googletagmanager\.com/gtm\.js", html_content))
        if not gtm_present:
            warnings.append("Google Tag Manager (GTM) script is missing.")

        pixel_present = bool(
            re.search(
                r"connect\.facebook\.net/[a-zA-Z_]+/fbevents\.js",
                html_content
            )
        )
        if not pixel_present:
            warnings.append("Meta Pixel script is missing.")

        return AuditReport(
            url=url,
            gtm_present=gtm_present,
            pixel_present=pixel_present,
            capi_dedup_score=0.0,
            warnings=warnings,
            healthy=gtm_present and pixel_present
        )

    def verify_capi_deduplication(
        self,
        browser_events: typing.List[typing.Dict[str, typing.Any]],
        server_events: typing.List[typing.Dict[str, typing.Any]]
    ) -> float:
        """Verifies deduplication matching rates between browser and server events.

        Checks if server-side events have a corresponding client-side browser
        event with the exact same `event_id` to prevent double-counting.

        Args:
            browser_events: List of event dictionaries captured in the browser.
            server_events: List of event dictionaries sent via Conversions API.

        Returns:
            Matched percentage from 0.0 to 1.0.
        """
        browser_ids = {
            e.get("event_id") for e in browser_events if e.get("event_id")
        }
        if not browser_ids:
            return 0.0

        matched_count = 0
        server_event_count = 0
        for se in server_events:
            s_id = se.get("event_id")
            if s_id:
                server_event_count += 1
                if s_id in browser_ids:
                    matched_count += 1

        if server_event_count == 0:
            return 1.0

        return matched_count / server_event_count
