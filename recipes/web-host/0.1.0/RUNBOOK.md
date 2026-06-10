# web-host Recipe Runbook (v0.1.0)

This recipe deploys a Cloud Run service and maps a custom domain to it.

## Failure Modes & Remediation

### 1. Cloud Run Deployment Fails
*   **Symptom**: `google_cloud_run_v2_service.web` creation fails.
*   **Root Cause**: Container image not found, regions block, or resource quotas exceeded.
*   **Remediation**:
    1.  Ensure the container image is public or resides in Artifact Registry inside the target project, and the deployment service account has read access.
    2.  Check project quotas for CPU/Memory in the target region.

### 2. Domain Mapping Fails / SSL Pending
*   **Symptom**: `google_cloud_run_domain_mapping.mapping` fails or custom domain shows SSL Certificate pending for hours.
*   **Root Cause**: DNS records are not pointed to the Google domain mapping verification target.
*   **Remediation**:
    1.  Retrieve the DNS target details from Terraform outputs or Google Cloud Run Console.
    2.  Create the DNS CNAME/A records at the domain registrar to verify ownership and complete SSL provisioning.
