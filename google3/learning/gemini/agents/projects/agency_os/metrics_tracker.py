"""Agency OS — Metrics Tracker Singleton & Threshold Alert Engine.

Manages system performance statistics and exposes health endpoints to trigger
reconciliation alerts when latency or error ratios exceed bounds.
"""

import typing


class MetricsTracker:
    """Singleton-style class tracking real-time server and queue statistics."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(
                MetricsTracker, cls
            ).__new__(cls, *args, **kwargs)
            cls._instance._init_tracker()
        return cls._instance

    def _init_tracker(self) -> None:
        self.total_requests = 0
        self.failed_requests = 0
        self.total_latency_ms = 0.0
        self.backlog_depth = 0

    def reset(self) -> None:
        """Resets tracker state (useful for unit testing isolation)."""
        self._init_tracker()

    def record_request(self, latency_ms: float, is_success: bool) -> None:
        """Accumulates API metrics."""
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        if not is_success:
            self.failed_requests += 1

    def update_backlog(self, depth: int) -> None:
        """Sets current queue event depth size."""
        self.backlog_depth = depth

    def get_metrics_payload(self) -> typing.Dict[str, typing.Any]:
        """Exposes GET /metrics aggregate stats payload."""
        avg_latency = 0.0
        if self.total_requests > 0:
            avg_latency = self.total_latency_ms / self.total_requests

        fail_rate = 0.0
        if self.total_requests > 0:
            fail_rate = self.failed_requests / self.total_requests

        return {
            "total_requests": self.total_requests,
            "average_latency_ms": avg_latency,
            "failure_rate": fail_rate,
            "backlog_depth": self.backlog_depth
        }

    def evaluate_rules(self) -> typing.Tuple[bool, typing.List[str]]:
        """Constantly evaluates metrics alerts thresholds.

        Returns:
            Tuple: (is_healthy: bool, alerts: List[str])
        """
        alerts = []
        stats = self.get_metrics_payload()

        # Rule 1: Latency Threshold (> 1000ms)
        if stats["average_latency_ms"] > 1000.0:
            alerts.append(
                f"LATENCY_SPIKE: Average latency "
                f"{stats['average_latency_ms']:.1f}ms exceeds 1000ms threshold."
            )

        # Rule 2: Failure Rate (> 5%)
        if stats["failure_rate"] > 0.05:
            alerts.append(
                f"HIGH_ERRORS: Failure rate "
                f"{stats['failure_rate'] * 100:.1f}% exceeds 5% threshold."
            )

        # Rule 3: Backlog event depth (> 100)
        if stats["backlog_depth"] > 100:
            alerts.append(
                f"QUEUE_BACKLOG: Queue depth "
                f"{stats['backlog_depth']} exceeds 100 tasks ceiling."
            )

        return (len(alerts) == 0, alerts)
