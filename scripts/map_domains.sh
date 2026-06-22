#!/usr/bin/env bash
#
# scripts/map_domains.sh — one-time: map custom domains onto the Cloud Run services.
#   api.trendingmediagroup.in -> agency-os-backend   (control-plane API)
#   app.trendingmediagroup.in -> agency-os-web        (console)
#
# Prereq: verify ownership of the domain ONCE, under the same account gcloud uses:
#   gcloud domains verify trendingmediagroup.in        (or via Google Search Console)
#
# Usage: ./scripts/map_domains.sh [PROJECT_ID] [REGION]
# Then add the DNS records it prints at your registrar; managed certs auto-provision.
#
set -euo pipefail

PROJECT="${1:-aos-control-plane-tmg}"
REGION="${2:-asia-south1}"
DOMAIN="trendingmediagroup.in"

declare -A MAP=(
  ["api.${DOMAIN}"]=agency-os-backend
  ["app.${DOMAIN}"]=agency-os-web
)

for host in "${!MAP[@]}"; do
  svc="${MAP[$host]}"
  if gcloud beta run domain-mappings describe --domain "$host" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    echo "ok    ${host} already mapped"
  else
    echo "==> mapping ${host} -> ${svc}"
    if ! gcloud beta run domain-mappings create --service "$svc" --domain "$host" \
         --region "$REGION" --project "$PROJECT"; then
      echo "!! create failed for ${host}. Is '${DOMAIN}' verified for this account?" >&2
      echo "   Run: gcloud domains verify ${DOMAIN}   (then re-run this script)" >&2
      echo "   If domain mappings aren't available in ${REGION}, front the services with a" >&2
      echo "   global external HTTPS load balancer instead." >&2
    fi
  fi
done

echo ""
echo "=== DNS records to add at your registrar ==="
for host in "${!MAP[@]}"; do
  echo "--- ${host} ---"
  gcloud beta run domain-mappings describe --domain "$host" --region "$REGION" --project "$PROJECT" \
    --format="table(status.resourceRecords.name, status.resourceRecords.type, status.resourceRecords.rrdata)" 2>/dev/null \
    || echo "  (not mapped yet)"
done
echo ""
echo "Certificates provision automatically once DNS resolves (15m–24h)."
echo "Verify:  curl -sI https://api.${DOMAIN}/   # should reach the backend"
