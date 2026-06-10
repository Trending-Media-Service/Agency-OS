"""Agency OS — GCP cPanel Provisioner.

Simulates provisioning and de-provisioning Google Cloud Platform (GCP) resources
(Cloud SQL, Cloud Run, and KMS keys) for new multi-tenant sign-ups.
"""

import re
import typing

class GcpProvisioner:
    """Manages virtual GCP tenant environments."""

    def __init__(self, project_id: str = "agency-os-prod"):
        self.project_id = project_id

    def provision_tenant_resources(
        self,
        tenant_id: str,
        region: str = "us-central1"
    ) -> typing.Dict[str, typing.Any]:
        """Simulates creation of Cloud SQL, Cloud Run, and KMS rings for a tenant.

        Args:
            tenant_id: String ID of the tenant.
            region: GCP region to deploy to (default 'us-central1').

        Returns:
            Dictionary manifest of provisioned assets.

        Raises:
            ValueError: If tenant_id contains invalid characters.
        """
        # Validate tenant slug pattern to prevent injection attacks
        if not re.match(r"^[a-zA-Z0-9\-]+$", tenant_id):
            raise ValueError(
                f"Invalid tenant_id '{tenant_id}'. Slugs must be alphanumeric and hyphens only."
            )

        db_instance = f"db-{tenant_id}"
        webhook_service = f"ingestion-webhook-{tenant_id}"
        kms_keyring = f"keyring-{tenant_id}"

        return {
            "status": "PROVISIONED",
            "gcp_project": self.project_id,
            "region": region,
            "cloud_sql": {
                "instance_name": db_instance,
                "connection_name": f"{self.project_id}:{region}:{db_instance}",
                "db_name": "agency_os",
                "status": "RUNNING"
            },
            "cloud_run": {
                "service_name": webhook_service,
                "endpoint": f"https://{webhook_service}-uc.a.run.app",
                "status": "ACTIVE"
            },
            "kms": {
                "keyring_name": kms_keyring,
                "active_key": "vault-crypt-key-v1"
            }
        }

    def deprovision_tenant_resources(self, tenant_id: str) -> bool:
        """Simulates teardown of a tenant's isolated resources."""
        if not re.match(r"^[a-zA-Z0-9\-]+$", tenant_id):
            raise ValueError(f"Invalid tenant_id '{tenant_id}' format for deletion.")
        return True
