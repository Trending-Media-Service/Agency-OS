# Connections Epic (C5) — Engineering Execution Brief

> **Type:** Execution work-order for the engineering agent. This is **not** a roadmap or
> strategy document — the single roadmap remains `ARCHITECTURE.md §9`. This brief
> *implements existing* `ARCHITECTURE.md` sections (§4 kernel, §5 + §5.1 adapters & plugin
> webhooks, §6.3 Manage, §6.5 Presence); it introduces no new product direction.
>
> **Authority order:** `ARCHITECTURE.md` (authoritative) → `AGENTS.md` (binding rules) →
> this brief. If this brief disagrees with either, they win — open an issue and stop.

---

## Context
The connector directory shipped (PR #151): an operator picks a provider, supplies a
credential, and the system stores it in Secret Manager + creates a governed `Connection`.
That is only the *intake* half. There is no way to **verify** a connection works, see its
**health**, **disconnect/revoke** it, **rotate** its secret, or connect via **OAuth**
("Sign in with Google/Meta") — and a latent naming bug means the credential field means
opposite things on the two sides of the wire. This epic makes connections first-class,
auditable, observable, and self-service **without ever leaving the governed pipeline**.

Scope decision (owner): **phased — harden first (Phases 0–4), OAuth second (Phase 5)**,
with all four value-add bundles (health/verify, async hardening, observability, rotation)
folded in.

---

## Part A — Operating instructions (read before touching any phase)

### How to use this brief
- **6 phases (0 → 5), each is ONE PR.** Execute in order; Phase 2 may parallelize.
- **One issue per PR (AGENTS.md §2).** Open a tracking issue as you *start* each phase —
  the phase section in Part B is the issue body (goal / changes / tests / DoD). One PR
  closes one issue.
- **Branch naming (AGENTS.md):** `s1-<issue#>/<slug>`.
- **Open PRs as draft; the owner merges.** Keep PRs ≲500 changed lines outside generated
  migrations/lockfiles (AGENTS.md §3); if a phase exceeds that, split it.

### Prime directive (non-negotiable)
Every connect / verify / disconnect / rotate / OAuth-callback **proposes a governed Op**
and rides the loop: `propose → preview_and_gate → approve (auto/human) → drain/execute
(outbox) → verify → audit` (`ARCHITECTURE.md §2.3` no silent writes, `§4.1` state machine).
**Never** a direct `connections` write or out-of-band side effect — including for the
operator.

Binding `AGENTS.md` prohibitions that bite this epic:
- **No model in any gating path** (§2.1) — verify/health probes may *report*, never *gate*.
- **Never bypass the Op state machine.** `ALLOWED_TRANSITIONS` edits require an
  `ARCHITECTURE.md §4.1` amendment in the **same PR**.
- **Never weaken the audit chain** (§4.5). Audit rows are append-only.
- **Statutory firewall is permanent** (§2.2) — connections are non-statutory; never add a
  statutory auto-approval path.
- **No secrets in the repo** — credentials are Secret Manager refs only.
- **No new top-level directories**; adapters live in `control-plane/app/adapters/`.
- **No new runtime dependencies** unless the phase's issue names them (stack fixed by §8).
- **Do not generate new strategy/roadmap markdown docs.**

### Architecture-amendment triggers in THIS epic (amend in the same PR — do not improvise)
Per `AGENTS.md §1`, where the plan touches something the authoritative architecture
constrains, amend `ARCHITECTURE.md` in the same PR rather than working around it:

1. **Adapter family (Phase 1).** §1 frames *four* adapter families
   (provision/build/manage/grow); Presence (§6.5) is already a de-facto 5th. A shared
   connection-lifecycle code path is needed (verify/disconnect/rotate are duplicated
   across the grow/presence/manage connect branches today).
   **Preferred:** house lifecycle in the **Manage** pillar — §6.3 is literally "connect,
   observe, and operate existing client infrastructure", the natural home — by extending
   `ManageAdapter` with `manage.connection.{verify,revoke,rotate}` actions plus a shared
   `connection_probes` module, introducing **no new adapter family**. If you instead add a
   standalone `connection` domain, amend §1/§5 to name the new family. (Either way, see the
   UI naming invariant below — it constrains the *tool name*, not the *action*.)
2. **Observability (Phase 4).** §8 says "No ELK/Jaeger/Prometheus stack", yet a Prometheus
   registry + `/metrics` already exist in `control-plane/app/middleware.py` (code has
   drifted from the doc). Resolve explicitly **in the PR**: either amend §8 to sanction the
   already-present `/metrics` + Cloud Monitoring alerts, or implement observability on the
   sanctioned **Sentry + Cloud Logging + one dashboard** path (§8). Do not silently expand
   Prometheus usage without the amendment; also reconcile §10 (which currently defers a
   "Prometheus stack").
3. **Schema (Phases 1 & 5).** Any new tenant-scoped table (e.g. `oauth_states`) is added to
   the `§3` RLS table list in the same PR, with the full RLS treatment (see "RLS triple-touch"
   below). New Op *actions* reuse the existing state machine — confirm there is **no**
   `ALLOWED_TRANSITIONS` change; if there is, amend §4.1.

### The connector UI naming invariant (load-bearing — pin it in a test)
`control-plane/web/src/app/(dashboard)/connections/page.tsx` builds the directory grid from
`t.name.includes("connect")`. Therefore **connect tools MUST contain "connect" in their
registry name; lifecycle tools (verify/revoke/rotate) MUST NOT.** The filter reads the
registry **tool name**, not the Op **action** — so action strings like
`manage.connection.verify` are fine; only the tool name matters. Pin both directions in
`tests/test_connector_contract.py`.

### Credential hygiene (binding — §2 "no secrets")
Raw credentials/tokens are written to the brand project's Secret Manager at execute time;
the control-plane DB stores only the `secret_ref` pointer + non-secret config. **Never log,
preview, or audit a raw credential** (mask it in `preview_summary`). OAuth refresh/access
tokens live only in Secret Manager.

### RLS triple-touch (any new RLS table)
1. Model in `control-plane/app/models.py` (carry `tenant_id`).
2. Alembic migration: `ENABLE` + `FORCE ROW LEVEL SECURITY`, a `tenant_isolation` `USING`
   policy, **and** a `worker_bypass` PERMISSIVE policy
   `FOR ALL TO <worker_role> USING(true) WITH CHECK(true)`.
3. Mirror that `worker_bypass` into `control-plane/scripts/setup_worker_role.sql`.
New Alembic revisions chain from the current head (`alembic heads`) — never hardcode a
parent hash. The Postgres guardrail `tests/test_api_rls_postgres.py` auto-discovers RLS
tables, so new tables are covered for free. Sessions: request paths use `get_db`
(`set_config app.current_tenant_id`); worker/outbox paths use `get_worker_db`. **Never
`SET LOCAL`** (it caused a prod 500; the RLS test asserts its absence).

### Definition of done (every PR — `AGENTS.md` DoD + epic specifics)
- [ ] `cd control-plane && pytest` green (all of it), including ≥1 **failure-path** test.
- [ ] `cd control-plane/web && npm run lint && npm test && npm run build` green.
- [ ] New state-changing behavior emits `OpTrace` + audit events.
- [ ] CI green: both the `tests` and `web` jobs; new invariant greps pass.
- [ ] `control-plane/README.md` REAL-vs-STUB table updated if a status changed.
- [ ] PR body names the issue (`Closes #N`) and the `ARCHITECTURE.md` sections it
      implements/amends.
- [ ] Contract test asserts no raw credential in logs/preview/audit.
- [ ] No TODOs left for invariants (deferred-feature TODOs need an issue reference).

### When to stop and ask (`AGENTS.md` "When blocked")
Stop and comment on the issue if: a test you didn't write fails, the issue contradicts
`ARCHITECTURE.md`, or a change would touch two prohibitions. Epic-specific: external OAuth
app registration (Google/Meta) and **prod `gcloud`** (queue, scheduler, alert policies,
secret rotation) are the **owner's** actions — deliver scripts/runbooks, build behind the
`AOS_ENV=test` mock, and neither execute them against prod nor block on them.

### What NOT to do
- Don't merge your own PRs or push to `main`.
- Don't run prod `gcloud` or rotate prod secrets (ship `scripts/*.sh` runbooks instead).
- Don't register OAuth apps (owner does; build + test behind the mock).
- Don't add runtime deps or top-level dirs; don't edit `legacy/` or `docs/archive/`.

---

## Part B — The phased plan

> Each phase: **Goal · Backend · Frontend · Migration · Tests · Guardrails · Reviewer
> checklist · Verify · Risk.** Reuse existing utilities (named inline) — avoid net-new code
> where the repo already has a pattern.

### Phase 0 — Fix the `secret_ref` contract (rename → `credential`)
**Goal.** The inbound raw-value field becomes `credential`; `secret_ref` is reserved
exclusively for the Secret-Manager pointer on the row. Backward-compatible, no behavior
change. Stop leaking the raw value into previews/audit (a §2 security fix).

Today both the `_*_connect_handler` functions in `control-plane/app/kernel/tools.py` **and**
each adapter's `plan()` build an `OpSpec` whose `params["secret_ref"]` is the **raw value**;
`execute()` writes it to Secret Manager and stores the returned **pointer** in
`Connection.secret_ref`. Same key = two meanings, and tests pin the ambiguous shape.

- **Backend** (`tools.py`, `adapters/{grow,presence,manage}.py`):
  - *Consumer* (every `execute()` connect branch): `raw = op.params.get("credential") or
    op.params.get("secret_ref")` — accept-both so already-proposed outbox Ops survive deploy.
  - *Producers* (handlers + adapter `plan()`): rename kwarg + schema property
    `secret_ref → credential`; emit `params={"provider":…, "credential":…, "config":…}`.
    Rename `_SECRET_REF_PROP → _CREDENTIAL_PROP` ("Provider API credential/token; stored to
    Secret Manager, never persisted in the DB").
  - *`preview()`*: stop printing the raw value — emit a masked marker (`Credential: ****`).
  - *Cleanup*: delete the now-dead `parse_chat_to_tool_call` regex parser (chat is gone).
- **Frontend** (`connections/page.tsx`): broaden the password-field heuristic from
  `name.includes("secret")` to also match `credential|token|password`.
- **Migration:** none (`Connection.secret_ref` column meaning unchanged — always the pointer).
- **Tests:** update `test_grow_adapter_connections.py` / `test_presence_adapter_connections.py`
  to assert `op.params["credential"]` and `read_secret(conn.secret_ref)` round-trips; update
  `test_actions_endpoint.py::test_actions_connect_is_governed` to POST `credential`. New
  `tests/test_connector_contract.py`: every "connect" tool exposes `credential` not
  `secret_ref`; the legacy `secret_ref` accept-both path still creates a connection;
  `preview_summary` never contains the raw value.
- **Guardrails:** introduces the "no secret in preview/audit" contract assertion (see
  cross-cutting CI greps).
- **Reviewer checklist:** ☐ all 3 adapters accept both keys ☐ no connect schema exposes
  `secret_ref` ☐ preview masks the value ☐ frontend masking still fires ☐ `secret_ref`
  column unchanged.
- **Verify:** the four named pytest files + `npm test`.
- **Risk:** must land first (all later phases assume the split). Low blast radius; only
  subtlety is persisted-Op back-compat, handled by accept-both.

### Phase 1 — Connection lifecycle: verify + health
**Goal.** Governed `verify` (read-only health probe) and `disconnect/revoke` (delete SM
secret + row, audited) per provider, with health surfaced in `GET /connections` and the
directory. **See Part A amendment trigger #1** — prefer extending the **Manage** pillar
(`manage.connection.{verify,revoke}`) over a new `connection` domain; amend `ARCHITECTURE.md`
accordingly in this PR.

- **Backend:**
  - `models.py` — extend `Connection`: `status` (default `unverified`;
    `healthy|degraded|expiring|revoked`), `last_verified_at`, `last_error` (Text),
    `expires_at`, `updated_at`.
  - Lifecycle handling (in `ManageAdapter`, or a new adapter if a `connection` domain is
    chosen): `execute()` for verify loads the row, dispatches to a **provider-probe
    registry** (`dict[provider → async probe]`) and sets status/last_verified_at/last_error/
    expires_at; for revoke deletes the SM secret + row. `verify()`/`compensate()` per the
    severity conventions below. **Relocate** the existing live checks (Shopify MCP
    `shopify_get_shop_info`, Google token read, etc.) into the probe registry so connect-time
    and lifecycle verify share one path.
  - `tools.py` — register `connection_health_check` and `connection_revoke` (params
    `{provider}`). **Tool names must not contain "connect".**
  - `main.py` — register the adapter if new; extend `ConnectionOut` + `GET /connections`
    with the health fields.
- **Frontend** (`connections/page.tsx`): health pill on each connected card
  (green/amber/red), "Verify" + "Disconnect" buttons on Active Connections rows posting
  `connection_health_check` / `connection_revoke`; add Status / Last-Verified columns.
- **Migration:** `add_connection_health_columns` (chain from head); columns nullable, server
  default for `status`. No new table → no `setup_worker_role.sql` change.
- **Tests:** `test_connection_lifecycle.py` (verify-ok → healthy; verify-fail → degraded +
  `last_error` + `ExecResult.ok=False`; revoke → row gone + `read_secret` raises);
  `test_connections_lifecycle_api.py` (POST `/actions` → drain → `GET /connections` reflects
  status; revoke removes provider); vitest `connections/page.test.tsx` (pills render;
  Disconnect posts `connection_revoke`).
- **Reviewer checklist:** ☐ verify read-only & governed ☐ revoke deletes SM secret inside the
  governed drain txn & is audited ☐ probes reuse existing live checks ☐ lifecycle tool names
  lack "connect" ☐ no raw secret in `GET /connections` ☐ ARCHITECTURE.md §1/§5/§6.3 amended.
- **Verify:** named pytest + vitest; manually confirm a degraded provider shows red.
- **Risk:** depends on Phase 0. Easier than it looks — the live checks already exist; you are
  relocating them into one shared probe registry.

### Phase 2 — Async hardening (`aos-outbox` Cloud Tasks queue + DLQ)
**Goal.** Create the prod queue with retry + dead-letter semantics, secure the task callback
with OIDC, make DEAD items visible + retryable. (Implements §4.2 reliability.)

- **Infra (runbook + `scripts/create_outbox_queue.sh`; owner runs against prod):**
  `gcloud tasks queues create aos-outbox --project=aos-control-plane-tmg
  --location=asia-south1 --max-attempts=5 --min-backoff=2s --max-backoff=300s
  --max-doublings=4 --max-concurrent-dispatches=10 --max-dispatches-per-second=5`.
  **DLQ strategy:** Cloud Tasks has no native DLQ topic; the durable DLQ is the `outbox`
  table filtered by `status='DEAD'` (the app DEADs at `attempts>=5`, `loop.py:~590`). Keep
  `--max-attempts=5` equal to that threshold.
- **Backend (`app/tasks.py`):** add `oidc_token`
  (`{service_account_email: AOS_WORKER_SERVICE_ACCOUNT, audience: APP_URL}`) to the task's
  `http_request` when the SA env is set; remove the leftover `print("[DEBUG]…")` lines.
  **Ship the `oidc_token` and the `AOS_WORKER_SERVICE_ACCOUNT` env (`deploy.yml`
  `--set-env-vars`) together** — enabling `verify_worker_auth` without the token 401s the
  prod drain. (Env var is `OUTBOX_QUEUE_NAME`, already set to `aos-outbox` in `deploy.yml`.)
- **Backend (`main.py`):** `GET /outbox/dead` (operator-auth) lists DEAD items joined to
  their Ops; **promote** the existing `/debug/reset/{op_id}` into an operator-authed
  `POST /outbox/{op_id}/retry` (reset item → PENDING/attempts=0/next_attempt_at=now; Op back
  to APPROVED if terminal-failed; then `enqueue_drain`). Don't duplicate it.
- **Frontend:** a small "Dead Letter Queue" panel on the ops dashboard (not the connections
  page) with a Retry button.
- **Migration:** none (`outbox` already has RLS).
- **Tests (mirror `test_safety_primitives.py`'s `FailingAdapter`):** `test_outbox_retry.py`
  (backoff `next_attempt_at == now + 2**attempts`; PENDING for attempts 1–4; DEAD at 5);
  `test_outbox_dlq_api.py` (seed DEAD → list → retry → drain succeeds); a `tasks.py` unit
  test asserting the task carries `oidc_token.service_account_email` + `audience` when the SA
  env is set.
- **Guardrails:** optional post-deploy `gcloud tasks queues describe aos-outbox` check so a
  missing queue fails the deploy loudly instead of silently falling back to in-process tasks.
- **Reviewer checklist:** ☐ queue `max-attempts` == app DEAD threshold (5) ☐ `oidc_token` +
  SA env ship together ☐ DLQ listable & retryable via operator auth ☐ debug endpoint promoted
  not duplicated ☐ drain still uses `set_config`, never `SET LOCAL`.
- **Verify:** named pytest; staging: push an Op, observe Cloud Tasks → `/tasks/drain-outbox`
  200; force 5 failures → DEAD → retry.
- **Risk:** independent of 0/1 (parallelizable). The OIDC+SA coupling is the sharp edge —
  verify in staging first.

### Phase 3 — Token & secret rotation + the missing scheduler
**Goal.** Governed secret rotation; scheduled OAuth refresh-before-expiry; **stand up Cloud
Scheduler** (none exists today — `/tasks/*` endpoints have never auto-fired, so trust
snapshots & cadences have silently never run); operator-token rotation runbook.

- **Backend:**
  - Add `connection.rotate` (tool `connection_rotate_secret` — no "connect" substring):
    `execute()` writes a **new SM version** and repoints `Connection.secret_ref`; stash the
    prior ref in the Op so `compensate()` rolls back → impact1 **COMPENSATABLE**.
  - Generalize `app/services/google_audit.py::_refresh_token` into
    `app/services/oauth.py::refresh_oauth_token(provider, config) → (token, expires_at)`;
    `_refresh_token` becomes a thin caller (one primitive shared by the on-401 path and the
    scheduled path).
  - New worker endpoint `POST /tasks/refresh-tokens` (OIDC-guarded, `get_worker_db`, added to
    the `TenantIsolationMiddleware` bypass list like the other `/tasks/*`): scan connections
    near `expires_at` with a `refresh_token` in config; for each, **propose a governed
    `connection.rotate` Op** under that connection's tenant context (mirror the §5.1
    plugin-webhook `set_config` + `propose` pattern). Never refresh out-of-band.
  - `scripts/create_schedulers.sh` (owner runs): Cloud Scheduler `http` jobs (with
    `--oidc-service-account-email`/`--oidc-token-audience`) for **all** `/tasks/*`:
    `drain-outbox` (frequent), `process-cadences`, `trust-snapshots`, `refresh-tokens`
    (hourly). **Flag to owner:** this also activates trust-snapshots/cadences that have never
    run — expect new background activity.
  - Operator-token rotation runbook (it is the SM secret `aos-operator-token`):
    `gcloud secrets versions add aos-operator-token …` → `gcloud run services update
    agency-os-backend --update-secrets=OPERATOR_TOKEN=aos-operator-token:latest` (restart
    required) → rotate the console's stored token. Zero-downtime order: add version → deploy
    → update clients → disable old version.
- **Frontend:** "Rotate"/"Refresh now" affordance on connected-provider rows.
- **Migration:** none beyond Phase 1's columns.
- **Tests:** `test_connection_rotate.py` (rotate v1→v2; `read_secret` returns v2; ref changed;
  compensate restores prior ref); `test_oauth_refresh.py` (mock via `AOS_ENV=test`;
  near-expiry connection yields a proposed `connection.rotate` Op from `/tasks/refresh-tokens`);
  assert `/tasks/refresh-tokens` is OIDC-guarded + in the bypass list.
- **Reviewer checklist:** ☐ rotation is a governed Op, never an out-of-band SM write ☐ one
  shared `refresh_oauth_token` primitive ☐ Scheduler jobs for all `/tasks/*` with OIDC ☐ old
  secret version retained; compensate works ☐ operator-token runbook covers zero-downtime
  ordering.
- **Risk:** depends on Phase 1; benefits from Phase 2. Hidden scope: there is no scheduler at
  all — creating it is the real prerequisite for any "scheduled" behavior.

### Phase 4 — Observability & alerts
**Goal.** Metrics for connector/OAuth/outbox/breaker events, alerts, and a connections-health
console panel. **See Part A amendment trigger #2** — resolve the §8 "no Prometheus" vs.
existing `/metrics` conflict in this PR (amend §8/§10, or use Sentry + Cloud Logging +
dashboard).

- **Backend:** add counters/gauges (new `app/metrics.py`, reusing the existing registry in
  `middleware.py`): `aos_connection_{connect,verify,rotate}_total{provider,result}`,
  `aos_oauth_callback_errors_total{provider,reason}` (defined now, used in Phase 5),
  `aos_outbox_dead_gauge`, `aos_circuit_breaker_trips_total{domain}` (increment in
  `loop.record_failure` on CLOSED→OPEN — confirm `loop.py` is not in the model-SDK CI grep
  scope; it isn't today), `aos_connection_verify_duration_seconds{provider}` histogram.
- **Alerts (`scripts/create_alert_policies.sh` + runbook; owner runs):** DLQ depth > 0 for
  15m; breaker trips > 0; OAuth callback error rate; per-provider verify failure rate;
  `/readyz` down. **Flag:** confirm a metrics collector scrapes `/metrics` in prod; if not,
  use log-based metrics.
- **Frontend:** a "Connections Health" dashboard panel — healthy/degraded/expiring counts
  (from `GET /connections`) + DLQ depth (from `/outbox/dead`).
- **Migration:** none.
- **Tests:** `test_metrics.py` (drive a connect + a verify-fail, then assert the counter
  strings appear in `GET /metrics` with correct labels); vitest panel render test.
- **Reviewer checklist:** ☐ §8/§10 amended (or sanctioned path used) ☐ metrics via existing
  registry ☐ no PII/secret/high-cardinality labels ☐ breaker metric fires exactly on
  CLOSED→OPEN ☐ alert policies scripted + reference the notification channel.
- **Risk:** depends on 1–3 for events worth counting; main risk is assuming a prod metrics
  collector exists — verify.

### Phase 5 — OAuth self-service ("Sign in with Google/Meta"), gated behind external setup
**Goal.** A governed start that builds a provider authorize URL with a signed, single-use,
short-TTL `state`; a **public** callback that validates state, exchanges code→tokens, stores
them in SM, and **proposes a governed connect Op** (never a direct write). Fully mockable in
CI. Models the §5.1 plugin-webhook pattern.

- **External prerequisites (owner, not the agent — document in this brief + the PR):**
  register a Google OAuth Web client + a Meta app with redirect URIs
  `…/oauth/{google,meta}/callback`, minimal per-connector scopes; store client id/secret in
  Secret Manager (`aos-oauth-google-client`, `aos-oauth-meta-client`); add
  `OAUTH_STATE_SECRET` (32B random) and `OAUTH_ALLOWED_REDIRECT_URIS` (exact-match allowlist).
- **Backend (`app/services/oauth.py` + `main.py`):** `sign_state`/`verify_state` via stdlib
  `hmac` (HMAC-SHA256 over `tenant_id|brand_id|provider|nonce|exp`, base64url — no new dep);
  `build_authorize_url`; `exchange_code` (reuses the httpx pattern, mocked under
  `AOS_ENV=test`). `POST /oauth/{provider}/start` (tenant/operator-authed) returns
  `{authorize_url}` with a **server-allowlisted** redirect_uri + minimal scopes.
  `GET /oauth/{provider}/callback` (**public** — add to `TenantIsolationMiddleware` bypass):
  `verify_state` → `exchange_code` → write tokens to SM → `set_config` (state's tenant_id) →
  `loop.propose` the existing per-provider `*.connect` Op (config carries
  `{refresh_token_ref, client_id, expires_at, scopes}`) → gate → commit → `enqueue_drain` →
  redirect browser back to the console.
- **Guardrails (spell out & test):** CSRF (HMAC-signed state bound to tenant/brand); replay
  (single-use nonce store + short exp); open-redirect (redirect_uri chosen server-side from
  the allowlist; final redirect a fixed console URL); scope minimization (per-provider
  constants, no wildcards); secret hygiene (tokens only in SM).
- **RLS note (sharp edge):** the public callback runs *before* tenant context exists, so it
  cannot use `tenant_context`-based RLS — use `get_worker_db` for the nonce-store read/write
  and SM write, then `set_config` explicitly before `propose` (exactly as §5.1 describes).
- **Migration:** new `oauth_states` table (single-use nonce store) — **RLS triple-touch**
  (see Part A) + add to the §3 RLS table list.
- **Mock the whole flow in CI** (`AOS_ENV=test`): deterministic authorize URL; canned tokens
  with no httpx; `SecretManagerClient` mocks via local JSON; conftest sets a test
  `OAUTH_STATE_SECRET`.
- **Tests (`test_oauth_flow.py`):** start→callback happy path proposes a connect Op + creates
  a Connection after drain; invalid/replayed/expired state rejected with generic errors (+
  error counter); redirect_uri not in allowlist rejected; callback uses the worker session
  for its own reads and `set_config`s before `propose`. Vitest: "Sign in with Google" posts to
  `/oauth/google/start` and navigates to the returned URL.
- **Reviewer checklist:** ☐ callback creates the connection ONLY via governed propose ☐ state
  HMAC-signed, single-use, short-TTL; forgery/replay/expiry rejected ☐ redirect_uri
  server-allowlisted ☐ scopes minimized + documented ☐ tokens only in SM ☐ `oauth_states` RLS
  triple-touch + §3 amended ☐ entire flow passes CI with no real provider calls.
- **Risk:** last; depends on Phase 3. Dark until the owner registers the apps — agent builds +
  tests behind the mock and ships.

---

## Cross-cutting (all phases)
- **`CONNECTORS.md` (new contributor doc — under `control-plane/` or `docs/`, not a new
  top-level dir).** End-to-end "add a connector": (1) connect action in the adapter using
  `credential`; (2) register a `*_connect` tool in `tools.py` (auto-discovered by the grid via
  the "connect" substring); (3) add a provider probe to the lifecycle probe registry;
  (4) add a `CONNECTOR_META` entry in `connections/page.tsx`; (5) OAuth: scopes + redirect-URI
  allowlist + external registration; (6) tests to mirror. Document the naming rule prominently.
- **Directory-naming invariant** — documented + tested in `test_connector_contract.py`
  (see Part A).
- **New CI invariant greps** (`.github/workflows/ci.yml`, "Invariant checks"): forbid
  interpolating credential/token values into `logger.*`/`print(...)` (`credential`,
  `raw_token`, `access_token`, `refresh_token`) — tuned to not flag the safe `secret_ref`
  pointer. Enforce "no secret in `preview_summary`/audit/config" via the contract test. Keep
  the existing model-SDK grep scoped to `services.py`/`optypes.py`.
- **Severity conventions:** connect = impact1 COMPENSATABLE (compensate = disconnect);
  verify = impact1 REVERSIBLE; rotate = impact1 COMPENSATABLE (compensate = restore prior ref);
  revoke = impact1 IRREVERSIBLE.

## Sequencing & dependencies
`0 (contract, blocks all)` → `1 (lifecycle + health)` → `3 (rotation + scheduler)` →
`4 (observability)` → `5 (OAuth)`. **`2 (Cloud Tasks)` is independent and may parallelize.**
Sharp edges to land atomically: Phase 2's `oidc_token` + SA env; Phase 3's "no scheduler
exists"; Phase 5's public-callback RLS story.

## Where existing code helps / hurts
- **Helps:** live verify checks already exist (Phase 1 relocates them); Cloud Tasks code + env
  already wired (Phase 2 ≈ "create the queue"); `_refresh_token` + httpx retry exist
  (Phase 3/5); §5.1 plugin-webhook is a ready template for the public OAuth callback
  (Phase 5); the Postgres RLS guardrail auto-covers new RLS tables (1/5); the Prometheus
  registry + `/metrics` are live (Phase 4).
- **Hurts:** `secret_ref` means two things across producer/consumer and is test-pinned
  (Phase 0); the Cloud Task lacks its `oidc_token` so enabling worker auth naïvely breaks the
  drain (Phase 2); there is no scheduler at all (Phase 3); the public OAuth callback can't use
  tenant-context RLS (Phase 5); §8 forbids Prometheus while the code already ships it (Phase 4).

## Critical files
- `control-plane/app/kernel/tools.py` — tool registry / connect handlers (all phases)
- `control-plane/app/adapters/{grow,presence,manage}.py` — connect pattern; lifecycle home (§6.3 Manage preferred)
- `control-plane/app/main.py` — endpoints, adapter registration, middleware bypass
- `control-plane/app/models.py` — `Connection` health columns; new `oauth_states`
- `control-plane/app/tasks.py` — Cloud Tasks `oidc_token` + debug-print cleanup
- `control-plane/app/services/{google_audit.py → oauth.py}` — refresh primitive
- `control-plane/web/src/app/(dashboard)/connections/page.tsx` — pills, verify/disconnect/rotate, OAuth buttons
- `control-plane/scripts/setup_worker_role.sql` + a new Alembic revision per schema phase (chain from `alembic heads`)
- `control-plane/scripts/{create_outbox_queue,create_schedulers,create_alert_policies}.sh` — new infra runbooks (owner runs)
- `.github/workflows/{ci,deploy}.yml` — new greps, env, smoke checks
- `ARCHITECTURE.md` — amend §1/§5/§6.3 (Phase 1), §8/§10 (Phase 4), §3 (Phases 1/5) in the same PR

## Global verification (every PR)
- Backend: `cd control-plane && python -m pytest` (asyncio_mode=auto; cov ≥ 60%; Postgres RLS
  test runs against CI postgres:16 and auto-covers new RLS tables).
- Frontend: `cd control-plane/web && npm run lint && npm test && npm run build`.
- Post-deploy smoke (`deploy.yml`): `/readyz` 200, CORS preflight on `/tenants`, unauthed
  `POST /tenants` → 401 (not 500). Phase 2 adds the optional `aos-outbox` existence check.
