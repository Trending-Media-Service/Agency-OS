# SHIP READINESS AUDIT REPORT — Production-Readiness Audit

**Target branch/commit state:**
- **Branch**: `feature/s4-grow-premium-remediation`
- **Commit SHA**: `20646e345bba6fb2756872ce1b78a27b9401173a`

---

## 1. Executive Summary

This report presents a comprehensive end-to-end (E2E) production readiness and security audit of the **Agency-OS** platform. Based on the technical audit executed at target commit `20646e3`, the repository meets many of the operational criteria (deterministic policy gating, robust tenant isolation context, functional outbox and idempotency structures, and a 100% passing test suite of 504 test cases with 74.26% code coverage). 

However, the audit identified **two critical architectural concerns** that block a safe production release:
1. **Critical Security Vulnerability: Webhook Signature Verification Bypass**: Webhook routers fallback to the literal secret reference name if the secret is not successfully retrieved from Secret Manager (e.g. `ValueError` on misconfigured/dev environments), allowing trivial webhook spoofing by calculating HMAC using the public `conn.credential` identifier string.
2. **High Security/Privacy Issue: Architectural Drift in Secret Isolation**: `SecretManagerClient` initialization during Connection creation, deletion, and management (inside `grow.py` and `manage.py` adapters) defaults to the shared control plane GCP project (`aos-control-plane`) instead of the tenant's dedicated GCP project, violating the core requirement of brand-level isolation.

**Release Verdict**: **NO-GO** until remediation of the above Critical and High security findings.

---

## 2. Test Suite Executions & Linting Analysis

### 2.1 Backend Unit and Integration Verification (Pytest)
- **Status**: **PASSING**
- **Metrics**:
  - Total Tests Executed: **504**
  - Total Test Successes: **504**
  - Failures: **0**
  - Code Coverage: **74.26%** (exceeds the 70% conformance threshold requirement)
- **Observations**:
  - The core state transitions, concurrency locks, RLS queries, and policy gate configurations are thoroughly covered by automated assertions.
  - Some test runs logged minor deprecation warnings related to `datetime.utcnow()` usages inside `test_tier4_real_world.py`, which do not affect correctness but should be updated to `datetime.now(datetime.UTC)` in future maintenance iterations.

### 2.2 Frontend Quality & Compliance Verification (ESLint)
- **Status**: **PASSING (with Warnings)**
- **Metrics**:
  - Total Errors: **0**
  - Warnings: **6** (non-blocking unused variables/imports in `poas/page.tsx`, `twin/page.tsx`, and `OperationDetailDrawer.tsx`)
- **Observations**:
  - The Next.js 16 / React 19 CSR structure compiles without any syntax or formatting exceptions.

---

## 3. Conformance Verification of Pre-Existing Findings (1–7)

| Finding ID | Description | Audit Status | Evidence / File References |
| :--- | :--- | :--- | :--- |
| **Finding 1** | Outbox Table RLS Policy | **RESOLVED** | Alembic migration `5cb046e08cb8_make_outbox_tenant_id_not_null.py` backfills null records to `'system'` and marks the column as `NOT NULL` under a strict RLS filter. |
| **Finding 2** | SQLite Temporary DB leaks in DR Drill | **RESOLVED / MITIGATED** | `DRAdapter.verify()` ([dr.py](../../control-plane/app/adapters/dr.py#L143-L161)) is configured with a nested `try...finally` block that guarantees local file unlinking even on verification crashes. *Note: A residual risk remains if the worker process crashes before verification starts, leaving orphan temp files in `/tmp`.* |
| **Finding 3** | PMax Bid-Cap Rule mismatch | **RESOLVED** | Tunable ruleset boundaries ([services.py](../../control-plane/app/kernel/services.py#L305)) lock `grow_bid_cap_minor` to exactly `100_000` (1,000 INR), aligning with system design boundaries. |
| **Finding 4** | Inverted GMC Penalty logic | **RESOLVED** | Penalty scoring uses `saturating_penalty(count, p_max, tau)` which computes `p_max * (1.0 - exp(-count / tau))` ([services.py](../../control-plane/app/kernel/services.py#L100-L105)), correctly bounding GMC mismatch penalties. |
| **Finding 5** | Missing `sync_order` executor | **RESOLVED** | `ManageAdapter.execute()` ([manage.py](../../control-plane/app/adapters/manage.py#L658-L690)) implements the `manage.shopify.sync_order` order synchronization path. |
| **Finding 6** | Git Worker credential isolation gap | **RESOLVED** | `BuildAgentHarness` ([build_agent.py](../../control-plane/app/adapters/build_agent.py#L31-L36)) embeds the brand's `access_token` directly in HTTPS URLs during clone operations, which Git configuration cache retains for subsequent pushes. |
| **Finding 7** | Secrets isolation project mismatch | **UNRESOLVED (DRIFTED)** | Secrets write/delete operations ([grow.py](../../control-plane/app/adapters/grow.py#L635), [manage.py](../../control-plane/app/adapters/manage.py#L191)) initialize `SecretManagerClient()` with no project ID, defaulting them to the global control plane project (`aos-control-plane`). |

---

## 4. Newly Discovered Security Vulnerability Details

### Webhook Signature Verification Bypass (CRITICAL)
- **Vulnerability Type**: Insecure Fallback / Authentication Bypass
- **Location**: [main.py:2163-2173](../../control-plane/app/main.py#L2163-L2173)
- **Mechanics**:
  ```python
  # Resolve actual secret key from Secret Manager (Falling back to credential if not in Secret Manager)
  from app.services.secrets import SecretManagerClient
  try:
      secrets_client = SecretManagerClient(project_id=gcp_project)
      secret_key = await secrets_client.read_secret(conn.credential)
  except ValueError as e:
      logger.warning(f"Secret not found in registry: {e}. Falling back to literal ref.")
      secret_key = conn.credential
  ```
  If `read_secret` raises a `ValueError` (which is standard behavior if the target secret key version does not exist or has been disabled in Secret Manager), the controller falls back to setting `secret_key = conn.credential` (e.g. `'t1-b1-shopify-secret'`). 
  
  An attacker who can guess or query the public connection credential string format (`{tenant_id}-{brand_id}-{provider}-secret`) can generate a valid signature using the credential string as the HMAC key, bypass webhook verification, and execute arbitrary automated Shopify syncing/polling actions on behalf of the target tenant.

---

## 5. Architecture, DB, Observability and Secrets Audit

### 5.1 DB & Migration Safety
- Migrations are fully structured under Alembic. No manual DB edits or drift are present.
- All RLS policies are enabled on core tables.
- Normal connections access DB using `get_db()` with `app.current_tenant_id` session settings. RLS worker tasks bypass these checks safely via the dedicated role `aos_api_rls_worker`.

### 5.2 Secrets Isolation (HIGH)
- Even though `grow.py` adapter reads secrets using tenant-scoped GCP project IDs, the `connect` and `disconnect` routes inside `grow.py` and *all* secret operations inside `manage.py` default to the global control plane project (`aos-control-plane`). 
- This leads to tenant secret leaks into the control plane project storage, violating the architectural boundary requiring strict segregation of tenant keys into their respective GCP landing zones.

### 5.3 Observability & Tracing Coverage
- **TraceMiddleware** is mounted at the root HTTP layer and properly propagates incoming `X-Trace-ID` and `traceparent` headers, or creates new random tracing identifiers (`tr-<uuid>`).
- Every state change triggers structured logs containing tracing identifiers, which guarantees clean trace coverage throughout the execution lifecycle of proposed and approved actions.
