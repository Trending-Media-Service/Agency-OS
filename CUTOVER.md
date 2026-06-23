# Region cutover — asia-south1 → us-central1

Moves the platform to `us-central1` (Cloud Run + Artifact Registry + Cloud SQL +
Cloud Tasks) and onto the `trendingmediagroup.in` custom domain. The database is
**migrated** to us-central1 (not accessed cross-region).

> ⚠️ **Do NOT merge the `deploy.yml` cutover until steps 1–3 are done.** The GitHub
> Actions CD runs on every push to `main`; if it targets us-central1 before the
> Artifact Registry repo, the migrated Cloud SQL instance, and the Cloud Tasks
> queue exist, the deploy fails. Order matters.

## What changes
- `deploy.yml`: `REGION`, Artifact Registry hosts, `CLOUDSQL_INSTANCE`, `APP_URL`,
  `configure-docker` → us-central1. (Manual scripts already cut over on
  `feature/us-central-cutover`.)
- Database: new `us-central1` Cloud SQL instance `aos-db-us`, data migrated from
  `asia-south1:aos-db`.

## 1. Provision us-central1 infra (before merge)
```bash
PROJECT=aos-control-plane-tmg
# Artifact Registry — must match deploy.yml's repo path "agency-os"
gcloud artifacts repositories create agency-os \
  --repository-format=docker --location=us-central1 --project="$PROJECT"   # if absent
# Cloud Tasks queue (regional) used by the outbox drain
gcloud tasks queues create aos-outbox --location=us-central1 --project="$PROJECT"
```
GCS buckets (`aos-tfstate-tmg`, report buckets) are reachable cross-region — no move needed.

## 2. Migrate the database
```bash
# Instance name MUST match deploy.yml CLOUDSQL_INSTANCE (aos-db-us)
gcloud sql instances create aos-db-us \
  --database-version=POSTGRES_16 --region=us-central1 --project="$PROJECT"   # match aos-db's tier/flags
```
Migrate data (pick one):
- **Dump/restore** (simplest, brief write-freeze): `pg_dump` from `aos-db` → restore into `aos-db-us`.
- **Database Migration Service** (minimal downtime): continuous job asia-south1 → us-central1, then promote.

Point the app at the new instance (connector socket is `/cloudsql/<INSTANCE_CONNECTION_NAME>`):
```bash
# credentials.env: set DATABASE_URL / WORKER_DATABASE_URL with
#   host=/cloudsql/aos-control-plane-tmg:us-central1:aos-db-us
./load_credentials.sh
```

## 3. Domain (can run in parallel)
`gcloud domains verify trendingmediagroup.in` → `./scripts/map_domains.sh` (defaults
to us-central1) → add DNS → wait for cert. Details in `DOMAINS.md`.

## 4. Merge + deploy
Merge this PR. The CD builds/pushes to the us-central1 Artifact Registry, runs the
migration job against `aos-db-us`, and deploys the backend + console to us-central1.
Watch the run.

## 5. Validate, then decommission
- Smoke-test the us-central1 services and `https://api.trendingmediagroup.in/`.
- Register the OAuth callback on the domain (see `ONBOARDING.md`).
- Once stable, delete the asia-south1 Cloud Run services and — after a retention
  window — the `asia-south1:aos-db` instance + asia-south1 images.

## Notes
- `APP_URL` is the us-central1 `run.app` URL (internal base for Cloud Tasks /
  Scheduler, which call `{APP_URL}/tasks/...`); OAuth uses the custom domain via the
  explicit `redirect_uri`. `deploy.sh` hardcodes `APP_URL=https://api.trendingmediagroup.in`,
  which only works once the domain is live — prefer the run.app URL there too, or
  sequence the domain first.
- Re-provision the scheduler after cutover (`control-plane/scripts/provision_scheduler.sh`).
