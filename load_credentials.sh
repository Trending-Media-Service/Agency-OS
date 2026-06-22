#!/usr/bin/env bash
#
# load_credentials.sh — push all platform credentials into Google Secret Manager
# in one pass. The manifest of supported keys lives in credentials.example.env.
#
# Usage:
#   cp credentials.example.env credentials.env   # then fill it in
#   ./load_credentials.sh [PROJECT_ID]           # defaults to current gcloud project
#
# Idempotent: creates each secret if missing, otherwise adds a new version.
# Blank values and obvious placeholders (mock-*, CHANGEME*, <...>) are skipped,
# so partial fills are safe to re-run.
#
set -euo pipefail

ENV_FILE="${ENV_FILE:-credentials.env}"
PROJECT="${1:-$(gcloud config get-value project 2>/dev/null || true)}"

if [[ -z "$PROJECT" ]]; then
  echo "ERROR: no project resolved. Pass one explicitly: ./load_credentials.sh PROJECT_ID" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Run:  cp credentials.example.env $ENV_FILE   (then fill it in)" >&2
  exit 1
fi

# env-var key (in $ENV_FILE)  ->  Secret Manager secret name
declare -A SECRET_NAME=(
  [DATABASE_URL]=aos-database-url
  [WORKER_DATABASE_URL]=aos-worker-database-url
  [OPERATOR_TOKEN]=aos-operator-token
  [WHATSAPP_APP_SECRET]=whatsapp-app-secret
  [WHATSAPP_VERIFY_TOKEN]=whatsapp-verify-token
  [SECRET_KEY]=aos-oauth-state-secret
  [GOOGLE_ADS_CLIENT_ID]=google-ads-client-id
  [GOOGLE_ADS_CLIENT_SECRET]=google-ads-client-secret
  [GOOGLE_ADS_DEVELOPER_TOKEN]=google-ads-developer-token
  [META_ADS_CLIENT_ID]=meta-ads-client-id
  [META_ADS_CLIENT_SECRET]=meta-ads-client-secret
  [SHOPIFY_CLIENT_ID]=shopify-client-id
  [SHOPIFY_CLIENT_SECRET]=shopify-client-secret
)

echo "Project: $PROJECT"
echo "Source:  $ENV_FILE"
echo "--------------------------------------------------"

loaded=0
skipped=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"                          # strip trailing CR
  [[ "$line" =~ ^[[:space:]]*# ]] && continue   # comment
  [[ "$line" != *"="* ]] && continue            # not KEY=VALUE
  key="${line%%=*}"
  val="${line#*=}"
  key="$(printf '%s' "$key" | tr -d '[:space:]')"
  val="${val#[\"\']}"; val="${val%[\"\']}"      # strip one layer of surrounding quotes
  [[ -z "${SECRET_NAME[$key]:-}" ]] && continue # key we don't manage
  if [[ -z "$val" || "$val" == CHANGEME* || "$val" == mock-* || "$val" == "<"* ]]; then
    echo "skip    $key  (blank/placeholder)"
    skipped=$((skipped + 1))
    continue
  fi
  secret="${SECRET_NAME[$key]}"
  if gcloud secrets describe "$secret" --project="$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$val" | gcloud secrets versions add "$secret" --project="$PROJECT" --data-file=- >/dev/null
    echo "updated $key -> $secret  (new version)"
  else
    printf '%s' "$val" | gcloud secrets create "$secret" --project="$PROJECT" --replication-policy=automatic --data-file=- >/dev/null
    echo "created $key -> $secret"
  fi
  loaded=$((loaded + 1))
done < "$ENV_FILE"

echo "--------------------------------------------------"
echo "Loaded/updated: $loaded   Skipped: $skipped"
echo "Verify:  gcloud secrets list --project=$PROJECT"
