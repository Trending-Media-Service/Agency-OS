# Agency OS — Master Architecture

**Status:** Authoritative. This document supersedes and replaces `STAKEHOLDER_FEATURE_REQUIREMENTS.md`, `ENTERPRISE_ARCHITECTURE_REVIEW.md`, `INTEGRATION_ECOSYSTEM_GUIDE.md`, and `PLATFORM_INTEGRATION_GUIDE.md`. Where any other document in this repository conflicts with this one, this one wins. Delete or archive the others.

**Version:** 1.0 — June 2026
**Owner:** Chandan (solo founder/operator)
**Repo visibility:** This repository must be **private**. It names a design partner and contains governance thresholds and pricing-relevant architecture.

---

## 1. Thesis

Agency OS is a digital agency's delivery capability turned into an operating system. A brand expresses intent in plain language; governed agents provision, build, run, and grow a brand's entire paid and organic digital presence — over a canonical brand model, on recurring cadences, with every action previewed, approved, audited, and reversible.

It is **one governance kernel with four adapter families supported by three connective layers**:

### Core Pillars

| Pillar | What it does | Adapter family |
|---|---|---|
| **Provision** | Host: domains, compute, DBs, email, certs on GCP | Terraform recipes |
| **Build** | Conversational dev agents ship web apps, automations, AI features | Agent harness + golden templates |
| **Manage** | Connect, observe, and operate existing client infrastructure | Read-then-write connectors |
| **Grow** | Trust-tiered autonomous ad operations (original Agency OS) | Ad-platform adapters |

### Supporting Layers (Connective Tissue)

| Layer | Role | Relationship to the four pillars |
|---|---|---|
| **Brand Graph (§6.5)** | Canonical model of what a brand consists of + health | The object every pillar reads and writes findings into |
| **Presence (§6.6)** | Organic & owned-channel audit-and-improve | A peer adapter family to Grow (organic : paid) |
| **Cadences (§13)** | Recurring responsibility → governed Op generator | Drives all four pillars on a schedule, executes nothing itself |

Every operation in every pillar is the same primitive: a proposed **Op**, previewed, gated by deterministic policy, approved by a human (until autonomy is earned), executed, verified, and reversible via a defined compensating action.

**Positioning:** The competitor is not Lovable, Vercel, or an ad tool. It is the traditional agency without leverage. Buyers are brands who want outcomes, not tools; they never touch code or consoles. The moat is the governance trail plus full-stack visibility (a brand we host and build for gives Grow first-party data no standalone ad tool can match).

**North-star product metric:** median approval latency < 2 minutes from card delivery to decision. If approvals rot, the product dies regardless of intelligence.

---

## 2. Non-negotiable invariants

These hold across all pillars, all tiers, all time:

1. **Deterministic gates only.** Safety boundaries (policy rules, spend caps, lockouts) are deterministic and explainable. ML/LLMs may rank, draft, prioritize, and explain — they never gate. A model's confidence is never grounds to bypass a rule.
2. **Statutory firewall.** Nothing touching GST, UAE VAT, or any statutory/tax/compliance obligation is auto-executed at any trust tier. These Ops always require explicit human approval, regardless of score.
3. **No silent writes.** Every state-changing operation against client property (infra, code, campaigns, data) flows through the action loop and lands in the audit log. There is no side door, including for the operator.
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
- **Control-plane data isolation:** every table carries `tenant_id`; Postgres row-level security enforced; every request passes tenant-assertion middleware. App-level checks are defense-in-depth on top of project isolation, not a substitute for it.
- **Service accounts:** per-brand, minimally scoped, short-lived tokens where the platform supports them. No standing org-wide credentials.
- **Verification Trust Boundary (`checks.py`):** The post-apply verification phase executes `checks.py` scripts packaged with Terraform recipes. Because these scripts execute arbitrary Python code and perform network queries (HTTP/DNS smoke tests) from the background worker context (outbox drain), they represent an external execution boundary. All recipe files, specifically `checks.py`, must be audited and treated as trusted core codebase components. Never load or run recipes from untrusted third parties.

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
- **Idempotency:** every external call carries the Op's idempotency key; retries with exponential backoff; poison Ops park in `PARTIAL` for the operator.
- **Multi-step Ops** (e.g. a provisioning recipe) are an ordered list of child Ops; failure mid-sequence runs compensations in reverse order for completed steps.

### 4.3 Policy gates

OPA-style deterministic rules, versioned in the repo, evaluated at Preview and re-evaluated at Execute (state may have changed in between):

- Per-domain rule packs (Provision: cost ceilings, region allowlist; Build: protected paths, dependency allowlist; Manage: write-scope limits; Grow: bid caps, budget-transfer caps, multiplier limits).
- Every rejection produces a structured explanation: rule id, limit, attempted value, delta. This renders in the UI/WhatsApp verbatim — no generic errors.
- Rule changes are themselves Ops (governed, audited).
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

### 4.5 Record layer

