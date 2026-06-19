# webapp-postgres Recipe Runbook (v0.1.0)

This recipe provisions a complete three-tier web application architecture:
1.  **Cloud SQL PostgreSQL Instance**: Managed relational database.
2.  **Secret Manager Secrets**: Secure storage for database credentials.
3.  **FastAPI API Backend (Cloud Run)**: Containerized backend service.
4.  **Next.js Web Frontend (Cloud Run)**: Containerized customer-facing frontend.

## Failure Modes & Remediation

### 1. Cloud SQL Provisioning Timeout / Out of Quotas
*   **Symptom**: `google_sql_database_instance.postgres` creation hangs for 15+ minutes or fails immediately.
*   **Root Cause**: Cloud SQL instances take several minutes to provision. It can also fail due to insufficient project quotas or IP range exhaustion.
*   **Remediation**:
    1.  Check the GCP console to see if the instance is actively building.
    2.  Verify that the `db_tier` matches a valid machine type (default: `db-f1-micro` for development).
    3.  Ensure that Service Networking connection is configured in the project to allow private IP allocation.

### 2. Egress / Database Reachability Failure
*   **Symptom**: The API container logs show `OperationalError: could not connect to server: Connection refused`.
*   **Root Cause**: The API service cannot reach the Cloud SQL instance over the private VPC connection, or the Cloud SQL Auth Proxy is misconfigured.
*   **Remediation**:
    1.  Ensure that a VPC Connector is provisioned in the same region and attached to the API Cloud Run service.
    2.  Verify that the `db_connection_name` (e.g. `project:region:instance`) is correctly passed to the container env.

### 3. Secret Access Denied
*   **Symptom**: Cloud Run service fails to start, displaying permission errors when mounting secrets.
*   **Root Cause**: The Cloud Run runtime service account does not have the `roles/secretmanager.secretAccessor` role on the generated secrets.
*   **Remediation**:
    *   Verify that the IAM bindings in `main.tf` successfully attach the deployer service account and the Cloud Run service identity to the secret accessor role.
