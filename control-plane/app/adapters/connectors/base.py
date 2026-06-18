from __future__ import annotations
import logging
from typing import Any, Optional, Protocol, Type
from app.services.secrets import SecretManagerClient

logger = logging.getLogger(__name__)

class Connector(Protocol):
    provider: str

    def __init__(self, token: str, config: dict[str, Any]):
        """Initialize the connector with the resolved credential token and configuration."""
        ...

    async def verify_connection(self) -> bool:
        """Verifies the API connection is active and responsive."""
        ...


# Global registry mapping provider name to Connector class
_REGISTRY: dict[str, Type[Connector]] = {}

def register_connector(connector_cls: Type[Connector]) -> Type[Connector]:
    """Decorator to register a connector class in the global registry."""
    provider = connector_cls.provider
    _REGISTRY[provider] = connector_cls
    logger.info(f"Registered universal connector for provider: {provider}")
    return connector_cls


async def get_connector(provider: str, secret_ref: str, config: dict[str, Any], tenant_project_id: Optional[str] = None) -> Optional[Connector]:
    """Connector factory that resolves credentials from Secret Manager and returns the configured Connector instance."""
    connector_cls = _REGISTRY.get(provider)
    if not connector_cls:
        logger.warning(f"No universal connector registered for provider: {provider}")
        return None

    # Resolve actual API credential token from Secret Manager
    token = secret_ref
    try:
        secrets_client = SecretManagerClient(project_id=tenant_project_id)
        token = await secrets_client.read_secret(secret_ref)
    except Exception as e:
        logger.warning(f"Failed to resolve connector secret from Secret Manager: {e}. Falling back to raw secret_ref.")

    try:
        instance = connector_cls(token=token, config=config)
        return instance
    except Exception as e:
        logger.error(f"Failed to instantiate connector {provider}: {e}")
        return None
