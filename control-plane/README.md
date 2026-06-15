# Agency OS — control plane (Slice 1 kernel)

The governance kernel from `/ARCHITECTURE.md`. Run:

    pip install -e ".[dev]"   # or: pip install fastapi uvicorn sqlalchemy pydantic pytest httpx
    pytest                    # 11 tests incl. the e2e governed loop
    uvicorn app.main:app --reload

## What is REAL vs STUB

| Component | Status |
|---|---|
| Op state machine (illegal transitions impossible) | REAL |
| Tamper-evident audit chain (hash-linked, verified) | REAL |
| Deterministic policy gates w/ rule/limit/delta explanations | REAL |
| Statutory firewall (never auto-approved, any tier) | REAL |
| Trust engine: saturating penalties + decay + 60/85 tiers | REAL (provisional weights, §11.4) |
| Transactional outbox + retries + PARTIAL parking | REAL (in-process drain; Cloud Tasks = issue) |
| Per-tenant access checks | REAL (header-based; app-level) |
| Postgres RLS policies | REAL (verified by tests, session wired in middleware & database session) |
| Provision adapter | STUB (fake terraform plan; real recipe executor = issue) |
| WhatsApp surface | REAL (Meta Cloud API client + webhook receiver; mock in tests) |
| Trust wiring into /intents tier | NOT WIRED (tier passed explicitly until trust events flow) |

SQLite by default (`AOS_DB_URL` overrides). Postgres + RLS is a tracked issue —
every table already carries `tenant_id` so it bolts on without schema change.
