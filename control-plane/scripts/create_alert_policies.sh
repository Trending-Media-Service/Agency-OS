#!/bin/bash
#
# Provision GCP Cloud Monitoring Alert Policies for Agency OS.
# Sanctions: DLQ depth, circuit breaker trips, verify failure rate, and readyz down.
#
# TAG=agy

set -euo pipefail

# 1. Resolve GCP Project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
if [ -z "${PROJECT_ID}" ]; then
  echo "❌ Error: No active gcloud project found. Run 'gcloud config set project [PROJECT_ID]' first." >&2
  exit 1
fi

echo "🚀 Provisioning Alert Policies in GCP Project: ${PROJECT_ID}..."

# Create a temp directory for the policy JSON files
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# 2. Write Policy Definitions

# Policy A: DLQ depth > 0 for 15m (using aos_outbox_dead_gauge)
cat <<EOF > "${TEMP_DIR}/dlq_depth.json"
{
  "displayName": "Agency OS - DLQ (Dead Tasks) Depth > 0 (15m)",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Outbox Dead Gauge Threshold",
      "conditionThreshold": {
        "filter": "metric.type=\"workload.googleapis.com/aos_outbox_dead_gauge/gauge\" AND resource.type=\"cloud_run_revision\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.0,
        "duration": "900s",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_MAX"
          }
        ]
      }
    }
  ],
  "enabled": true
}
EOF

# Policy B: Circuit Breaker Trips (any trip)
cat <<EOF > "${TEMP_DIR}/breaker_trips.json"
{
  "displayName": "Agency OS - Circuit Breaker Tripped",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Circuit Breaker Trips Count",
      "conditionThreshold": {
        "filter": "metric.type=\"workload.googleapis.com/aos_circuit_breaker_trips_total/counter\" AND resource.type=\"cloud_run_revision\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.0,
        "duration": "60s",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_RATE"
          }
        ]
      }
    }
  ],
  "enabled": true
}
EOF

# Policy C: Verify Failure Rate High
cat <<EOF > "${TEMP_DIR}/verify_fail.json"
{
  "displayName": "Agency OS - Connector Verification Failure Rate High",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Verify Failure Rate",
      "conditionThreshold": {
        "filter": "metric.type=\"workload.googleapis.com/aos_connector_operations_total/counter\" AND metric.label.operation=\"verify\" AND metric.label.result=\"failure\" AND resource.type=\"cloud_run_revision\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.0,
        "duration": "300s",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_RATE"
          }
        ]
      }
    }
  ],
  "enabled": true
}
EOF

# Policy D: /readyz Probe Down
cat <<EOF > "${TEMP_DIR}/readyz_down.json"
{
  "displayName": "Agency OS - readyz Probe Down (Service Unavailable)",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Cloud Run Instance Count Zero",
      "conditionThreshold": {
        "filter": "metric.type=\"run.googleapis.com/container/instance_count\" AND resource.type=\"cloud_run_revision\"",
        "comparison": "COMPARISON_LE",
        "thresholdValue": 0.0,
        "duration": "120s",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_MEAN"
          }
        ]
      }
    }
  ],
  "enabled": true
}
EOF

# 3. Apply Policies using gcloud
for policy_file in "${TEMP_DIR}"/*.json; do
  policy_name=$(basename "${policy_file}" .json)
  display_name=$(jq -r '.displayName' "${policy_file}")
  
  echo "Applying policy: ${display_name}..."
  
  # Check if policy already exists to make the script idempotent
  EXISTING_POLICY_ID=$(gcloud alpha monitoring policies list \
    --filter="displayName=\"${display_name}\"" \
    --format="value(name)" 2>/dev/null || echo "")
    
  if [ -n "${EXISTING_POLICY_ID}" ]; then
    echo "  -> Policy already exists (ID: ${EXISTING_POLICY_ID}). Updating..."
    gcloud alpha monitoring policies update "${EXISTING_POLICY_ID}" \
      --policy-from-file="${policy_file}" >/dev/null
  else
    echo "  -> Policy does not exist. Creating..."
    gcloud alpha monitoring policies create \
      --policy-from-file="${policy_file}" >/dev/null
  fi
done

echo "✅ All alert policies successfully provisioned!"
