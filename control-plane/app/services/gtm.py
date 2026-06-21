import logging
import os
import re
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

class GTMClient:
    """Asynchronous client for Google Tag Manager (GTM) API v2.

    Architectural Decision:
    Matches the GoogleAdsClient design by utilizing raw asynchronous `httpx` calls
    to the GTM REST API. This ensures non-blocking I/O execution on the ASGI event loop
    and maintains a zero-dependency footprint.
    """
    
    def __init__(self, oauth_token: Optional[str] = None):
        self.oauth_token = oauth_token
        self.api_url = "https://www.googleapis.com/tagmanager/v2"
        self.headers = {
            "Authorization": f"Bearer {oauth_token or ''}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        self._is_mock = not oauth_token or oauth_token == "mock-gtm-token"

    async def _make_request(
        self, 
        client: httpx.AsyncClient, 
        method: str, 
        path: str, 
        json_data: Optional[dict] = None
    ) -> dict:
        """Helper to send async requests with error handling."""
        url = f"{self.api_url}/{path}"
        try:
            if method == "POST":
                resp = await client.post(url, headers=self.headers, json=json_data)
            elif method == "DELETE":
                resp = await client.delete(url, headers=self.headers)
            else:
                resp = await client.get(url, headers=self.headers)
                
            if resp.status_code == 204: # No Content on successful DELETE
                return {"success": True}
                
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"GTM API HTTP Error on {method} {path}: {e.response.status_code} - {e.response.text}")
            return {"error": e.response.text, "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"GTM API Connection Error on {method} {path}: {e}")
            return {"error": str(e)}

    async def list_containers(self) -> list[dict]:
        """Scans GTM accounts and returns a flat list of all containers."""
        if self._is_mock:
            return [
                {"name": "Mock Web Store", "publicId": "GTM-MOCK123", "type": "WEB"},
                {"name": "Mock Server Gateway", "publicId": "GTM-MOCK456", "type": "SERVER"}
            ]

        async with httpx.AsyncClient() as client:
            accounts_res = await self._make_request(client, "GET", "accounts")
            accounts = accounts_res.get("account", [])
            
            flat_containers = []
            for acc in accounts:
                acc_path = acc.get("path")
                containers_res = await self._make_request(client, "GET", f"{acc_path}/containers")
                containers = containers_res.get("container", [])
                
                for c in containers:
                    flat_containers.append({
                        "account_name": acc.get("name"),
                        "account_id": acc.get("accountId"),
                        "container_name": c.get("name"),
                        "public_id": c.get("publicId"), # e.g., 'GTM-NTCNQN55'
                        "type": c.get("usageContext", ["UNKNOWN"])[0].upper(), # e.g., 'WEB' or 'SERVER'
                        "path": c.get("path")
                    })
            return flat_containers

    async def cleanup_tag_clutter(self, container_public_id: str) -> dict:
        """Finds and deletes redundant 'Offline Conversion' Google Tags in the workspace.

        This resolves the common 'tag clutter' issue programmatically, leaving only the
        essential base tags active.
        """
        if self._is_mock:
            return {"success": True, "deleted_tags": ["Offline Conversion"]}

        async with httpx.AsyncClient() as client:
            # 1. Locate the container path
            containers = await self.list_containers()
            target_container = next((c for c in containers if c["public_id"] == container_public_id), None)
            
            if not target_container:
                return {"error": f"Container {container_public_id} not found under this account."}
                
            container_path = target_container["path"]
            
            # 2. Get active workspaces
            workspaces_res = await self._make_request(client, "GET", f"{container_path}/workspaces")
            workspaces = workspaces_res.get("workspace", [])
            if not workspaces:
                return {"error": "No active workspaces found."}
                
            active_workspace = workspaces[0]
            workspace_path = active_workspace.get("path")
            
            # 3. Query tags in the workspace
            tags_res = await self._make_request(client, "GET", f"{workspace_path}/tags")
            tags = tags_res.get("tag", [])
            
            # 4. Filter for redundant 'Offline Conversion' Google Tags (googtag)
            cluttered_tags = []
            for t in tags:
                # GTM API internal type name for a Google Tag is 'googtag'
                if t.get("name") == "Offline Conversion" and t.get("type") == "googtag":
                    cluttered_tags.append(t)
                    
            if not cluttered_tags:
                return {"success": True, "message": "Workspace is already clean.", "deleted_tags": []}
                
            # 5. Delete them
            deleted = []
            for ct in cluttered_tags:
                ct_path = ct.get("path")
                del_res = await self._make_request(client, "DELETE", ct_path)
                if del_res.get("success"):
                    deleted.append(ct.get("name"))
                    logger.info(f"Programmatically deleted cluttered GTM tag: {ct.get('name')}")
                    
            return {
                "success": len(deleted) == len(cluttered_tags),
                "deleted_tags": deleted,
                "workspace_name": active_workspace.get("name")
            }

    @staticmethod
    async def verify_onpage_gtm_container(target_url: str) -> list[str]:
        """Scrapes a public URL and extracts all GTM Container IDs loading on the page.

        Used by the OS Sentinel to verify that the container being configured in the
        dashboard is actually the one currently installed on the brand's live website.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Add typical browser user agent to avoid bot-blocking
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = await client.get(target_url, headers=headers)
                resp.raise_for_status()
                
                # Regex match for GTM-XXXXXX patterns in HTML
                # This matches standard GTM loading script tags
                html_content = resp.text
                gtm_ids = re.findall(r"\b(GTM-[A-Z0-9]{5,10})\b", html_content)
                
                # Deduplicate and return
                return list(set(gtm_ids))
        except Exception as e:
            logger.error(f"Failed to scrape on-page GTM container for {target_url}: {e}")
            return []


def get_gtm_client(token: Optional[str] = None, config: Optional[dict] = None) -> GTMClient:
    """Factory to resolve a GTM client, mirroring services.marketing.get_marketing_client.

    - In the test environment we always return a mock-backed client.
    - In real environments a GTM OAuth token (tagmanager.* scopes) is required for
      container/tag operations. The on-page verifier is a static method and needs no
      token, so callers may invoke it without a connection.
    """
    env = os.getenv("AOS_ENV", "development")
    if env == "test":
        return GTMClient(oauth_token="mock-gtm-token")
    if not token:
        raise ValueError("Credentials (token) are required for provider: gtm")
    return GTMClient(oauth_token=token)
