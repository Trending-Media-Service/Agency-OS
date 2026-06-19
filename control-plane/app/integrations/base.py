"""Base provider adapter interface.

All Tier 1 integrations inherit from this.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Standard health check response."""
    provider: str
    is_healthy: bool
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    last_checked: Optional[datetime] = None
    
    def __post_init__(self):
        if self.last_checked is None:
            self.last_checked = datetime.utcnow()


@dataclass
class WebhookEvent:
    """Standard webhook event format."""
    provider: str
    event_type: str
    timestamp: datetime
    data: Dict[str, Any]
    raw_body: Optional[str] = None


class ProviderAdapter(ABC):
    """Base class for all platform integrations.
    
    Subclasses implement connect(), health_check(), fetch_metrics(), send_action(), etc.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize adapter with environment/connection config.
        
        Args:
            config: Dict of required config keys (e.g., {"token": "...", "account_id": "..."})
        """
        self.config = config or {}
        self.provider_name = self.__class__.__name__.replace("Adapter", "").lower()
        self._validate_config()
    
    @abstractmethod
    def _validate_config(self):
        """Validate required config keys are present.
        Raise ValueError if missing.
        """
        pass
    
    @abstractmethod
    async def connect(self) -> HealthCheckResult:
        """Test connection to provider API.
        
        Returns:
            HealthCheckResult with connection status.
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """Periodic health check (may be different from initial connect).
        
        Returns:
            HealthCheckResult.
        """
        pass
    
    @abstractmethod
    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        """Fetch metrics for a resource (campaign, page, account, etc).
        
        Args:
            resource_id: Platform resource ID (e.g., campaign ID, page ID).
            metric_keys: List of metric names to fetch.
        
        Returns:
            Dict of metric_name -> value.
        """
        pass
    
    @abstractmethod
    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send an action to the platform (create, update, pause campaign, etc).
        
        Args:
            action: Action name (e.g., "pause_campaign", "create_post").
            payload: Action-specific payload.
        
        Returns:
            Response dict (may include resource ID, status, etc).
        """
        pass
    
    @abstractmethod
    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        """Verify webhook signature and parse event.
        
        Args:
            raw_body: Raw HTTP body.
            signature: Signature header (platform-specific format).
        
        Returns:
            WebhookEvent if valid, None if invalid signature.
        """
        pass
    
    def _log_request(self, method: str, url: str, status: int, error: Optional[str] = None):
        """Helper to log API requests."""
        msg = f"{self.provider_name.upper()} {method} {url} -> {status}"
        if error:
            msg += f" ({error})"
            logger.warning(msg)
        else:
            logger.info(msg)
