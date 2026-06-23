#!/usr/bin/env bash
# Deploy control-plane frontend console to Cloud Run
set -euo pipefail

GCP_PROJECT_ID="aos-control-plane-tmg"
REGION="us-central1"
BACKEND_SERVICE="agency-os-backend"
FRONTEND_SERVICE="agency-os-web"

echo "=== Starting Agency-OS Frontend Deployment ==="
echo "Project ID: $GCP_PROJECT_ID"
echo "Region: $REGION"

# 1. Verify gcloud configuration
echo "Checking gcloud configuration..."
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ "$CURRENT_PROJECT" != "$GCP_PROJECT_ID" ]; then
    echo "Setting gcloud project to $GCP_PROJECT_ID..."
    gcloud config set project "$GCP_PROJECT_ID"
fi

# 2. Use Custom Domain Backend URL for production cutover
echo "Using custom domain Backend URL..."
BACKEND_URL="https://api.trendingmediagroup.in"
echo "Backend URL: $BACKEND_URL"

# 3. Build and push the frontend Docker image using Google Cloud Build with config
echo "Building and pushing frontend image via Google Cloud Build..."
gcloud builds submit \
  --config control-plane/web/cloudbuild.yaml \
  --substitutions="_NEXT_PUBLIC_API_URL=$BACKEND_URL,_REGION=$REGION" \
  --project "$GCP_PROJECT_ID" \
  control-plane/web/

# 4. Redeploy/Update the Cloud Run frontend service
echo "Updating Cloud Run service $FRONTEND_SERVICE..."
gcloud run services update "$FRONTEND_SERVICE" \
  --image "$REGION-docker.pkg.dev/$GCP_PROJECT_ID/aos-docker/control-plane-web:latest" \
  --region "$REGION" \
  --project "$GCP_PROJECT_ID"

echo "=== Frontend Deployment Successfully Completed! ==="
echo "Frontend Console is now live at: $(gcloud run services describe "$FRONTEND_SERVICE" --platform managed --region "$REGION" --format="value(status.url)" --project "$GCP_PROJECT_ID")"
