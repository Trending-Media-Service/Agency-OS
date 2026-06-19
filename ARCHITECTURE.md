# Agency OS — Master Architecture

**Status:** Authoritative. This document supersedes and replaces `STAKEHOLDER_FEATURE_REQUIREMENTS.md`, `ENTERPRISE_ARCHITECTURE_REVIEW.md`, `INTEGRATION_ECOSYSTEM_GUIDE.md`, and `PLATFORM_INTEGRATION_GUIDE.md`. Where any other document in this repository conflicts with this one, this one wins. Delete or archive the others.

**Version:** 1.0 — June 2026
**Owner:** Chandan (solo founder/operator)
**Repo visibility:** This repository must be **private**. It names a design partner and contains governance thresholds and pricing-relevant architecture.

---

## 1. Thesis

Agency OS is a digital agency's delivery capability turned into an operating system. A brand expresses intent in plain language; governed agents provision, build, run, and grow its entire digital presence on GCP — with every action previewed, approved, audited, and reversible.

It is **one governance kernel with four adapter families**, not four products:

| Pillar | What it does | Adapter family |
|---|---|---|
| **Provision** | Host: domains, compute, DBs, email, certs on GCP | Terraform recipes |
| **Build** | Conversational dev agents ship web apps, automations, AI features | Agent harness + golden templates |
| **Manage** | Connect, observe, and operate existing client infrastructure | Read-then-write connectors |
| **Grow** | Trust-tiered autonomous ad operations (original Agency OS) | Ad-platform adapters |

Every operation in every pillar is the same primitive: a proposed **Op**, previewed, gated by deterministic policy, approved by a human (until autonomy is earned), executed, verified, and reversible via a defined compensating action.

**Positioning:** The competitor is not Lovable, Vercel, or an ad tool. It is the traditional agency without leverage. Buyers are brands who want outcomes, not tools; they never touch code or consoles. The moat is the governance trail plus full-stack visibility (a brand we host and build for gives Grow first-party data no standalone ad tool can match).

**North-star product metric:** median approval latency < 2 minutes from card delivery to decision. If approvals rot, the product dies regardless of intelligence.
  - **Latency measurement:** Measured in milliseconds as the duration between card delivery (traced via `whatsapp_card_sent` trace, falling back to the `AWAITING_APPROVAL` state transition timestamp if the card trace is missing) and the `Approval` commit time.
  - **Rollup Aggregation:** The control plane provides a tenant-scoped read-only aggregate endpoint (`/metrics/approval-latency`) computing count, median, p90, and count of expired cards within a selectable time window.

---

## 2. Non-negotiable invariants

These hold across all pillars, all tiers, all time:

1. **Deterministic gates only.** Safety boundaries (policy rules, spend caps, lockouts) are deterministic and explainable. ML/LLMs may rank, draft, prioritize, and explain — they never gate. A model's confidence is never grounds to bypass a rule.
2. **Statutory firewall.** Nothing touching GST, UAE VAT, or any statutory/tax/compliance obligation is auto-executed at any trust tier. These Ops always require explicit human approval, regardless of score.
3. **No silent writes.** Every state-changing operation against client property (infra, code, campaigns, data) flows through the action loop and lands in the audit log. There is no side door, including for the operator.
   *Bootstrap Exception:* The initial provisioning of the primary Tenant, Brand, and operator credentials during system installation, as well as database schema migrations, are exempt from the action loop. These are executed via privileged CLI scripts or Alembic, and are recorded in system application logs rather than the audit chain.
4. **Vendor-neutral core.** The kernel's `Op` type carries no platform vocabulary (no "campaign", "bid", "Cloud Run"). Domain vocabulary lives in adapters. (This fixes the previously flagged defect where ad-platform terms leaked into the universal contract.)
5. **Reversibility is declared, not assumed.** Every Op declares its compensation semantics up front: `REVERSIBLE` (exact undo exists), `COMPENSATABLE` (a defined compensating action restores intent, e.g. restore prior bid — spend already incurred is logged as irreversible delta), or `IRREVERSIBLE` (e.g. sent email, registered domain). Irreversible Ops face stricter gates.
6. **Cost attribution from day one.** Every tool call, token, API request, and GCP resource is tagged with `tenant_id`/`brand_id`. This is nearly free now and impossible to retrofit; it is also the pricing model's raw data.
7. **Single source of truth per fact.** Control-plane Postgres is the system of record for tenants, Ops, approvals, trust. Terraform state is the system of record for provisioned infrastructure. Analytics stores are derived, never authoritative.

