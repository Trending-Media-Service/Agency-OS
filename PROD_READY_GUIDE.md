# Agency-OS — Production Readiness Guide

Actionable, grounded steps to take Agency-OS from current state to production-ready.
Each step lists exact files, line numbers, what to change, tests required, and guardrails.

**Current state (post-PR #126 merge, 2026-06-18):** Kernel (ops, saga, trust, policy, outbox) is
REAL and tested. Adapters are a mix of REAL (provision, build, manage.connect) and MOCK (grow
campaigns, presence audits, MCP client). Security has dev-mode defaults that are unsafe in prod.
Infrastructure is CI-only (no CD, Dockerfile runs as root, no global error handler).

**Rule:** Every step produces a **single commit** on a feature branch, opened as a **draft PR**.
CI must be green before the next step begins. No step may break an existing test.

---

## Phase 0 — Security Hardening (MUST before any prod traffic)

### P0-1: Enforce critical env vars at boot

**File:** `control-plane/app/main.py:113`

**Current:**
```python
OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "default-dev-token")
```

**Change to:**
```python
OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "default-dev-token")
if os.getenv("ENV") == "production" and OPERATOR_TOKEN == "default-dev-token":
    raise RuntimeError("PRODUCTION BOOT ERROR: OPERATOR_TOKEN must be explicitly set — default is forbidden")
```

Also add near line 12 (where `DATABASE_URL` is set in `app/database.py:11`):
```python
if os.getenv("ENV") == "production" and "localhost" in DATABASE_URL:
    raise RuntimeError("PRODUCTION BOOT ERROR: DATABASE_URL still points at localhost")
```

**Test:** Add `tests/test_prod_boot_guards.py`:
- Monkeypatch `ENV=production` + `OPERATOR_TOKEN=default-dev-token` → assert `RuntimeError` on import.
- Monkeypatch `ENV=production` + `OPERATOR_TOKEN=real-secret` → no error.
- Monkeypatch `ENV=` (empty/dev) + `OPERATOR_TOKEN` missing → boots fine (dev mode).

**Guardrail:** Do NOT remove the `"default-dev-token"` fallback for dev/test — only fail in `ENV=production`.

---

### P0-2: Use constant-time comparison for operator token

**File:** `control-plane/app/main.py:120`

**Current:**
```python
if token != OPERATOR_TOKEN:
```

**Change to:**
```python
import hmac
...
if not hmac.compare_digest(token, OPERATOR_TOKEN):
```

WhatsApp webhook already uses `hmac.compare_digest` (line ~1185). Operator auth should too.

**Test:** Existing `test_rbac.py` tests for 401/403 on bad tokens — verify they still pass.

**Guardrail:** Do NOT change the header format (`Bearer <token>`), only the comparison.

---

### P0-3: Add input validation (length limits) to Pydantic models

**File:** `control-plane/app/main.py:149-163` (and other BaseModel classes)

**Change `TenantIn`:**
```python
from pydantic import BaseModel, Field

class TenantIn(BaseModel):
    name: str = Field(max_length=200)
    brand_name: str = Field(max_length=200)
```

**Change `ChatIn` (~line 246):**
```python
class ChatIn(BaseModel):
    brand_id: str = Field(max_length=100)
    text: str = Field(max_length=5000)
```

**Change `IntentIn` (~line 416):**
```python
class IntentIn(BaseModel):
    brand_id: str = Field(max_length=100)
    text: str = Field(max_length=5000)
    domain: str = Field(max_length=50)
```

**Test:** Add to `tests/test_kernel.py` or a new `tests/test_input_validation.py`:
- POST `/tenants` with a 10,000-char name → 422.
- POST `/chat` with a 50,000-char text → 422.
- Normal-length inputs → pass.

**Guardrail:** Do NOT add `regex` validators to IDs — some tenant_id/brand_id values are UUID-format
but the system doesn't enforce UUID everywhere. Length limits only.

---

### P0-4: Add global exception handler

**File:** `control-plane/app/main.py` — add after the middleware setup (~line 111):

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from app.observability import trace_context
    trace_id = trace_context.get("unknown")
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "trace_id": trace_id},
    )
