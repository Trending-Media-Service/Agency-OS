# static-host Recipe Runbook (v0.1.0)

This recipe provisions static website hosting using a Google Cloud Storage bucket, Cloud CDN backend bucket, Managed SSL certificate, and an HTTPS Load Balancer.

## Failure Modes & Remediation

### 1. Storage Bucket Name Collision
*   **Symptom**: `google_storage_bucket.static_bucket` creation fails with a "Bucket name already exists" error.
*   **Root Cause**: GCS bucket names are globally unique. Another user or project has already claimed the name specified in `bucket_name`.
*   **Remediation**:
    1.  Tweak the `bucket_name` parameter to include a unique suffix (e.g. appending the tenant ID or a random string).
    2.  Rerun the proposal to verify and apply with the new unique name.

### 2. SSL Managed Certificate Stays Pending
*   **Symptom**: Custom domain does not resolve over HTTPS, and the managed SSL certificate state remains `PROVISIONING` or `FAILED_NOT_VISIBLE` for over 30 minutes.
*   **Root Cause**: The DNS A record for the custom `domain` is not pointed to the load balancer's reserved IP address.
*   **Remediation**:
    1.  Query the terraform outputs to retrieve the load balancer's IP: `lb_ip_address`.
    2.  Update the DNS configuration at the domain's registrar/DNS zone, creating an `A` record pointing the custom domain to the `lb_ip_address`.
    3.  Google's managed certificate system will automatically verify ownership and complete SSL provisioning within 10-15 minutes after DNS propagation.

### 3. Load Balancer / CDN Latency
*   **Symptom**: Accessing `https://<domain>` returns an HTTP `404` or `502` immediately after deployment.
*   **Root Cause**: HTTP/HTTPS Load Balancers and Cloud CDN configurations require several minutes to propagate globally across Google's edge caches.
*   **Remediation**:
    *   Wait 5 to 10 minutes. The edge caches will synchronize automatically, and the static website will begin serving.
