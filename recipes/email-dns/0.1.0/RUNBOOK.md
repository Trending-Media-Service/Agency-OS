# email-dns Recipe Runbook (v0.1.0)

This recipe configures custom DNS records (MX, SPF, and DKIM) in Google Cloud DNS to enable third-party email routing (e.g., via Amazon SES) for a brand domain.

## Failure Modes & Remediation

### 1. Managed Zone Not Found
*   **Symptom**: Creation fails with `google_dns_record_set` resource error: `"managed_zone not found"`.
*   **Root Cause**: The parent managed DNS zone for the brand domain (expected to be named `zone-<domain-with-dashes>`) does not exist in the target GCP project.
*   **Remediation**:
    1.  Ensure that the `brand-baseline` recipe has been successfully run first, which is responsible for provisioning the project and baseline DNS zones.
    2.  Check the zone name in the GCP console and ensure it matches the naming convention `zone-${replace(domain, ".", "-")}`.

### 2. DNS Propagation Delay / Verification Failures
*   **Symptom**: The `verify` phase (which queries active DNS servers using `dig`/`nslookup` or urllib) fails to detect the newly added MX, SPF, or DKIM records.
*   **Root Cause**: DNS updates require time to propagate across global DNS servers. This is a natural, non-hermetic latency and not an infrastructure bug.
*   **Remediation**:
    1.  Wait 2 to 5 minutes.
    2.  Query the DNS records directly using an external tool: `dig mx <domain>` or `dig txt _amazonses.<domain>`.
    3.  Once the records are visible globally, re-trigger the verification phase.

### 3. Record Conflict (Pre-existing SPF/MX)
*   **Symptom**: Terraform apply fails with a "Resource already exists" or "Duplicate record" error.
*   **Root Cause**: MX or TXT records already exist in the DNS zone for the target domain, causing a collision.
*   **Remediation**:
    *   If you are migrating email routing, you must manually remove or merge the pre-existing records in the DNS zone before applying the new recipe, as Terraform will refuse to overwrite unmanaged records.