- **Audit log:** append-only `audit_events` table; each row stores the SHA-256 of the previous row (tamper-evident chain). Actor, role, surface, Op id, before/after refs, timestamp. Nothing is ever updated or deleted.
- **Execution traces:** every Op accumulates a trace — each gate evaluated, each adapter call, each retry, with reasons. "Why was this rejected/approved/slow" is a query, not an investigation.
- **Cost ledger:** per-Op and per-tenant rollups of tokens, API calls, and GCP spend (label-based export from billing). Feeds pricing and the per-card cost estimate shown at approval time.

### 4.6 Approval surfaces

- **WhatsApp (primary):** card = summary, preview link, cost, severity, and reply affordances (approve / reject / natural-language modify). This market approves on WhatsApp, not in dashboards or Slack.
- **Web queue (secondary):** full preview rendering, payload diffs (never raw JSON), trace viewer, history.
- Role matrix: rejections explain *why this role cannot approve this Op*, explicitly.
- Cards carry a TTL; expiry is logged and surfaces as a latency problem, not silently dropped.

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

**Mechanism:** wrap an agentic coding harness (Claude Code class) in the action loop. We do not build an LLM coding product. Per brand: a repo, CI via Cloud Build, deploy targets from Provision. The agent works only inside **golden templates** — opinionated, pre-QA'd stacks where output quality is reliable and the review checklist is fixed.

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

### 6.5 The Brand Graph — what a brand *is* (the systematized SOP)

**Problem this solves:** onboarding a brand (Tanmatra.food) is chaos because there is no canonical object representing the brand. Its existence is scattered across a registrar (GoDaddy), hosting (GCP), analytics, Merchant Center, an ad stack, an email tool, a WhatsApp number, a catalog, brand assets. Nobody — human or system — can answer "what does this brand consist of, and what condition is each piece in."

**The model.** A `brand` is not a name + tenant row. It owns a **Brand Graph**: a set of typed **Properties**, each a connected account or asset with a health state.

```
Brand
└── Properties (typed nodes)
    ├── domain         (registrar, expiry, DNS authority)        e.g. GoDaddy
    ├── hosting        (where the site runs)                     e.g. GCP / external
    ├── analytics      (GA4 / GTM / pixel / CAPI)
    ├── merchant_feed  (Google Merchant Center)
    ├── search_console (GSC property + verification)
    ├── ads_account    (Google / Meta / Amazon)                  one per platform
    ├── email          (provider, domain auth: SPF/DKIM/DMARC)
    ├── whatsapp       (Business number, template status)
    ├── catalog        (product source of truth)
    └── content        (blog / CMS)
```

Each Property carries: `provider`, `connection_ref` (→ §3 Secret Manager, never the secret itself), `status` ∈ {absent | connected | sensing | healthy | degraded | broken}, `last_checked`, and `findings` (structured, from the most recent audit Op).

**Onboarding becomes a state-fill, not a scramble.** Onboarding a brand = walking the graph and moving each Property from `absent` toward `healthy`. The "SOP" is no longer tribal knowledge in your head — it is the ordered list of Property types and the connect-or-provision Op that fills each. Tanmatra.food onboarding = the graph with most nodes `absent`; Abley's = the graph with `ads_account`, `merchant_feed`, and `search_console` present-but-`degraded`. Same object, different fill state. The onboarding dashboard is just a render of the graph.

**Critically, this is mostly READ.** Populating the graph is the §6.3 "Sense" phase: scoped read credentials, inventory, health-check. No writes, no new governance machinery, no invariant pressure. It is the highest value-to-risk capability in the system — it makes onboarding legible and every other pillar "see" the brand, while risking nothing.

**Hard prerequisite (do this before any code):** manually onboard ONE brand (Tanmatra.food) end to end and write down every step, account, and credential as you go. That written run IS the schema for this section. We do not systematize an SOP that has not been performed once by hand. The Brand Graph is designed *from* that document, not ahead of it.

