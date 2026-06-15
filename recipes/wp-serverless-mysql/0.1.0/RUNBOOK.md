# wp-serverless-mysql Recipe Runbook (v0.1.0)

This recipe provisions serverless WordPress on Cloud Run, connected to dedicated Cloud SQL MySQL and a GCS bucket.

## Failure Modes & Remediation

### 1. Database Connection Fails
*   **Symptom**: Cloud Run service shows 500 or "Error establishing a database connection".
*   **Root Cause**: MySQL instance not fully started when Cloud Run service initialized, or incorrect IAM database credentials / service account bindings.
*   **Remediation**:
    1. Verify that the Cloud SQL instance is in `RUNNING` status in GCP Console.
    2. Check the Cloud Run service logs for database connection timeouts.
    3. Re-run verification step to confirm database connectivity.

### 2. GCS Bucket Access Denied
*   **Symptom**: WordPress media uploads fail.
*   **Root Cause**: GCS bucket permissions (IAM roles) not set correctly for the Cloud Run service account.
*   **Remediation**:
    1. Ensure the Cloud Run service account has the `Storage Object Admin` role on the uploads bucket.
