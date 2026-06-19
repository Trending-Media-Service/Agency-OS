# AGENTS.md — instructions for ALL coding agents working this repository

This file is binding for any AI agent (Gemini, Jules, Copilot, Claude, or other)
making changes here. Human = repository owner (@tanmatra6-wq). When these rules
conflict with your default behavior, these rules win.

## The law
1. **`/ARCHITECTURE.md` is authoritative.** Implement it as written. If you
   believe it is wrong or incomplete, OPEN AN ISSUE explaining why — do not
   improvise a different design in code. Architecture changes happen as PRs to
   ARCHITECTURE.md itself, reviewed by the owner, in the same PR as the code
   that depends on them.
2. **Work one GitHub issue per PR.** The issue defines scope. Build exactly
   what it asks — nothing speculative, no extra modules, no "while I was here"
   features. If the issue is ambiguous, comment on it and stop.
3. **Small PRs.** If a change exceeds ~500 changed lines outside of generated
   migrations/lockfiles, split it.

## Hard prohibitions (CI enforces some; all are binding)
- **Never put a model in a gating path.** `control-plane/app/kernel/services.py`
  policy and trust functions stay deterministic (ARCHITECTURE.md §2.1). LLM
  calls may draft, rank, and explain — never approve, block, or score trust.
- **Never weaken the audit chain.** `audit_append` / `audit_verify` semantics
  and the `audit_events` schema change ONLY alongside an ARCHITECTURE.md §4.5
  amendment in the same PR. Audit rows are never updated or deleted.
- **Never bypass the Op state machine.** No code path may change external state
  without an Op in `APPROVED` and a trace. `ALLOWED_TRANSITIONS` edits require
  an ARCHITECTURE.md §4.1 amendment in the same PR.
- **Statutory firewall is permanent** (§2.2). Do not add auto-approval paths
  for tax/GST/VAT/statutory actions at any tier.
- **No secrets in the repo.** No tokens, keys, service-account JSON, .env with
  real values — not in code, tests, fixtures, or history. Credentials are
  referenced via Secret Manager paths only.
- **No new top-level directories.** Layout is: `ARCHITECTURE.md`, `AGENTS.md`,
  `control-plane/`, `recipes/`, `legacy/`, `docs/`, `.github/`. Adapters go in
  `control-plane/app/adapters/<domain>/`; recipes in `recipes/<name>/<version>/`.
- **`legacy/` and `docs/archive/` are read-only reference.** Do not edit,
  extend, or import from them. Port concepts into `control-plane/` instead.
- **Never recreate `google3/` paths** or any vendor-internal monorepo
  conventions. They were committed here once by a prior agent in error.
- **No new runtime dependencies** unless the issue explicitly names them.
  Stack is fixed by ARCHITECTURE.md §8 (FastAPI, SQLAlchemy, Postgres,
  Cloud Tasks, Terraform). No Kafka, no Temporal, no LangChain, no service
  mesh — these are on the §10 deferred list, not forgotten.
- **Do not generate new strategy/roadmap markdown documents.** One roadmap
  exists (ARCHITECTURE.md §9). This repo has been buried in generated docs
  before; it does not happen again.

## Definition of done (every PR)
- [ ] `cd control-plane && pytest` passes — all of it, locally and in CI
- [ ] New state-changing behavior emits traces (`OpTrace`) and audit events
- [ ] New behavior has tests, including at least one failure-path test
- [ ] `control-plane/README.md` REAL-vs-STUB table updated if a status changed
- [ ] PR description names the issue (`Closes #N`) and the ARCHITECTURE.md
      sections it implements
- [ ] No TODOs left for invariants — TODOs are allowed for deferred features
      only, with an issue reference

## Conventions
- Python ≥3.11, type hints on public functions, SQLAlchemy 2.0 style.
- Money is integer minor units + currency (no floats for money, ever).
- All timestamps UTC, timezone-aware.
- Branch naming: `s1-<issue#>/<slug>` (e.g. `s1-2/postgres-rls`).
- Commit messages explain WHY, reference the issue.

## Connector conventions (Manage/Grow/Presence connect surface)
- **Governed connections only.** Connect, verify, disconnect, rotate, and OAuth
  callbacks are governed Ops (§2.3/§4.1) — never direct `connections` writes. The
  plugin-webhook pattern (ARCHITECTURE.md §5.1) is the template for public callbacks:
  resolve the connection under a privileged session, set `tenant_context`, then propose.
- **Credentials are Secret Manager refs.** Raw credentials/tokens are written to the
  brand project's Secret Manager at execute time; the DB stores only the `secret_ref`
  pointer + non-secret config. Never log, preview, or audit a raw credential.
- **Directory naming invariant.** The console builds the connector grid from tool
  names containing the substring "connect". Connect tools MUST contain "connect";
  lifecycle tools (verify/revoke/rotate) MUST NOT. Pinned by
  `tests/test_connector_contract.py`.

## When blocked
Stop and comment on the issue. A wrong guess that passes review costs more
than a question. Specifically stop if: a test you didn't write fails, the
issue contradicts ARCHITECTURE.md, or a change would touch two prohibition
items above.
