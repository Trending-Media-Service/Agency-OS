# Operator-Assisted Brand Onboarding (Runbook)

How to onboard a brand — e.g. your first tenant, **"Ableys"** — through the
onboarding API, until the self-serve frontend wizard exists.

> **Context:** Agency-OS today ships an **operator console**, not brand
> self-serve signup. There is no brand-level login yet, so the operator drives
> onboarding on the brand's behalf. The backend endpoints below
> (`app/routers/onboarding.py`) are currently **open** (they trust the
> `tenant_id`/`brand_id` in the request) — fine for operator-driven onboarding,
> but they must be secured behind brand auth before any public self-serve use.

## Prerequisites

- **Platform OAuth app credentials** provisioned in Secret Manager
  (`./load_credentials.sh`; see `credentials.example.env`) and wired into the
  backend by the deploy's **"Resolve runtime secrets"** step. Until a provider's
  secret exists, its OAuth uses the `mock-*` fallback and **cannot** complete a
  real handshake.
- `BACKEND` = the deployed control-plane URL (your custom domain, e.g.
  `https://api.yourdomain.com`, or `https://agency-os-backend-…run.app`).
- **`SECRET_KEY`** (secret `aos-oauth-state-secret`) must also be provisioned — it
  HMAC-signs the OAuth `state`. Without it the app uses an insecure hardcoded
  default and state tokens are forgeable. Generate once: `openssl rand -base64 32`.

> **Quick start:** `BACKEND=https://api.yourdomain.com ./scripts/onboard.sh --name Ableys --domain ableys.com --shop ableys`
> bootstraps the tenant and prints the authorize URLs + follow-up commands. The
> steps below are the manual equivalent.

## Step 1 — Create the tenant + brand

`POST /api/v1/onboarding/bootstrap` (scalar args are query params):

```bash
curl -sS -X POST \
  "$BACKEND/api/v1/onboarding/bootstrap?name=Ableys&domain=ableys.com&tier=shared"
# → { "tenant_id": "...", "brand_id": "...", "status": "onboarding_ready", "tier": "shared" }
```

Capture `tenant_id` and `brand_id` — every later step needs them.

## Step 2 — Connect data / ad sources (OAuth)

Open each authorize URL in a browser (you, or the brand contact, completes the
consent). On success the callback exchanges the code, seeds a `Connection`, and
— for Shopify — kicks off the catalog RAG scan + brand-identity synthesis.

```
$BACKEND/api/v1/onboarding/oauth/authorize/{provider}
    ?tenant_id=<tenant_id>
    &brand_id=<brand_id>
    &redirect_uri=$BACKEND/api/v1/onboarding/oauth/callback
    &shop=<store-handle>        # Shopify only (e.g. ableys or ableys.myshopify.com)
```

OAuth-redirect providers: `shopify`, `google-ads`, `meta-ads`, `tiktok-ads`,
`hubspot`, `salesforce`.

> **Shopify:** pass the store handle/domain via `&shop=` (e.g. `shop=ableys` or
> `shop=ableys.myshopify.com`). It is carried in the signed OAuth state, so the
> callback completes the token exchange and the catalog RAG scan against the
> correct store. If omitted, it falls back to `brand_id` (legacy behavior).

## Step 3 — Connect key-based services (no OAuth)

For providers that use a static API key (e.g. Stripe, Klaviyo, a Shopify
private app):

```bash
curl -sS -X POST \
  "$BACKEND/api/v1/onboarding/connection/direct?tenant_id=<tenant_id>&brand_id=<brand_id>&provider=klaviyo&api_key=<KEY>"
```

The key is written to Secret Manager (tenant/brand-scoped) and a `Connection`
row is seeded.

## Step 3b — Provider settings (e.g. Google Ads developer token)

Some providers need config that OAuth doesn't capture — notably the Google Ads
**developer token** (Ads → Tools → API Center), read by
`app/services/google_ads.py` from the connection `config`. After the Google Ads
OAuth connection exists, merge it in:

```bash
curl -sS -X POST \
  "$BACKEND/api/v1/onboarding/connection/config?tenant_id=<tenant_id>&brand_id=<brand_id>&provider=google-ads" \
  -H 'Content-Type: application/json' -d '{"developer_token":"<YOUR_DEV_TOKEN>"}'
```

## Step 3c — Headless storefront on GitHub (e.g. Tanmatra)

No first-class GitHub connector exists yet, but a headless site is supported today:

1. Register the site (URL + a deploy token, e.g. Vercel) as a `web` connection:
   ```bash
   curl -sS -X POST \
     "$BACKEND/api/v1/onboarding/connection/direct?tenant_id=<tenant_id>&brand_id=<brand_id>&provider=web&api_key=<DEPLOY_TOKEN>" \
     -H 'Content-Type: application/json' -d '{"url":"https://tanmatra.com"}'
   ```
2. Drive code changes through the build agent (`build_deliver`) with the GitHub
   repo URL + a GitHub PAT as the access token. (A real "Connect GitHub" OAuth
   connector is future work.)

## Step 4 — Verify

- `GET $BACKEND/connections` with header `X-Tenant-ID: <tenant_id>` → the new
  connections show `status: "active"`.
- Shopify: the background RAG scan imports the product catalog and synthesizes
  the brand identity.

## Known gaps (tracked for the self-serve epic)

- **No brand auth** — onboarding endpoints trust the IDs in the URL. Secure them
  to an authenticated brand session before exposing self-serve.
- **No frontend wizard / callback page** — drive via the URLs above (or
  `scripts/onboard.sh`) for now.
- **No first-class GitHub connector** — headless apps use a `web` connection +
  the build agent with a repo URL + PAT (Step 3c); real GitHub OAuth is future work.
