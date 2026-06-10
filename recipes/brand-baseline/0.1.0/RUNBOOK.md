# brand-baseline Recipe Runbook (v0.1.0)

This recipe provisions the core GCP resources for a brand, targeting either dedicated or shared tier.

## Failure Modes & Remediation

### 1. Project Creation Fails (`dedicated` tier)
*   **Symptom**: `terraform apply` fails with error containing `google_project.brand_project: Error creating Project`.
*   **Root Cause**: Billing account not linked, organization permissions missing (Project Creator role), or project ID collision.
*   **Remediation**:
    1.  Ensure the Billing Account is active and the Control Plane SA has `Billing Account User` role.
    2.  Check folder permissions to ensure the SA has `Project Creator` role on the target folder.
    3.  If it's an ID collision, adjust `brand_id` mapping.

### 2. Database Creation Fails (`shared` tier)
*   **Symptom**: `google_sql_database.shared_db: Error creating Database`.
*   **Root Cause**: Shared database instance is down, unreachable, or database name already exists.
*   **Remediation**:
    1.  Check the state of the central Postgres instance `aos-shared-postgres` in GCP Console.
    2.  Check connectivity from the workspace runner executing Terraform.
