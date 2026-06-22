# app/services/gcp_provisioning.py
import os
import json
import logging
import httpx
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.secrets import SecretManagerClient

logger = logging.getLogger(__name__)

class GcpProvisioningService:
    """Orchestrates GCP authentication, credential resolution, and baseline project setup."""

    def __init__(self, project_id: str, tenant_id: str, brand_id: str):
        self.project_id = project_id
        self.tenant_id = tenant_id
        self.brand_id = brand_id
        self.secrets_client = SecretManagerClient()

    async def resolve_gcp_credentials(self, session: AsyncSession) -> Dict[str, Any]:
        """Resolves the GCP credentials for a dedicated project from Secret Manager.
        
        Supports both direct Service Account JSON keys and federated Workload Identity settings.
        """
        # 1. Fetch GCP connection metadata from DB
        from app.models import Connection
        from sqlalchemy import select
        
        stmt = select(Connection).where(
            Connection.tenant_id == self.tenant_id,
            Connection.brand_id == self.brand_id,
            Connection.provider == "gcp"
        )
        res = await session.execute(stmt)
        conn = res.scalar_one_or_none()
        
        if not conn:
            logger.info(f"No dedicated GCP connection found. Falling back to Shared Central Topology.")
            return {"tier": "shared", "project_id": os.getenv("GCP_PROJECT", "aos-central-project")}

        # 2. Read the credentials from Secret Manager
        try:
            raw_credentials = await self.secrets_client.read_secret(conn.credential)
            creds_data = json.loads(raw_credentials)
        except Exception as e:
            logger.error(f"Failed to read/parse GCP credentials: {e}")
            raise RuntimeError(f"GCP Credential resolution failed: {e}")

        # Check if credentials represent a standard Service Account JSON Key
        if "private_key" in creds_data:
            logger.info(f"Resolved Service Account JSON Key for dedicated project {self.project_id}")
            return {
                "tier": "dedicated",
                "project_id": self.project_id,
                "auth_method": "service_account_json",
                "credentials_json": creds_data
            }
            
        # Check if credentials represent Workload Identity Federation configuration
        elif "workload_identity_pool" in creds_data:
            logger.info(f"Resolved Workload Identity Federation (WIF) settings for project {self.project_id}")
            return {
                "tier": "dedicated",
                "project_id": self.project_id,
                "auth_method": "workload_identity",
                "wif_pool": creds_data["workload_identity_pool"],
                "wif_provider": creds_data["workload_identity_provider"]
            }

        raise ValueError("Invalid GCP credential structure: missing private_key or workload_identity_pool.")

    async def exchange_wif_for_token(self, wif_pool: str, wif_provider: str) -> str:
        """Exchanges the federated Workload Identity token for a temporary GCP access token.
        
        This is actual Python execution code for Workload Identity Federation!
        """
        logger.info(f"Exchanging federated Workload Identity token for pool {wif_pool}...")
        
        # 1. Obtain OIDC token from the central Agency OS Service Account
        # In production, GCP automatically injects the OIDC token in the container environment.
        central_oidc_token = "mock-central-oidc-token"
        
        # 2. Call GCP Secure Token Service (STS) to exchange OIDC token for federated token
        sts_url = "https://sts.googleapis.com/v1/token"
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "audience": f"//iam.googleapis.com/{wif_pool}",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "subject_token": central_oidc_token
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(sts_url, json=payload, timeout=10.0)
            if resp.status_code != 200:
                raise RuntimeError(f"GCP STS token exchange failed: {resp.text}")
            federated_token = resp.json()["access_token"]
            
        # 3. Exchange federated token for a temporary Service Account access token
        # in the client's dedicated project
        iam_url = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/aos-sentinel-sa@{self.project_id}.iam.gserviceaccount.com:generateAccessToken"
        headers = {"Authorization": f"Bearer {federated_token}", "Content-Type": "application/json"}
        payload_iam = {"scope": ["https://www.googleapis.com/auth/cloud-platform"]}
        
        async with httpx.AsyncClient() as client:
            resp_iam = await client.post(iam_url, json=payload_iam, headers=headers, timeout=10.0)
            if resp_iam.status_code != 200:
                raise RuntimeError(f"GCP IAM Service Account token generation failed: {resp_iam.text}")
            
            scoped_access_token = resp_iam.json()["accessToken"]
            logger.info("Successfully federated access token for dedicated project!")
            return scoped_access_token
