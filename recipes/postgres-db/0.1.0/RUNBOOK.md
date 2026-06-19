# postgres-db Recipe Runbook (v0.1.0)

This recipe provisions a serverless PostgreSQL database slot using a serverless database provider (e.g. Neon).

## Failure Modes & Remediation

### 1. Database Connection Failure
*   **Symptom**: Downstream services fail to connect to the database host `db_host` using the provided `connection_uri`.
*   **Root Cause**: Incorrect credentials, network security policies, or provider service outage.
*   **Remediation**:
    1.  Verify the connection URI string.
    2.  Ensure that the downstream service has egress access permitted (e.g. Serverless VPC Access connector if running on Cloud Run, or open IP ranges on Neon console).
    3.  Check Neon/provider status page for active outages.

### 2. Data Preservation during Compensation (Destroy)
*   **Symptom**: Deleting the database via targeted compensation destroys all tables and data.
*   **Root Cause**: Running `terraform destroy` or calling the `destroy` action deletes the database instance and all associated storage slots.
*   **Remediation**:
    *   **WARNING**: Always perform a manual database dump (`pg_dump`) prior to approving a database `destroy` action if any production data needs to be preserved.
    *   Store backups securely in a separate, non-governed Cloud Storage bucket (`gs://aos-db-backups-<tenant_id>/`).
