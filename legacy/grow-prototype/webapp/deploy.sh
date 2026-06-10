#!/bin/bash
# Script to deploy Agency OS Frontend/Backend to GCP Cloud Run

set -e

# Configuration
PROJECT_ID="omnianalytix-master-platform"
REGION="us-central1"
SERVICE_NAME="agency-os-webapp"

# Allow overrides from environment
PROJECT_ID="${1:-$PROJECT_ID}"
REGION="${2:-$REGION}"

echo "Starting deployment process..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
AGENCY_OS_DIR="$(dirname "$SCRIPT_DIR")"
GOOGLE3_DIR="$(cd "$AGENCY_OS_DIR/../../../.." && pwd)"

# We need to run from google3 root to easily resolve paths relatively if needed,
# but we will create temp dir relative to script.
TMP_DIR="$SCRIPT_DIR/deploy_tmp"

echo "Cleaning up old temp dir if exists..."
rm -rf "$TMP_DIR"

echo "Creating deployment structure..."
mkdir -p "$TMP_DIR/google3/learning/gemini/agents/projects/agency_os/webapp/static"

# Copy requirements and Dockerfile
cp "$SCRIPT_DIR/requirements.txt" "$TMP_DIR/"
cp "$SCRIPT_DIR/Dockerfile.deploy" "$TMP_DIR/Dockerfile"

# Copy webapp files
cp "$SCRIPT_DIR/app.py" "$TMP_DIR/google3/learning/gemini/agents/projects/agency_os/webapp/"
cp "$SCRIPT_DIR/static/index.html" "$TMP_DIR/google3/learning/gemini/agents/projects/agency_os/webapp/static/"

# Copy other backend files (excluding tests and webapp directory itself)
# We use find to get all .py files in agency_os, excluding tests and webapp
cd "$AGENCY_OS_DIR"
find . -maxdepth 1 -name "*.py" ! -name "*_test.py" -exec cp {} "$TMP_DIR/google3/learning/gemini/agents/projects/agency_os/" \;

echo "Files prepared for deployment."

# Go to temp dir to deploy
cd "$TMP_DIR"

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --allow-unauthenticated \
    --platform managed \
    --quiet

echo "Deployment completed successfully!"

# Clean up
cd "$SCRIPT_DIR"
rm -rf "$TMP_DIR"
echo "Cleaned up temporary files."
