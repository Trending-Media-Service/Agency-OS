#!/usr/bin/env bash
#
# scripts/onboard.sh — guided operator-assisted onboarding for a brand/tenant.
#
# OAuth needs an in-browser approval, so this bootstraps the tenant, prints the
# authorize URLs to open, and gives you the follow-up commands (set the Google
# Ads developer token, register a headless site, verify connections). It drives
# the real /api/v1/onboarding/* flow — the console's Connect buttons still use
# the old mock path.
#
# Usage:
#   BACKEND=https://api.yourdomain.com \
#     ./scripts/onboard.sh --name Ableys --domain ableys.com --shop ableys [--tier shared]
#
set -euo pipefail

BACKEND="${BACKEND:-http://localhost:8000}"
NAME=""; DOMAIN=""; SHOP=""; TIER="shared"
while [ $# -gt 0 ]; do
  case "$1" in
    --name)   NAME="${2:-}";   shift 2;;
    --domain) DOMAIN="${2:-}"; shift 2;;
    --shop)   SHOP="${2:-}";   shift 2;;
    --tier)   TIER="${2:-}";   shift 2;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done
if [ -z "$NAME" ] || [ -z "$DOMAIN" ]; then
  echo "usage: BACKEND=https://api.you.com $0 --name NAME --domain DOMAIN [--shop HANDLE] [--tier shared|dedicated]" >&2
  exit 1
fi
command -v python3 >/dev/null || { echo "python3 required (for urlencode + JSON parse)" >&2; exit 1; }

uenc() { python3 -c 'import sys,urllib.parse as u; print(u.quote(sys.argv[1], safe=""))' "$1"; }
CALLBACK="${BACKEND}/api/v1/onboarding/oauth/callback"
RU="$(uenc "$CALLBACK")"

echo "==> 1. Bootstrapping tenant '${NAME}' (${DOMAIN}, tier=${TIER}) on ${BACKEND}"
RESP=$(curl -fsS -X POST "${BACKEND}/api/v1/onboarding/bootstrap?name=$(uenc "$NAME")&domain=$(uenc "$DOMAIN")&tier=$(uenc "$TIER")")
echo "    ${RESP}"
TENANT_ID=$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["tenant_id"])')
BRAND_ID=$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["brand_id"])')
echo "    tenant_id=${TENANT_ID}  brand_id=${BRAND_ID}"

SHOP_Q=""
[ -n "$SHOP" ] && SHOP_Q="&shop=$(uenc "$SHOP")"

cat <<EOF

==> 2. Open these authorize URLs in a browser and approve (each callback seeds a Connection):
    Shopify:    ${BACKEND}/api/v1/onboarding/oauth/authorize/shopify?tenant_id=${TENANT_ID}&brand_id=${BRAND_ID}&redirect_uri=${RU}${SHOP_Q}
    Google Ads: ${BACKEND}/api/v1/onboarding/oauth/authorize/google-ads?tenant_id=${TENANT_ID}&brand_id=${BRAND_ID}&redirect_uri=${RU}

==> 3. (Google Ads) after connecting, set the developer token (from Ads > Tools > API Center):
    curl -X POST '${BACKEND}/api/v1/onboarding/connection/config?tenant_id=${TENANT_ID}&brand_id=${BRAND_ID}&provider=google-ads' \\
         -H 'Content-Type: application/json' -d '{"developer_token":"<YOUR_DEV_TOKEN>"}'

==> 4. (Tanmatra / headless) register the site, then drive code via the build agent:
    curl -X POST '${BACKEND}/api/v1/onboarding/connection/direct?tenant_id=${TENANT_ID}&brand_id=${BRAND_ID}&provider=web&api_key=<DEPLOY_TOKEN>' \\
         -H 'Content-Type: application/json' -d '{"url":"https://${DOMAIN}"}'
    # headless code changes go through the build agent (build_deliver) with the GitHub repo URL + a GitHub PAT

==> 5. Verify:
    curl -s '${BACKEND}/connections' -H 'X-Tenant-ID: ${TENANT_ID}'
EOF