---

## 3. Tenant & isolation model

**GCP-native isolation. GCP projects are the walls; we do not reinvent them with path strings or app-level checks alone.**

```
GCP Organization
└── Folder: agency-os-platform
    ├── Project: aos-control-plane        # the OS itself
    ├── Project: aos-shared-tier          # shared hosting for small brands
    └── Folder: tenants
        ├── Project: brand-ableys         # dedicated tier: one project per brand
        ├── Project: brand-tanmatra
        └── Project: brand-<slug>
```

- **Control plane** (`aos-control-plane`): FastAPI service(s) on Cloud Run, Cloud SQL Postgres (system of record), Cloud Tasks (queue), Secret Manager (platform secrets), Cloud Build (CI), Sentry + Cloud Logging.
- **Dedicated tier:** one GCP project per brand. Native billing isolation, IAM boundary, budget alerts, and credential blast-radius containment. A compromised brand service account structurally cannot see another brand's project. Brand-scoped third-party credentials (Shopify tokens, ad-platform creds) live in **that brand's** Secret Manager, not the control plane's.
- **Shared tier:** scale-to-zero Cloud Run services + per-tenant databases on a shared Cloud SQL instance (or Supabase/Neon for tiny tenants), inside `aos-shared-tier`. Exists because a dedicated project has a ~$30–60/month cost floor before traffic. Brands graduate to dedicated at a defined revenue/usage threshold. **The two tiers are the hosting price list.**
- **Control-plane data isolation:** every table containing tenant-scoped data carries a `tenant_id` column with Postgres Row-Level Security (RLS) enabled and forced.
  - The following tables are subject to RLS policy: `brands`, `ops`, `audit_events`, `trust_events`, `trust_snapshots`, `cost_ledger`, `connections`, `brand_properties`, `cadences`, `op_traces`, `approvals`, `orders`, `order_lines`, `refunds`, `fulfillment_costs`, `campaigns`, `spend_facts`, `touchpoints`, `circuit_breakers`, `op_dependencies`, `outbox`, `policy_versions`, `shadow_decisions`, `consent_bases`.
  - Every session transaction sets the session configuration `app.current_tenant_id` via middleware before executing queries. If no tenant context is set, the session is isolated and denied read/write access to all rows. App-level checks are defense-in-depth on top of project isolation, not a substitute for it.
- **Service accounts:** per-brand, minimally scoped, short-lived tokens where the platform supports them. No standing org-wide credentials.
- **Worker Role RLS Bypass:** The background outbox worker (`loop.py`) runs in a privileged system context and uses `get_worker_db()` to bypass Postgres RLS. This is necessary because the worker must poll the global `outbox` table and coordinate operations across multiple tenants. However, the worker is strictly a scheduling and routing kernel. When it executes a tenant-specific adapter operation, the session context dynamically sets the active `app.current_tenant_id` for that transaction. This ensures that any queries executed by the adapter (or by verification checks) are strictly bounded to that tenant's RLS workspace, maintaining deep isolation during execution.

---

## 4. Governance kernel

### 4.1 The governed action loop

Every state-changing operation is an **Op** moving through a fixed state machine:

```
PROPOSED → PREVIEWED → AWAITING_APPROVAL → APPROVED → EXECUTING → VERIFYING → DONE
                │              │                          │            │
                │              ├→ REJECTED                ├→ FAILED → COMPENSATING → ROLLED_BACK
                │              ├→ MODIFIED (A2UI) ──→ re-enters PREVIEWED
                │              └→ EXPIRED (TTL)           │
                └→ BLOCKED (policy gate)                  └→ PARTIAL → needs operator
```

- **Plan:** intent (from chat, schedule, or webhook) decomposes into one or more Ops with declared inputs, cost estimate, severity, and compensation semantics.
- **Preview:** a human-readable diff of intended change. For Provision this is literally `terraform plan` output, summarized. For Build it is a staging URL. For Grow it is the before/after of the bid/budget/campaign. No Op reaches approval without a preview artifact.
- **Approve:** delivered to the right approver on their surface (WhatsApp first-class, web queue second). Tier 2 Ops within policy auto-approve; everything else waits. Approval records user, role, surface, latency, and free-text reason if rejected/modified.
- **A2UI modification:** the approver may reply in natural language ("make it ₹40,000 and run it"). The Op is re-planned with the new parameter, re-previewed, re-gated, and re-presented. Modification never skips gates.
- **Execute:** via the owning adapter, through the outbox (below). Idempotency key per Op; executors must be safe to retry.
- **Verify:** adapter-defined post-conditions (HTTP 200 on the new site, bid value read back equals written value, Terraform state matches plan). Verification failure triggers compensation, not silence.
- **Rollback/Compensate:** per the Op's declared semantics. All compensations are themselves Ops and are audited.

