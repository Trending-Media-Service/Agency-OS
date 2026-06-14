# Deploy Agency-OS + onboard a brand (real GCP)

Operational runbook for standing up the control plane on GCP and onboarding a real
brand end-to-end (`host <domain>` → live site) via the **Provision** pillar — the
one slice that performs real Terraform, not mocks. See `/ARCHITECTURE.md` §3 (tenant
isolation), §6.1 (Provision), §8 (stack). This is ops docs, not a roadmap.

## Phase A — one-time GCP prerequisites
1. **Org + billing**; control-plane project `aos-control-plane`; a `tenants` folder (§3).
2. **State bucket** (versioned): `gsutil mb -l asia-south1 gs://aos-tfstate-<suffix>` → `AOS_STATE_BUCKET`.
3. **Cloud SQL Postgres** (system of record) + a **non-superuser** app role (RLS is FORCEd).
4. **Control-plane service account** able to create resources under `tenants/` (project creation
   + Cloud Run + Cloud DNS) and read per-brand Secret Manager. v1 options: grant project-creation
   on the folder, or pre-create the brand projects and use the shared tier.
5. **Domains** for each brand (delegate DNS or register).
6. **Meta WhatsApp Cloud API** creds; submit the `agency_os_approval` template for review **early**
   (Meta approval has lead time).

## Phase B — deploy the control plane
1. Merge the production-ready Provision PR to `main`.
2. **Container image must include the `terraform` CLI** — the `ProvisionAdapter` shells out to it.
   Deploy `app.main:app` to **Cloud Run**.
3. **Env vars:**
   - `ENV=production`
   - `DATABASE_URL=postgresql+asyncpg://<app-role>@…/agency_os` (and `WORKER_DATABASE_URL` for the
     privileged outbox/snapshot role that bypasses RLS)
   - `AOS_STATE_BUCKET=gs://aos-tfstate-<suffix>`
   - `GCP_PROJECT`, `GCP_LOCATION`, `OUTBOX_QUEUE_NAME`, `APP_URL` (Cloud Tasks outbox drain)
   - `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APPROVER_PHONE`,
     `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` (boot fails closed in prod without the secret)
   - `SENTRY_DSN` (optional)
4. **DB + RLS:** run `python migrate.py` against Cloud SQL (creates tables + RLS policies).
5. **Cloud Tasks** queue for the outbox; **Cloud Scheduler** → `POST /tasks/trust-snapshots` nightly.
   The web approval dashboard and `/webhooks/whatsapp` run on the same service.

## Phase C — onboard a brand (governed flow)
Per brand (e.g. Ableys → `ableys.in`, Tanmatra → `tanmatra.food`):
1. **Create tenant + brand**
   ```
   POST /tenants {"name":"Ableys","brand_name":"Ableys"}   → {tenant_id, brand_id}
   ```
2. **Submit intent** (header `X-Tenant-Id: <tenant_id>`)
   ```
   POST /intents {"brand_id":"<brand_id>","text":"onboard brand ableys ableys.in","domain":"provision"}
   ```
   The adapter plans the **bootstrap saga**: `brand-baseline` (project / shared-tier slot) +
   `web-host` (Cloud Run + Cloud DNS + managed SSL) as child Ops. The card carries the real
   `terraform plan` preview and the ₹/month cost estimate.
3. **Approve** — tap approve on WhatsApp, or:
   ```
   POST /ops/{op_id}/decision {"decision":"approve","actor":"chandan","role":"AGENCY_OWNER","surface":"whatsapp"}
   ```
   At Tier 1 every Op is human-approved.
4. **Execute** — the outbox worker runs `terraform apply`; `verify()` runs the recipe `checks.py`
   (DNS resolves, cert issued, HTTP 200).
5. **Confirm** — `GET /ops/{op_id}` (full trace), cost ledger has the spend, `GET /audit/verify`
   returns `ok: true`. Site is live at the domain.

## Guardrails (enforced by the kernel)
- Per-brand GCP project + per-brand Secret Manager (§3) — no standing org-wide creds.
- Every Op previewed (`terraform plan`) and human-approved at Tier 1 before any `apply`.
- Statutory firewall: tax/GST-adjacent Ops never auto-execute (§2.2).
- Failure → compensation (`terraform destroy`); poison Ops park in `PARTIAL` for the operator.
- Audit chain is append-only and hash-linked; `GET /audit/verify` proves integrity.

## Rollback / DR
- Per-Op rollback = the declared compensation (`web_host.destroy`).
- Control-plane DR = nightly `pg_dump` → multi-region GCS + Terraform state versioning (§8);
  run a restore drill monthly.