```

**Test:** Add `tests/test_global_error_handler.py`:
- Create a test route that raises `RuntimeError("boom")`.
- Assert response is 500 with `trace_id` in body.
- Assert the error is logged (capture log output).

**Guardrail:** Do NOT catch `HTTPException` in the global handler — FastAPI handles those already.
The handler must only catch `Exception` (non-HTTP).

---

### P0-5: Extend rate limiting to operator endpoints

**File:** `control-plane/app/middleware.py:88`

**Current:**
```python
if request.method == "POST" and request.url.path in ["/chat", "/webhooks/whatsapp"]:
```

**Change to:**
```python
rate_limited_paths = ["/chat", "/webhooks/whatsapp", "/tenants", "/intents", "/policy-simulate"]
if request.method == "POST" and request.url.path in rate_limited_paths:
```

**Test:** Existing `tests/test_rate_limit.py` — extend with a test for `POST /tenants` rate limiting.

**Guardrail:** Do NOT rate-limit GET endpoints, health checks, or background worker endpoints
(`/tasks/*`). Those are internal.

---

### P0-6: Restrict CORS allow_methods

**File:** `control-plane/app/main.py:107`

**Current:**
```python
allow_methods=["*"],
```

**Change to:**
```python
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
```

**Test:** Existing `tests/test_cors.py` — verify it still passes (it tests allowed origins, not methods).
Add a test that `TRACE` method returns 405.

**Guardrail:** Do NOT remove `OPTIONS` — CORS preflight requires it.

---

### P0-7: Plugin webhook — retrieve secret from Secret Manager, not secret_ref directly

**File:** `control-plane/app/main.py` — in `plugin_webhook` handler (~line 1350-1360)

Find the line where `conn.secret_ref` is used as the HMAC key. Change to:

```python
from app.services.secrets import SecretManagerClient

# Retrieve the actual secret for HMAC verification
if os.getenv("AOS_ENV") == "test" or os.getenv("ENV") != "production":
    secret_key = conn.secret_ref  # dev/test: secret_ref IS the key
else:
    sm = SecretManagerClient()
    secret_key = await sm.read_secret(conn.secret_ref)
```

**Test:** Existing `tests/test_webhooks.py` should still pass (test env uses secret_ref directly).
Add a test that mocks `SecretManagerClient.read_secret` → returns a key → HMAC succeeds.

**Guardrail:** Do NOT change the test-mode behavior — `secret_ref` as direct key is correct for testing.

---

## Phase 1 — Infrastructure Hardening

### P1-1: Dockerfile — non-root user + HEALTHCHECK

**File:** `control-plane/Dockerfile`

**Change to:**
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

ENV TERRAFORM_VERSION=1.5.7
RUN curl -LO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && mv terraform /usr/local/bin/ \
    && rm "terraform_${TERRAFORM_VERSION}_linux_amd64.zip"

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/app/
COPY migrate.py /app/
COPY recipes/ /recipes/

RUN chown -R appuser:appuser /app /recipes

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Test:** `docker build -t agency-os-test . && docker run --rm agency-os-test whoami` → prints `appuser`, not `root`.

**Guardrail:** Do NOT use `curl` in HEALTHCHECK (may not be available after switching to non-root).
Use Python's `urllib` which is always present. Do NOT remove Terraform — provision adapter needs it.

---

### P1-2: Alembic migration — outbox.tenant_id NOT NULL

**File:** Create new migration: `control-plane/migrations/versions/<hash>_outbox_tenant_id_not_null.py`

```python
"""Make outbox tenant_id NOT NULL"""
revision = '<generate>'
down_revision = '0c06f3a7b210'

from alembic import op
import sqlalchemy as sa

def upgrade():
    # Backfill any NULL tenant_ids with a sentinel (should not exist in prod)
    op.execute("UPDATE outbox_items SET tenant_id = 'UNKNOWN' WHERE tenant_id IS NULL")
    op.alter_column('outbox_items', 'tenant_id', nullable=False)

def downgrade():
    op.alter_column('outbox_items', 'tenant_id', nullable=True)
```

**Test:** `tests/test_migrations.py` already tests upgrade/downgrade roundtrip — verify it still passes.

**Guardrail:** Do NOT run this migration without first checking that no NULL `tenant_id` rows exist in prod.
Add the `UPDATE` backfill as a safety net but log a warning if any rows are affected.

---

### P1-3: Add CD workflow for Cloud Run

**File:** Create `.github/workflows/deploy.yml`

```yaml
name: deploy
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}

      - uses: google-github-actions/setup-gcloud@v2

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker ${{ vars.GCP_REGION }}-docker.pkg.dev

      - name: Build and push
        run: |
          IMAGE="${{ vars.GCP_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT }}/agency-os/control-plane:${{ github.sha }}"
          docker build -t "$IMAGE" control-plane/
          docker push "$IMAGE"

      - name: Run migrations
        run: |
          gcloud run jobs execute migrate-job \
            --region ${{ vars.GCP_REGION }} \
            --wait \
            --args="python,migrate.py"

      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy agency-os-api \
            --image "$IMAGE" \
            --region ${{ vars.GCP_REGION }} \
            --platform managed \
            --min-instances 1 \
            --max-instances 10 \
            --port 8080 \
            --set-env-vars "ENV=production" \
            --no-allow-unauthenticated

      - name: Verify deployment health
        run: |
          URL=$(gcloud run services describe agency-os-api --region ${{ vars.GCP_REGION }} --format='value(status.url)')
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/healthz")
          if [ "$STATUS" != "200" ]; then
            echo "::error::Deployment health check failed (HTTP $STATUS)"
            exit 1
          fi
```

**Test:** Workflow syntax only — no runtime test. Validate with `actionlint .github/workflows/deploy.yml` if available.

**Guardrail:**
- Do NOT add secrets directly in the workflow file — use GitHub repo secrets/variables.
- Do NOT use `--allow-unauthenticated` — prod API should be behind IAP or auth.
- Do NOT auto-deploy on PR merges to main until the team explicitly enables it. Use `workflow_dispatch` for initial manual deploys.
- The `vars.*` and `secrets.*` references must be configured in the GitHub repo settings before first use.

---

### P1-4: Add pytest-cov to CI

**File:** `.github/workflows/ci.yml:34`

**Current:**
```yaml
- name: Kernel test suite
  run: cd control-plane && python -m pytest -q
```

**Change to:**
```yaml
- name: Kernel test suite
  run: cd control-plane && python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=60
```

**Also** add `pytest-cov` to `control-plane/requirements.txt`:
```
pytest-cov==6.1.1
```

**Guardrail:** Start with `--cov-fail-under=60` (achievable now). Ratchet up after each phase. Do NOT
set it to 80+ immediately — that will block unrelated PRs.

---

## Phase 2 — Feature Completeness (C5/C8 gaps)

### P2-1: Add `presence.google.connect` action

**File:** `control-plane/app/adapters/presence.py`

Add to the plan section (alongside existing `presence.wordpress.connect`, ~line 30-86):

```python
# In plan() method, add a new action block:
if "search console" in text_lower or "gsc" in text_lower or "merchant center" in text_lower or "gmc" in text_lower:
    specs.append(OpSpec(
        domain="presence",
        action="presence.google.connect",
        params={
            "provider": "google",
            "scope": "search_console,merchant_center",
            "secret_ref": params.get("secret_ref", ""),
            "property_url": params.get("property_url", ""),
        },
        impact=1,
    ))
```

Add execute/verify/compensate handlers matching the pattern in `presence.wordpress.connect`
(~lines 167-225). The execute should:
1. Write OAuth token to Secret Manager via `SecretManagerClient`.
2. Create a `Connection(provider="google", scope="search_console,merchant_center", ...)` row.
3. Return `{"connected": True, "property_url": property_url}`.

Compensate (disconnect) should soft-delete the Connection row.

**Test:** Add `tests/test_presence_google_connect.py`:
- Plan with "connect search console" → produces `presence.google.connect` OpSpec.
- Execute → creates Connection row.
- Compensate → marks Connection inactive.
- Verify → checks connection exists.

**Guardrail:** Do NOT implement real Google OAuth flow yet — that's Phase 3. This step creates the
governed Op + Connection row (the same pattern as `manage.shopify.connect`). Real API verification
comes in P3.

---

### P2-2: Replace MockMarketingClient with a real-capable client (C8)

**File:** `control-plane/app/services/marketing.py`

**Current:** `MockMarketingClient` writes to a JSON file. No real API calls.

**Change architecture:**

```python
import os
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class MarketingClient(ABC):
    """Base interface for all marketing platform clients."""

    @abstractmethod
    async def create_campaign(self, account_id: str, campaign: dict) -> dict: ...

    @abstractmethod
    async def update_campaign(self, account_id: str, campaign_id: str, updates: dict) -> dict: ...

    @abstractmethod
    async def pause_campaign(self, account_id: str, campaign_id: str) -> dict: ...

    @abstractmethod
    async def resume_campaign(self, account_id: str, campaign_id: str) -> dict: ...

    @abstractmethod
    async def get_campaign(self, account_id: str, campaign_id: str) -> dict: ...

    @abstractmethod
    async def adjust_bid(self, account_id: str, campaign_id: str, bid_params: dict) -> dict: ...

    @abstractmethod
    async def adjust_budget(self, account_id: str, campaign_id: str, budget_params: dict) -> dict: ...


class MockMarketingClient(MarketingClient):
    """File-backed mock for dev/test. Existing behavior preserved."""
    # ... keep existing MockMarketingClient code unchanged ...


class GoogleAdsClient(MarketingClient):
    """Real Google Ads API client. Requires google-ads package."""

    def __init__(self, developer_token: str, client_id: str, client_secret: str, refresh_token: str, customer_id: str):
        self.customer_id = customer_id
        self._credentials = {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.ads.googleads.client import GoogleAdsClient as GAdsClient
            self._client = GAdsClient.load_from_dict(self._credentials)
        return self._client

    async def create_campaign(self, account_id: str, campaign: dict) -> dict:
        client = self._get_client()
        service = client.get_service("CampaignService")
        operation = client.get_type("CampaignOperation")
        # Build campaign resource from dict...
        # This is the shell — real implementation fills in the protobuf fields
        raise NotImplementedError("Google Ads campaign creation requires protobuf field mapping — see P3-1")

    # ... other methods raise NotImplementedError with clear messages ...


def get_marketing_client(provider: str = "mock", credentials: dict = None) -> MarketingClient:
    """Factory that returns the appropriate client based on provider and environment."""
    if os.getenv("AOS_ENV") == "test" or provider == "mock":
        return MockMarketingClient()
    if provider == "google_ads":
        if not credentials:
            raise ValueError("Google Ads client requires credentials dict")
        return GoogleAdsClient(**credentials)
    raise ValueError(f"Unknown marketing provider: {provider}")
```

**Then update** `control-plane/app/adapters/grow.py` execute methods to use `get_marketing_client()`:

In the execute method (~line 375+), replace direct `MockMarketingClient()` instantiation with:
```python
from app.services.marketing import get_marketing_client
from app.services.secrets import SecretManagerClient

# Retrieve credentials from the brand's connection
conn = await session.execute(
    select(Connection).where(Connection.brand_id == op.brand_id, Connection.provider == "google_ads")
)
connection = conn.scalar_one_or_none()

if connection and connection.secret_ref:
    sm = SecretManagerClient()
    creds = await sm.read_secret(connection.secret_ref)
    client = get_marketing_client("google_ads", json.loads(creds))
else:
    client = get_marketing_client("mock")
```

**Test:**
- Existing grow adapter tests must still pass (they'll get MockMarketingClient via `AOS_ENV=test`).
- Add `tests/test_marketing_client_factory.py`:
  - `get_marketing_client("mock")` → returns `MockMarketingClient`.
  - `get_marketing_client("google_ads", creds)` → returns `GoogleAdsClient`.
  - `get_marketing_client("google_ads")` without creds → raises `ValueError`.

**Guardrail:**
- Do NOT remove `MockMarketingClient` — it's the dev/test default.
- Do NOT add `google-ads` to `requirements.txt` yet — it's a large dependency. Add it in P3 when the
  real protobuf field mapping is implemented.
- The `GoogleAdsClient` methods should raise `NotImplementedError` with clear messages pointing to P3.
  This is the **interface + factory + wiring** step, not the full API implementation.

---

### P2-3: Wire `manage.backup.create` to real GCS

**File:** `control-plane/app/adapters/manage.py` (~line 187-190, currently just logs)

**Change to:**
```python
async def _execute_backup(self, op, session):
    from google.cloud import storage as gcs
    brand_id = op.brand_id
    bucket_name = os.getenv("AOS_BACKUP_BUCKET", f"aos-backups-{op.tenant_id}")

    if os.getenv("AOS_ENV") == "test":
        logger.info(f"[TEST] Would back up brand {brand_id} to gs://{bucket_name}/")
        return {"status": "mock_ok", "bucket": bucket_name}

    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"backups/{brand_id}/{dt.datetime.utcnow().isoformat()}.json")

    # Serialize brand state (connections, ops, config)
    brand_state = {
        "brand_id": brand_id,
        "timestamp": dt.datetime.utcnow().isoformat(),
        "connections": [...],  # query and serialize
    }
    blob.upload_from_string(json.dumps(brand_state), content_type="application/json")
    return {"status": "ok", "gcs_path": f"gs://{bucket_name}/{blob.name}"}
```

**Test:** Add `tests/test_manage_backup.py`:
- In test mode (`AOS_ENV=test`), backup returns mock_ok.
- Mock `google.cloud.storage.Client` → verify `upload_from_string` called with correct path.

**Guardrail:** Do NOT make the backup block on GCS availability — wrap in try/except and return
a degraded status if GCS is unreachable.

---

## Phase 3 — Real Provider Integrations

### P3-1: Real Google Ads API client

**File:** `control-plane/app/services/marketing.py` — fill in `GoogleAdsClient` methods.

**Dependency:** Add `google-ads==25.1.0` to `requirements.txt`.

**Implementation:** Each method must:
1. Build the protobuf request from the dict params.
2. Call the Google Ads API via the `google-ads` SDK.
3. Handle `GoogleAdsException` with structured error logging.
4. Return a normalized dict matching the existing mock response format.

**Key methods to implement:**
- `create_campaign` → `CampaignService.MutateCampaigns`
- `update_campaign` → same, with update operation
- `pause_campaign` → set `campaign.status = PAUSED`
- `adjust_bid` → `CampaignBidModifierService`
- `adjust_budget` → `CampaignBudgetService.MutateCampaignBudgets`

**Test:**
- Unit tests with mocked `GoogleAdsClient` (do NOT call real API in CI).
- Add `tests/test_google_ads_client.py`:
  - Mock the gRPC service → verify protobuf fields are set correctly.
  - Error handling: mock `GoogleAdsException` → verify graceful degradation.

**Guardrail:**
- Do NOT store Google Ads developer token in code — must come from Secret Manager via connection.secret_ref.
- Do NOT enable real API calls in CI — mock at the SDK level.
- Rate limit: Google Ads API has strict QPS limits. Add exponential backoff in the client.

---

### P3-2: Real Meta Ads API client

**File:** Add `control-plane/app/services/meta_ads.py`

**Dependency:** Add `facebook-business==21.0.0` to `requirements.txt`.

**Implementation:** Follows the same `MarketingClient` interface:
```python
class MetaAdsClient(MarketingClient):
    def __init__(self, app_id: str, app_secret: str, access_token: str, ad_account_id: str):
        from facebook_business.api import FacebookAdsApi
        FacebookAdsApi.init(app_id, app_secret, access_token)
        self.ad_account_id = ad_account_id

    async def create_campaign(self, account_id: str, campaign: dict) -> dict:
        from facebook_business.adobjects.campaign import Campaign
        from facebook_business.adobjects.adaccount import AdAccount
        account = AdAccount(f"act_{self.ad_account_id}")
        result = account.create_campaign(params={
            Campaign.Field.name: campaign["name"],
            Campaign.Field.objective: campaign.get("objective", "OUTCOME_TRAFFIC"),
            Campaign.Field.status: "PAUSED",  # always create paused, activate via separate op
            Campaign.Field.special_ad_categories: [],
        })
        return {"campaign_id": result["id"], "status": "PAUSED"}
```

**Update** `get_marketing_client()` factory to return `MetaAdsClient` for `provider="meta"`.

**Test:** Same pattern as P3-1 — mock at the SDK level, verify field mapping.

**Guardrail:**
- Always create campaigns in PAUSED state — activation must be a separate governed Op.
- The Meta Business SDK is synchronous — wrap calls in `asyncio.to_thread()` to avoid blocking the event loop.

---

### P3-3: Configure real MCP for Shopify

**File:** `control-plane/app/services/mcp.py`

**Current:** Falls back to mock if no `server_url` provided.

**What to change:**
The `McpClient` transport layer is already functional (JSON-RPC over HTTP). The gap is:
1. No Shopify MCP server is deployed.
2. `manage.shopify.connect` verify step (~`manage.py:354`) doesn't pass `server_url`.

**Steps:**
1. Deploy the Shopify MCP server (see https://github.com/anthropics/shopify-mcp-server or equivalent).
   Add env var `SHOPIFY_MCP_SERVER_URL`.
2. In `control-plane/app/adapters/manage.py` verify method (~line 339-361):
   ```python
   mcp_url = os.getenv("SHOPIFY_MCP_SERVER_URL") or connection.config.get("mcp_server_url")
   mcp = McpClient(server_url=mcp_url)
   result = await mcp.call_tool("shopify_get_shop_info", {"shop_url": connection.config.get("shop_url")})
   ```
3. Add `SHOPIFY_MCP_SERVER_URL` to `DEPLOY.md` env var list.

**Test:**
- Mock the MCP server HTTP endpoint in tests → verify JSON-RPC request/response cycle.
- Integration test (if MCP server is running): `SHOPIFY_MCP_SERVER_URL=http://... pytest tests/test_mcp_integration.py`.

**Guardrail:**
- Do NOT make MCP server mandatory for boot — fallback to mock in dev/test.
- Do NOT hardcode MCP server URL — must be env var.

---

### P3-4: Real GSC/GMC integration for Presence audits

**File:** `control-plane/app/adapters/presence.py` (~line 227-309)

**Current:** `presence.search_console.audit` and `presence.merchant_center.audit` return hardcoded mock findings.

**Dependencies:** Add `google-api-python-client==2.165.0` and `google-auth-oauthlib==1.2.1` to `requirements.txt`.

**Implementation pattern:**
```python
async def _execute_gsc_audit(self, op, session):
    if os.getenv("AOS_ENV") == "test":
        return self._mock_gsc_findings(op)

    from app.services.secrets import SecretManagerClient
    sm = SecretManagerClient()
    conn = await self._get_connection(session, op.brand_id, "google", "search_console")
    creds_json = await sm.read_secret(conn.secret_ref)

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.loads(creds_json))
    service = build("searchconsole", "v1", credentials=creds)

    # Query search analytics for the property
    response = service.searchanalytics().query(
        siteUrl=conn.config.get("property_url"),
        body={"startDate": "...", "endDate": "...", "dimensions": ["page"], "rowLimit": 100}
    ).execute()

    findings = self._analyze_gsc_data(response)
    return {"findings": findings, "source": "real"}
```

**Test:** Mock `googleapiclient.discovery.build` → return fixture data → verify findings analysis.

**Guardrail:**
- Keep the mock path for `AOS_ENV=test` — do NOT remove it.
- GSC/GMC are read-only APIs — ARCHITECTURE.md §6.5 mandates Presence is read-only. Do NOT add
  any write operations to Presence.
- OAuth token refresh must be handled — GSC access tokens expire. Use `google-auth` refresh flow.

---

## Phase 4 — Observability & Polish

### P4-1: Add security headers middleware

**File:** `control-plane/app/middleware.py` — add new class:

```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if os.getenv("ENV") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
```

**Register in `main.py`** after CORS middleware:
```python
from app.middleware import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)
```

**Test:** Add `tests/test_security_headers.py`:
- GET `/healthz` → response has `X-Content-Type-Options: nosniff`.
- In prod mode → response has `Strict-Transport-Security`.

**Guardrail:** Only add HSTS in production (`ENV=production`) — it breaks local dev over HTTP.

---

### P4-2: Add Prometheus metrics endpoint

**File:** Create `control-plane/app/metrics.py`:

```python
import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import PlainTextResponse

request_count = defaultdict(int)
request_latency_sum = defaultdict(float)

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        key = f'{request.method}_{request.url.path}_{response.status_code}'
        request_count[key] += 1
        request_latency_sum[key] += duration
        return response

def metrics_endpoint(request):
    lines = []
    for key, count in request_count.items():
        method, path, status = key.rsplit("_", 2)
        lines.append(f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
        lines.append(f'http_request_duration_seconds_sum{{method="{method}",path="{path}",status="{status}"}} {request_latency_sum[key]:.4f}')
    return PlainTextResponse("\n".join(lines), media_type="text/plain")
```

Register: `app.add_middleware(MetricsMiddleware)` and `app.get("/metrics")(metrics_endpoint)`.

**Guardrail:** Do NOT use the `prometheus_client` library yet — it adds dependency weight. This
simple counter is sufficient for Cloud Monitoring scraping. Upgrade later if needed.
Do NOT expose `/metrics` publicly — add it to the tenant-bypass list in `TenantIsolationMiddleware`
and consider auth-protecting it.

---

## Phase 5 — Frontend Hardening

### P5-1: Split dashboard into proper routes

**Current:** `control-plane/web/src/app/page.tsx` is 6,600+ lines — everything in one page.

**Change:** Extract tab content into separate route files:

```
control-plane/web/src/app/
├── page.tsx              (landing/dashboard summary — keep, but slim down)
├── ops/
│   └── page.tsx          (ops list + detail drawer)
├── connections/
│   └── page.tsx          (connections management)
├── policy/
│   └── page.tsx          (policy editor + simulate)
├── audit/
│   └── page.tsx          (audit chain viewer)
└── layout.tsx            (shared nav + TenantProvider)
```

**Steps:**
1. Extract the ops tab JSX into `ops/page.tsx` as a server component with client islands.
2. Extract connections tab into `connections/page.tsx`.
3. Extract audit/safety tabs into their respective pages.
4. Keep `page.tsx` as a dashboard summary with links to each section.
5. Move shared state (tenant context, API hooks) into `src/lib/` or keep in `contexts/`.

**Test:** `npm run lint && npm test && npm run build` must pass after each extraction.
Visually verify each page renders correctly in the browser.

**Guardrail:**
- Do NOT rewrite component logic — only move JSX blocks into new files.
- Do NOT change the API calls — only the routing structure.
- Read `node_modules/next/dist/docs/` for any Next.js breaking changes (per AGENTS.md).
- Keep the detail drawer as a shared component imported by the ops page.

---

## Review & Test Checklist

### Before each PR merge:
- [ ] CI green (both `tests` and `web` jobs)
- [ ] No new `any` types in TypeScript (ESLint enforces)
- [ ] No hardcoded secrets (CI invariant check enforces)
- [ ] No model SDK in gating modules (CI invariant check enforces)
- [ ] At least one failure-path test per new feature

### Before prod deploy (all phases complete):
- [ ] `ENV=production` boot succeeds with all required env vars set
- [ ] `ENV=production` boot fails if `OPERATOR_TOKEN` is `default-dev-token`
- [ ] `ENV=production` boot fails if `WHATSAPP_APP_SECRET` is missing
- [ ] Docker image runs as non-root user
- [ ] `/healthz` returns 200; `/readyz` returns 200 with DB connected
- [ ] CORS rejects requests from unlisted origins
- [ ] Rate limiting triggers on burst traffic to `/chat`
- [ ] `POST /tenants` with invalid token → 403
- [ ] `GET /tenants` with valid token → returns tenant list
- [ ] Op creation → traces visible in detail drawer (flat detail format)
- [ ] `governance.policy.update` Op → changes gate outcomes
- [ ] Cross-tenant read isolation verified on real Postgres
- [ ] Outbox drain processes pending items → ops transition to DONE
- [ ] Trust score computation returns valid tier (0/1/2)
- [ ] WhatsApp webhook with valid signature → processed
- [ ] WhatsApp webhook with invalid signature → 401
- [ ] Plugin webhook (Shopify) with valid HMAC → Op proposed
- [ ] Cloud Tasks drain endpoint rejects unauthenticated requests

### Load test (before GA):
- [ ] 100 concurrent `/ops` GETs → p99 < 500ms
- [ ] 50 concurrent `POST /chat` → rate limiter activates correctly
- [ ] DB pool (10 + 20 overflow) doesn't exhaust under load
- [ ] Memory stays stable over 1000 op submissions (no leak)

---

## Dependency Summary

### New packages needed (add in the phase that uses them):
| Package | Phase | Purpose |
|---------|-------|---------|
| `pytest-cov==6.1.1` | P1-4 | Test coverage in CI |
| `google-ads==25.1.0` | P3-1 | Real Google Ads API |
| `facebook-business==21.0.0` | P3-2 | Real Meta Ads API |
| `google-api-python-client==2.165.0` | P3-4 | GSC/GMC API |
| `google-auth-oauthlib==1.2.1` | P3-4 | Google OAuth flow |

### Env vars needed for production:
| Variable | Required | Default | Phase |
|----------|----------|---------|-------|
| `ENV` | Yes | — | P0-1 |
| `OPERATOR_TOKEN` | Yes (prod) | `default-dev-token` | P0-1 |
| `DATABASE_URL` | Yes | localhost (forbidden in prod) | P0-1 |
| `WORKER_DATABASE_URL` | Yes | — | existing |
| `WHATSAPP_APP_SECRET` | Yes (prod) | — | existing |
| `WHATSAPP_TOKEN` | Yes | — | existing |
| `WHATSAPP_VERIFY_TOKEN` | Yes | — | existing |
| `WHATSAPP_PHONE_NUMBER_ID` | Yes | — | existing |
| `WHATSAPP_APPROVER_PHONE` | Yes | — | existing |
| `GCP_PROJECT` | Yes | — | existing |
| `GCP_LOCATION` | Yes | — | existing |
| `ALLOWED_ORIGINS` | Yes | hardcoded fallback | P0-6 |
| `SENTRY_DSN` | Recommended | — | existing |
| `AOS_BACKUP_BUCKET` | For backups | auto-generated | P2-3 |
| `SHOPIFY_MCP_SERVER_URL` | For Shopify | mock fallback | P3-3 |
| `GOOGLE_APPLICATION_CREDENTIALS` | For GCP services | — | existing |
| `WIF_PROVIDER` | For CD | — | P1-3 (GitHub secret) |
| `WIF_SERVICE_ACCOUNT` | For CD | — | P1-3 (GitHub secret) |

---

## Commit Order (linear — each depends on the previous)

```
P0-1  fix(security): enforce OPERATOR_TOKEN + DATABASE_URL in production boot
P0-2  fix(security): use constant-time comparison for operator token
P0-3  fix(security): add input length validation to Pydantic models
P0-4  feat(api): add global exception handler with trace context
P0-5  fix(security): extend rate limiting to operator endpoints
P0-6  fix(security): restrict CORS allow_methods
P0-7  fix(security): retrieve webhook HMAC key from Secret Manager in prod
P1-1  fix(infra): Dockerfile non-root user + HEALTHCHECK
P1-2  feat(db): make outbox.tenant_id NOT NULL
P1-3  feat(ci): add Cloud Run CD workflow
P1-4  feat(ci): add pytest-cov with 60% floor
P2-1  feat(presence): add presence.google.connect governed action
P2-2  refactor(grow): extract MarketingClient interface + factory pattern
P2-3  feat(manage): wire backup.create to real GCS
P3-1  feat(grow): implement real Google Ads client
P3-2  feat(grow): implement real Meta Ads client
P3-3  feat(manage): configure real Shopify MCP server
P3-4  feat(presence): implement real GSC/GMC audit via API
P4-1  feat(security): add security headers middleware
P4-2  feat(observability): add Prometheus-style metrics endpoint
P5-1  refactor(web): split monolithic page.tsx into route-based pages
```

Each commit = 1 PR. Each PR = CI green before merge. No skipping phases.