### 4.2 Reliability (saga-lite)

No Kafka, no Temporal. At this scale:

- **Outbox table:** Op execution requests are written transactionally with the state change, then drained by a Cloud Tasks worker. No dual-write inconsistency.
- **Multi-step Ops (Sagas):** Executed as an ordered list of child Ops. Sagas can be sequenced linearly using `OpRow.sequence_order` or as a Directed Acyclic Graph (DAG) using the `OpDependency` table (edges mapping parent, from, and to Op IDs).
  - **Forward execution:** A child node becomes runnable and is enqueued when all its upstream dependency nodes have transitioned to `DONE`.
  - **Rollback cascade:** On failure of any node, all running or unexecuted siblings are cancelled, and the transitive set of successfully completed (`DONE`) nodes is compensated in reverse topological order.
- **Idempotency:** every external call carries the Op's idempotency key; retries with exponential backoff; poison Ops park in `PARTIAL` for the operator.


### 4.3 Policy gates

OPA-style deterministic rules, versioned in the repo, evaluated at Preview and re-evaluated at Execute (state may have changed in between):

- **Ruleset Parameterization:** Rule validation thresholds are parameterized via the `RulesetParams` dataclass. The ruleset can be dynamically initialized using parameters stored in control-plane database tables (`policy_versions`), allowing for versioned, dynamic, and replayable policy checks.
- **DEFAULT_RULES:** Initialized with default `RulesetParams` corresponding to historical limits:
  - `provision_cost_ceiling_minor` = 1,000,000 minor units (10,000.00 INR/month)
  - `grow_bid_cap_minor` = 100,000 minor units (1,000.00 INR per adjustment)
  - `grow_budget_transfer_cap_minor` = 5,000,000 minor units (50,000.00 INR per transfer)
  - `statutory_refund_limit_minor` = 1,000,000 minor units (10,000.00 INR per refund)
  - `allowed_regions` = `("asia-south1",)`
  - `approved_dependencies` = `("react", "react-dom", "next", "tailwindcss", "lucide-react")`
  - `protected_paths` = `("control-plane/", ".github/", "recipes/", "OWNERS", "METADATA")`
- Per-domain rule packs (Provision: cost ceilings, region allowlist; Build: protected paths, dependency allowlist; Manage: write-scope limits; Grow: bid caps, budget-transfer caps, multiplier limits).
- Every rejection produces a structured explanation: rule id, limit, attempted value, delta. This renders in the UI/WhatsApp verbatim — no generic errors.
- Rule changes are themselves Ops (governed, audited).
- **Policy Simulation (Backtesting):** Before applying a policy parameter change, operators can backtest proposed parameters via `POST /policy-simulate`. The simulation replays historical operations (e.g. over the last 30 days) against the baseline and proposed rulesets, bucketing differences into `newly_blocked`, `newly_allowed`, `newly_auto_approved`, and `now_requires_human` without modifying any execution states or the outbox.
- **Severity model (two-factor):** `severity = f(impact, reversibility)`. Impact is domain-scaled (₹ at stake, blast radius); reversibility from the Op declaration. Severity selects the approval requirement, not the model's opinion.

### 4.4 Trust engine

Trust is per-brand-per-domain (a brand can be Tier 2 in Grow and Tier 0 in Build).

**Tiers (canonical — the 80.00 threshold in older docs is wrong):**

| Tier | Score | Behavior |
|---|---|---|
| 0 — Lockout | < 60 | All state-changing Ops blocked; diagnose-and-remediate cards only |
| 1 — Supervised | 60–84 | Every Op requires human approval |
| 2 — Earned autonomy | ≥ 85 | Ops auto-approve **iff** within policy gates and below severity ceiling; statutory firewall always applies |

**Score = static health + dynamic history, clamped to [0, 100]:**

```
S = clamp( S_health − P_signals + S_history , 0, 100 )
```