**Build status:** Property model + read-only Sense for 2–3 property types is a candidate **Slice 3** opener (it is literally Manage's read-only phase, §6.3). The full typed graph across all property types is **deferred** — it grows one property type at a time, each gated by "can I operate this for a paying brand."

### 6.6 Presence — organic & owned-channel operations (distinct from paid Grow)

**Problem this solves:** Abley's growth is blocked by Search Console, Merchant Center feed health, the WordPress blog, email deliverability, and reputation — none of which are bids or budgets. Forcing them into Grow would repeat the original defect of leaking one domain's vocabulary into another. They are **owned-property audit-and-improve loops**, not trust-tiered spend decisions, and they get their own adapter family.

**Why a separate family, concretely.** Grow Ops change *spend* on *rented* platforms and need spend caps + reversibility. Presence Ops improve *owned* properties and are dominated by **audit → finding → recommended fix → (optional) governed change**. The risk profile, the gates, and the cadence all differ.

**Presence scope (each is an adapter action, all sharing the kernel):**
- `presence.search_console.audit` — coverage errors, query/CTR opportunities, indexing health (READ)
- `presence.merchant_center.audit` — disapprovals, feed mismatches, policy flags (READ)
- `presence.merchant_center.fix` — corrective feed change (WRITE — gated, reversible)
- `presence.email.audit` — SPF/DKIM/DMARC + deliverability + list health (READ)
- `presence.reputation.audit` — review/rating signals across surfaces (READ)
- `presence.content.*` — blog/CMS publishing (overlaps Build; lives wherever the deploy target is)

**The dominant pattern is read-only audit producing findings.** A Presence audit emits structured findings into the Brand Graph (§6.5) and, where a fix exists, *proposes* a governed Op — it does not silently change anything (§2.3). This means the entire READ half of Presence ships with **zero write risk** and immediately makes the OS useful to a brand like Abley's: "here is exactly what is wrong with your Merchant Center and Search Console, ranked, with the fix for each." That is sellable on its own, before a single write integration exists.

**Paid channels that are NOT Google/Meta still belong to Grow, not Presence.** Amazon Ads is a Grow adapter action (it is paid spend, trust-tiered, capped) — it just isn't built yet. Listing it here only to be unambiguous: Presence = organic + owned; Grow = paid, regardless of platform.

**Build status:** the **read-only audit half** (Search Console + Merchant Center audits for Abley's) is the strongest candidate for a near-term slice because it unblocks a real brand with no write risk and proves the family. Everything that *writes* to an owned property is **deferred** behind the same trust ladder as Manage (§6.3) — sense first, write later, tier by tier. Email sending, WhatsApp campaigns, and content publishing are each a live integration with real operational burden and are **not** near-term for a solo operator (§ the operating-capacity constraint).

---

## 7. Conversational interface

The front door for all pillars. Intent parsing → adapter `plan()` → cards. Three hard rules:

1. The interface **never executes**; it only proposes Ops. All authority lives in the kernel.
2. Ambiguity resolves by asking, not assuming (an Op with wrong params that passes gates is still wrong).
3. Every generated plan shows its cost estimate before approval.

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
| Observability | Sentry + structured logs to Cloud Logging + one dashboard | No ELK/Jaeger/Prometheus stack |
| Backups | Nightly pg_dump → GCS (multi-region bucket) + Terraform state versioning | This IS the DR plan; monthly restore test |
| Frontend | Next.js + shadcn/Tailwind on Firebase Hosting/Cloud Run | The one place defaults win |
| LLM | Claude API (agents, parsing, explanations) | Never gates (§2.1) |
| WhatsApp | Meta Cloud API | Template messages for cards |

**Core tables (control plane):** `tenants`, `brands`, `ops`, `op_traces`, `approvals`, `audit_events` (hash-chained), `trust_events`, `trust_snapshots`, `cost_ledger`, `recipes`, `outbox`, `policy_versions`, `connections` (Manage credentials metadata — secrets themselves stay in brand-project Secret Manager).

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

---

## 13. Cadences — recurring responsibility as a first-class object

**Problem this solves:** the work that actually establishes a brand is not one-shot Ops. It is "optimize Search Console weekly," "reconcile the feed," "run the campaign calendar," "the regular optimization tweaks." The kernel models a discrete Op beautifully and has **no model of an ongoing responsibility** — so recurring work lives in your memory, which does not scale past one or two brands.

**The model — a Cadence is a scheduled Op generator, nothing more exotic.**
```
Cadence
├── brand_id, domain                 # whose, which pillar
├── action                           # the Op it generates, e.g. presence.search_console.audit
├── schedule                         # cron-like (weekly, monthly) OR signal-driven
├── status      ∈ {on_track | due | overdue | needs_attention}
└── last_run, next_run, last_finding_ref
```

A Cadence does not execute anything. On schedule, it **proposes an Op** into the exact same governed loop (§4.1) — previewed, gated, approved/auto, audited. It is a producer of Ops, not a side channel. This keeps invariant §2.3 intact: cadences create no new way to touch client property.

**Why this is the multiplier you actually need.** With cadences, "handling Abley's and Tanmatra.food and a new lead at the same time" becomes a **queue with status**, not a feat of memory: the system tells you what is `due` and `overdue` across all brands, each as a ready-to-approve card. This is the difference between operating 3 brands and operating 30 — and it is cheap, because it reuses the entire loop and adds only a scheduler + a status field.

**Start dead-simple.** Cadences begin as read-only audit cadences (run the §6.6 audits weekly, surface findings). No autonomous writes on a timer until the relevant brand-domain has earned Tier 2 *and* a deterministic gate bounds the worst case (§2.1, §4.4). A recurring auto-write is the highest-trust action in the system and is **deferred** accordingly.

**Build status:** the Cadence object + a read-only audit scheduler is a small, high-leverage addition that becomes worthwhile the moment you run the §6.6 audits for **two** brands manually and feel the duplication. Not before — a scheduler with nothing safe to schedule is premature. **Deferred until read-only audits exist and run for ≥2 brands.**
