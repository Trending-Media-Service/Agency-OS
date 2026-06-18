import logging
import httpx
import base64
from typing import Any
from .base import register_connector

logger = logging.getLogger(__name__)

@register_connector
class JiraConnector:
    provider = "jira"

    def __init__(self, token: str, config: dict[str, Any]):
        self.token = token # Expecting email:api_token format
        self.config = config
        self.domain = config.get("domain", "mock-domain")
        self.api_url = config.get("api_url", f"https://{self.domain}.atlassian.net/rest/api/3")
        
        encoded = base64.b64encode(token.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    async def verify_connection(self) -> bool:
        """Verifies Jira connection by querying current user info."""
        if not self.token or self.token == "mock-jira-secret":
            logger.info("[Mock Jira] Verifying connection successfully")
            return True

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{self.api_url}/myself", headers=self.headers)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Jira connection verification failed: {e}")
                return False

    async def create_issue(self, summary: str, description: str, project_key: str) -> dict:
        """Creates an issue ticket in Jira."""
        if not self.token or self.token == "mock-jira-secret":
            logger.info(f"[Mock Jira] Created issue '{summary}' in project {project_key}")
            return {"id": "10001", "key": f"{project_key}-42", "self": f"{self.api_url}/issue/10001"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": summary,
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": description}]
                            }
                        ]
                    },
                    "issuetype": {"name": "Task"}
                }
            }
            resp = await client.post(f"{self.api_url}/issue", headers=self.headers, json=payload)
            resp.raise_for_status()
            return resp.json()