- `S_health` — integration health, weighted: GTM presence, pixel presence, CAPI dedup rate, etc. Weights sum to the baseline maximum (e.g. 70).
- `P_signals` — penalties from negative signals. **Counts must saturate** (this fixes the unbounded-subtraction defect): for a count `M` with sensitivity `τ` and cap `p_max`,
  `P = p_max · (1 − e^(−M/τ))`
  so 5 GMC mismatches and 50 are distinguishable but neither nukes the score to −∞.
- `S_history` — dynamic component (max e.g. 30) earned from outcomes: verified successful Ops add; human overrides/rejections and verification failures subtract; **all events decay exponentially** (half-life ~30–60 days, tune per domain) so the score reflects recent behavior, not ancient history. Every human override reason is logged — that log *is* this component's training data.
- All weights, caps, τ, and half-lives live in versioned config, with worked examples in tests. No magic numbers in code, no fabricated-precision examples in docs.
- **Autonomy Confidence (Shadow Mode):** To safely evaluate potential promotions to Tier 2, human decisions (Tier 1) are audited against what the system *would* have done under shadow Tier-2 logic. If a human rejects an operation that shadow mode would have auto-approved, it is flagged as a critical disagreement (indicating unsafe auto-approval risk). This shadow evaluation is strictly advisory and does not affect operation execution.
- **Advisory Brand Performance Score (B):** Separate from the safety-critical `trust_score` (S), the system exposes a composite performance score `B = w1*UX + w2*Organic + w3*Paid + w4*PR` representing overall channel execution quality.
  - **Non-Gating Invariant:** The score `B` is strictly advisory. It **must never gate** execution, nor should it ever appear inside the path of `approval_requirement` or `evaluate_gates` checks. Altering weights or score values leaves all Op decision records byte-identical.
  - **Read-Only:** The computation is entirely read-only and has no side effects on the database state or audit records.

### 4.5 Record layer

- **Audit log:** append-only `audit_events` table; each row stores the SHA-256 of the previous row (tamper-evident chain). Actor, role, surface, Op id, before/after refs, timestamp. Nothing is ever updated or deleted.
- **Execution traces:** every Op accumulates a trace — each gate evaluated, each adapter call, each retry, with reasons. "Why was this rejected/approved/slow" is a query, not an investigation.
- **Cost ledger:** per-Op and per-tenant rollups of tokens, API calls, and GCP spend (label-based export from billing). Feeds pricing and the per-card cost estimate shown at approval time.
- **Shadow decisions log:** advisory records in the `shadow_decisions` table storing the counterfactual Tier-2 evaluation details (shadow tier, shadow requirement, agreement status, rule violations). Unlike the main audit log, shadow decisions are for performance analysis and are not hash-chained or authoritative.

### 4.6 Approval surfaces

- **WhatsApp (primary):** card = summary, preview link, cost, severity, and reply affordances (approve / reject / natural-language modify). This market approves on WhatsApp, not in dashboards or Slack.
- **Web queue (secondary):** full preview rendering, payload diffs (never raw JSON), trace viewer, history.
- **Autonomy Confidence Metrics:** `GET /autonomy-confidence` calculates the counterfactual agreement rate, critical disagreements, and recommendation (PROCEED, HOLD, OBSERVE) to guide operators prior to promoting a domain to Tier 2. Promotion decisions remain manual and score-based; metrics are advisory.
- **Role-Authority Matrix:** Every human approval is validated against a deterministic authority matrix configured inside the versioned tenant ruleset (`RulesetParams`):
  - **AGENCY_OWNER:** Full authority. May approve all domains, overrides, irreversible actions, and statutory operations up to 1,000,000 INR.
  - **OPERATOR:** Standard operations. May approve all domains, overrides, and irreversible actions up to 50,000 INR; may *never* approve statutory operations.
  - **BRAND_VIEWER:** Read-only reviewer. May only approve `grow` actions with severity impact 1 and zero cost.
  - **CLIENT:** Bounded additive actor. May approve `grow` actions with severity impact <= 2 and cost up to 10,000 INR. May *never* approve statutory operations, override gates, or approve irreversible actions.
- **Role-Aware Rejections:** Approvals by roles lacking authority are rejected deterministically with clear explanation messages (e.g., `"OPERATOR cannot approve statutory Ops"`) and logged to the audit and trace layers.
- **Cards carry a TTL:** expiry is logged and surfaces as a latency problem, not silently dropped.

---

## 5. Adapter contract (universal)

Every pillar implements the same interface. The kernel knows nothing about domains.

```python
class Adapter(Protocol):
    domain: str                                   # "provision" | "build" | "manage" | "grow"

    def plan(self, intent: Intent, ctx: TenantCtx) -> list[Op]: ...
    def preview(self, op: Op) -> PreviewArtifact: ...          # tf plan, staging URL, diff
    def execute(self, op: Op, idem_key: str) -> ExecResult: ...
    def verify(self, op: Op) -> VerifyResult: ...              # adapter-defined post-conditions
    def compensate(self, op: Op) -> list[Op]: ...              # per declared semantics

@dataclass(frozen=True)
class Op:                       # vendor-neutral — NO platform vocabulary here
    id: str
    tenant_id: str
    brand_id: str
    domain: str
    action: str                 # adapter-namespaced, e.g. "provision.dns_zone.create"
    params: dict                # schema owned and validated by the adapter
    cost_estimate: Money | None
    severity: Severity          # impact x reversibility
    reversibility: Literal["REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE"]
    parent_op_id: str | None    # for multi-step recipes
```

Third-party connectivity standardizes on **MCP** where servers exist (Shopify's MCP suite is the first target); plain REST adapters elsewhere. Quoted rate limits in any doc are advisory only — adapters read current platform documentation and enforce their own client-side limiter + circuit breaker.

### 5.1 Plugin webhooks and routers
For event-driven third-party triggers (such as Shopify `orders/create`), the control plane exposes a generic, RLS-bypassed endpoint `/webhooks/plugins/{provider}`. 
- **Plugin Protocol:** Every third-party platform registers a `Plugin` helper detailing:
  - `verify_signature(raw_body, signature, secret)`: Custom platform-specific cryptographical validation (e.g. HMAC-SHA256).
  - `resolve_connection_identifier(headers, payload)`: Extracts the platform identifier (e.g. shopify store URL).
  - `translate_webhook(event_type, payload, tenant, brand)`: Maps events to vendor-neutral `OpSpec` objects (e.g. `manage.shopify.sync_order`).
- **Isolation and Scope Validation:**
  - The webhook router queries the global `connections` table bypassing RLS using a privileged database session to match the provider and connection identifier, resolving the correct `tenant_id` and `brand_id`.
  - Signature validation is strictly completed using the stored `secret_ref`. If validation fails, or if no connection matches, a `401 Unauthorized` or `404 Not Found` is returned.
  - Upon successful verification, the router sets the active `tenant_context` context variable and writes proposed Ops to the database, ensuring all downstream policy evaluation and auditing executes safely within that tenant's RLS isolation boundary.

---

## 6. Pillar specifications

### 6.1 Provision — "cPanel on GCP", except the chat is the panel

**Mechanism:** every provisioning request compiles to a **recipe** — a versioned Terraform module plus metadata. `terraform plan` IS the Preview artifact; `apply` is Execute; state is Verify; targeted destroy/revert is Compensate. The governance loop and IaC are the same shape; we wrap Terraform, we do not build a provisioning engine.

**Recipe format (the platform's core asset — every new recipe is sellable to every tenant):**

```
recipes/<name>/<version>/
├── recipe.yaml        # inputs schema, outputs, monthly cost estimate, tier (shared|dedicated),
│                      # severity, reversibility map per resource, policy pack refs
├── main.tf            # the module
├── checks.py          # post-apply verification (DNS resolves, cert issued, 200 on /)
└── RUNBOOK.md         # failure modes + manual remediation
```

**Launch recipe set (v1):**

1. `brand-baseline` — GCP project (or shared-tier slot), budget alert, logging, service account
2. `web-host` — Cloud Run service + Cloud DNS zone + managed SSL + domain connect/registration
3. `static-host` — Firebase Hosting / GCS+CDN variant
4. `postgres-db` — Cloud SQL database (shared instance) or dedicated instance
5. `email-dns` — SPF/DKIM/DMARC records + Workspace/Zoho provisioning hooks
6. OSS installs (see Manage): `cms-directus`, `automation-n8n`, `crm-twenty` — each a recipe

**Example flow — "Hey! host newbrand.com":** intent → `brand-baseline` + `web-host` + `email-dns` planned as child Ops → WhatsApp card: plan summary + ₹/month estimate → approve → apply → checks pass → "newbrand.com is live" with status link.

**Explicit non-goals:** no graphical cPanel clone (chat + a read-only per-brand status dashboard only — deployed services, cost, health); no multi-cloud (GCP only; AWS appears solely as a Manage-pillar connect target).

### 6.2 Build — governed delivery, not raw generation

**Mechanism:** wrap an agentic coding harness (Gemini Code Assist / Vertex AI) in the action loop. We do not build an LLM coding product. Per brand: a repo, CI via Cloud Build, deploy targets from Provision. The agent works only inside **golden templates** — opinionated, pre-QA'd stacks where output quality is reliable and the review checklist is fixed.

**Golden templates (v1):** Next.js storefront on headless Shopify; brand/marketing site; internal dashboard app. Add templates only after the second time the same custom build repeats.

**The Build loop:** conversational request → agent produces a branch + **staging preview URL** (this is the Preview artifact) → policy gates (protected paths, dependency allowlist, secret-leak scan) → approval card: "New PDP design on staging — approve to ship" → merge + deploy → verify (smoke checks) → instant rollback = previous revision (Cloud Run revisions make this nearly free).

**Capability honesty:**
- Now: web apps, storefronts, landing pages on golden templates.
- Near (same harness, different output): workflow automations (n8n / Cloud Workflows configs), RAG chatbots and brand-tailored AI features, "machine intelligence in existing processes" — all deployed as Provision recipes.
- Deferred hard: **native mobile apps.** PWA/Expo from the web codebase covers ~80% of demand. Native iOS/Android is the single scope item most capable of sinking a solo operation. Revisit at 10 paying tenants.

### 6.3 Manage — connect existing infrastructure

This pillar absorbs the conversational backup-platform work. Targets: Shopify stores and custom GCP/AWS headless apps (current client base).

**Graduated access (the trust ledger applied to infra):**
1. **Sense (read-only, weeks):** brand grants scoped read credentials into *their* project's Secret Manager. The system inventories, monitors, and reports. Zero write capability exists in this phase — not "unused", *absent*.
2. **Continuity:** the system can redeploy the brand's stack from recipes if the primary dies. This resolves the earlier open question (hot failover vs. business continuity vs. request-level fallback) in favor of **business continuity first** — cheapest to build, easiest to sell; hot failover deferred.
3. **Operate:** write Ops unlock tier-by-tier through the action loop like everything else.

**State drift control:** Manage never maintains a parallel writable copy of client state. It reads, snapshots (versioned, point-in-time), and acts on the primary through Ops. Snapshots are recovery material, not a second source of truth.

**The "all-in-one" answer — managed OSS, not built-from-scratch:** CMS (Directus/Strapi), CRM (Twenty/EspoCRM), automation (n8n), ERP (ERPNext, only on explicit demand) are deployed into the brand's own project as Provision recipes — the governed equivalent of cPanel one-click installs. We own operations and upgrades (each upgrade is an Op); we do not own the roadmap of a CRM.

### 6.4 Grow — trust-tiered ad operations (original Agency OS)

Unchanged from the refined plan; now expressed as the fourth adapter family. Card types: `BID_ADJUSTMENT`, `BUDGET_REALLOCATION`, `PAUSE_CAMPAIGN`, `ALERT_DISPATCH` — all four generated and rendered, none hidden. Policy pack: bid cap, ≤2x multiplier, budget-transfer cap, with structured-explanation rejections. Batch sweeps are a **feature** (predictable, reviewable decision windows); continuous webhook-driven autonomy is earned later, not apologized for now.

**iPOAS + Causal Calibration (α):**
Attributed contribution margin reporting is calibrated using a causal-calibration multiplier: `iPOAS = POAS_attributed · α`, where `α = iROAS / AttrROAS` is computed offline/batch from geo-experiment history and ledger data.
- **Offline Separation Invariant:** The statistical/MMM calibration compute engine (`google-meridian`) runs exclusively in a background scheduler cadence. It is strictly prohibited from running inside a request path or any deterministic policy gate.
- **Governed Proposal Loop:** Adjustments to campaign bids and budgets driven by the causal multiplier are planned as `grow.bid.adjust` or `grow.budget.reallocate` Ops. They pass through the standard kernel state machine and are evaluated by the deterministic policy gates (e.g., bid limits, transfer caps, region locks) before execution.


**Immediate Grow backlog (Phase 0 — verify each item against actual source before building):**
- [ ] Confirm `calculate_dynamic_ats()` exists and wire it in (or build it per §4.4)
- [ ] Generate + render all 4 card types
- [ ] OPA rejections rendered as rule/limit/delta, in UI and WhatsApp
- [ ] Role-aware rejection messages
- [ ] Cold-start badge (missing COGS / tags)
- [ ] Payload diffs instead of raw JSON
- [ ] Dispatch log (which platform URLs were called, with what)
- [ ] Replace in-memory state with control-plane Postgres
- [ ] One real execution path (Shopify or Google Ads — whichever Ableys needs first), dry-run mode included

**Differentiator note:** a brand on Provision+Build gives Grow clean first-party data (server-side tagging, CAPI from our own stack). Full-stack tenants should see measurably better Grow outcomes; instrument this from the start — it is the cross-sell argument.

### 6.5 Presence — read-only SEO and competitor citation audit

**Mechanism:** reads and audits the brand's visibility and citations across Google AI Overviews and competitor landing pages using automated web crawling (`playwright` headless Chromium).
- **Read-Only Sense Invariant:** The presence audit adapter is strictly read-only. It generates local findings (`BrandProperty.findings` with `type="citation_audit"`) and surfaces content gap reports on the operator dashboard. It is strictly prohibited from proposing state-changing operations against client ad accounts, domains, or storefront configurations (§2.3).
- **Graceful Failure Fallback:** If a crawl times out, is blocked by anti-scraping measures, or fails due to missing OS-level browser binaries, the execution logs a retry/warning, updates findings to empty lists, and completes successfully without throwing a fatal crash or creating write operations.
- **RLS Safety Scoping:** Competitor domains and audit results are strictly scoped to the active tenant's Postgres RLS workspace context to prevent cross-tenant search intelligence leaks.

---

## 7. Conversational interface

The front door for all pillars. Intent parsing → adapter `plan()` → cards. Three hard rules:

1. The interface **never executes**; it only proposes Ops. All authority lives in the kernel.
2. Ambiguity resolves by asking, not assuming (an Op with wrong params that passes gates is still wrong).
3. Every generated plan shows its cost estimate before approval.

### 7.1 Tool Registry and Execution Gate
For conversational interactions with agentic workflows (e.g. Gemini tool calling), the interface standardizes tool execution on the `ToolRegistry` ([tools.py](file:///google/src/cloud/chandansinghr/AgecyOSV1/sandbox/Agency-OS/control-plane/app/kernel/tools.py)).
- **Action Decoupling:** Any tool call parsed from natural language (such as `grow_bid_adjust`) is routed directly to its corresponding tool handler. 
- **Propose-Only Boundary:** The handler does not execute the action. It merely returns a vendor-neutral `OpSpec` object (pre-configured with appropriate severity and impact details).
- **Mandatory Gating:** The `/chat` endpoint accepts the returned `OpSpec` and passes it through the standard `loop.propose` and `loop.preview_and_gate` pipelines. The tool execution path can only transition an Op to `PROPOSED` and then to `AWAITING_APPROVAL` or `BLOCKED` (or `APPROVED` if trust snapshot metrics qualify it for auto-approval); it cannot bypass safety gates or force immediate execution.

Surfaces: WhatsApp (approvals + simple intents), web chat (rich intents + previews). The A2UI modify-loop (§4.1) applies uniformly: "change the hero to teal and redeploy", "make it ₹40k", "use the .in domain instead".

---

## 8. Tech stack (boring on purpose)

| Layer | Choice | Note |
|---|---|---|
| API / workers | FastAPI on Cloud Run | One service to start; split only when forced |
| System of record | Cloud SQL Postgres + RLS | No TimescaleDB/Kafka/Temporal at this scale |
| Queue | Cloud Tasks | Drains the outbox |
| IaC | Terraform (recipes) + small state-orchestration layer | State in GCS, locked |
| CI/CD | Cloud Build | Per-brand triggers |
| Secrets | Secret Manager (per-brand in brand projects) | |
| Observability | Sentry + structured logs to Cloud Logging + Prometheus client (/metrics endpoint) | No ELK/Jaeger/Prometheus stack (monitoring is lightweight and client-pulled) |
| Backups | Nightly pg_dump → GCS (multi-region bucket) + Terraform state versioning | This IS the DR plan; monthly restore test |
| Frontend | Next.js + shadcn/Tailwind on Firebase Hosting/Cloud Run | The one place defaults win |
| Frontend | Next.js + shadcn/Tailwind on Firebase Hosting/Cloud Run | The one place defaults win |
| LLM | Vertex AI Gemini API (agents, parsing, explanations) | Never gates (§2.1) |
| WhatsApp | Meta Cloud API | Template messages for cards |
| Database Migrations | alembic | Async schema migrations, preserving Postgres RLS policies |
| Attribution Calibration | google-meridian | Offline Bayesian MMM causal calibration (α) scope only |
| Browser Crawl / Audit | playwright | Headless Chromium, read-only citation/competitor audit scope |


**Core tables (control plane):** `tenants`, `brands`, `ops`, `op_traces`, `approvals`, `audit_events` (hash-chained), `trust_events`, `trust_snapshots`, `cost_ledger`, `recipes`, `outbox`, `policy_versions`, `connections`, `shadow_decisions`, `consent_bases` (Manage credentials metadata — secrets themselves stay in brand-project Secret Manager).
- **policy_versions table:** Dynamic parameter records with columns `tenant_id`, `version`, `status` (active|proposed|superseded), `params` (JSON RulesetParams), `note`, `created_by`, and timestamps. Proposed policy revisions are saved as `proposed` records during simulation, but only `active` status records are loaded by the active ruleset evaluator.

---

## 9. Roadmap — vertical slices, each ends with a real brand getting real value

**Slice 1 — Kernel + Provision (~6–8 weeks).**
Build: tenant model + RLS, Op state machine + outbox, policy gate v1, audit chain, cost ledger, WhatsApp approval cards, recipes 1–2 (`brand-baseline`, `web-host`).
First tenant: **Tanmatra/Wok-Tok** (owned dogfood client). Second: **Ableys**.
*Exit criteria:* "host <domain>" spoken in chat results in a live site via an approved Terraform plan; the full trace and cost are queryable; approval happened on WhatsApp in under 2 minutes.

**Slice 2 — Build (~6–8 weeks).**
Build: agent harness on one golden template, staging-preview cards, protected-path gates, deploy + revision rollback.
*Exit criteria:* one real client request goes intent → staging URL → approval → production, with rollback demonstrated. Productize only what repeated.

**Slice 3 — Manage (~4–6 weeks).**
Build: read-only connect for one existing client (Shopify first — MCP), inventory + status dashboard, first OSS recipe install (n8n or Directus), snapshot/continuity drill.
*Exit criteria:* an existing client's stack is visible, snapshotted, and provably redeployable; first write Op executed at Tier 1.

**Slice 4 — Grow (~4–6 weeks).**
Execute the Phase 0 backlog (§6.4), then dynamic trust scoring per §4.4 and the A2UI tweak loop on Grow cards.
*Exit criteria:* a real bid/budget change executes against a live platform for Ableys with dry-run, trace, and rollback; trust score moves on real outcomes.

Slices 2–4 can reorder based on client pull. Slice 1 cannot — everything stands on it.

---

## 10. Deferred — revisit at 10 paying tenants (not before)

Native mobile apps · graphical control panel · Kafka/event sourcing/CQRS · Temporal · multi-region active-active DB · hot failover · service mesh · SOC 2 program (keep audit hygiene now, certify later) · competitive cross-tenant benchmarking (also a consent/data-governance question) · self-healing auto-remediation that writes to client property (currently violates §2.3 by definition) · plugin/SDK developer ecosystem · ML forecasting of trust/ROI (needs months of executed-Op history that does not yet exist) · predictive tier-degradation alerts (same reason).

Items that look deferred but are actually cheap and IN scope now: execution traces, cost attribution, override-reason logging, LLM-written root-cause explanations over the trace/event log (read-only, no remediation writes).

---

## 11. Open questions (tracked, not blocking Slice 1)

1. Shared-tier database choice: shared Cloud SQL instance vs. Supabase/Neon for tiny tenants — decide on cost floor + ops burden during Slice 1.
2. Domain registration: resell via Cloud Domains vs. instruct-and-delegate from the brand's existing registrar — likely both, recipe handles either.
3. WhatsApp template approval lead time (Meta review) — start the template submissions in week 1 of Slice 1.
4. Trust-score weights/τ/half-life initial values — set provisional values in config with worked-example tests; tune on Ableys data.
5. Build-agent harness selection and sandboxing model — evaluate during Slice 2 planning, not before.

## 12. Document hygiene rules

- One roadmap. It lives in §9. Any other roadmap found in this repo is stale — delete it.
- No fabricated precision: no example scores, costs, or dates that were not computed from the versioned config or real billing data.
- Architecture changes are PRs to this file. If the code and this file disagree for more than a week, that is an incident, not a footnote.
