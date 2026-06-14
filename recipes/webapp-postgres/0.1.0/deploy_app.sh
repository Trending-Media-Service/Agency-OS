#!/usr/bin/env bash
set -euo pipefail

echo "=== Starting Post-Apply Application Deployment and Migration ==="
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Brand ID: $BRAND_ID"
echo "Repository: $REPO_URL"

PROXY_PATH="/tmp/cloud-sql-proxy"

# Generate fresh/random internal parameters
API_URL="https://${API_SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app/api"
FRONTEND_ORIGIN="https://${FRONTEND_SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
FRESH_API_KEY="AIzaSyBK3TyG-FRESH-KEY-${PROJECT_NUMBER}"
# Fake redis url default fallback
REDIS_URL="redis://localhost:6379"

# Create a secure temporary directory
TEMP_DIR=$(mktemp -d)
trap 'echo "Cleaning up..."; rm -rf "$TEMP_DIR"' EXIT

echo "Cloning repository $REPO_URL..."
git clone "$REPO_URL" "$TEMP_DIR"

CLOUDBUILD_FILE="$TEMP_DIR/cloudbuild.yaml"
if [ ! -f "$CLOUDBUILD_FILE" ]; then
    echo "Error: cloudbuild.yaml not found in cloned repository."
    exit 1
fi

echo "Patching cloudbuild.yaml..."
# Replace substitutions using standard sed
sed -i -E "s|_PROJECT:\s*\S+|_PROJECT: $PROJECT_ID|g" "$CLOUDBUILD_FILE"
sed -i -E "s|_REGION:\s*\S+|_REGION: $REGION|g" "$CLOUDBUILD_FILE"
sed -i -E "s|_REPO:\s*\S+|_REPO: wellness|g" "$CLOUDBUILD_FILE"
sed -i -E "s|_API_SERVICE:\s*\S+|_API_SERVICE: $API_SERVICE|g" "$CLOUDBUILD_FILE"
sed -i -E "s|_FRONTEND_SERVICE:\s*\S+|_FRONTEND_SERVICE: $FRONTEND_SERVICE|g" "$CLOUDBUILD_FILE"
sed -i -E "s|_API_URL:\s*\S+|_API_URL: $API_URL|g" "$CLOUDBUILD_FILE"
sed -i -E "s|_FRONTEND_ORIGIN:\s*\S+|_FRONTEND_ORIGIN: $FRONTEND_ORIGIN|g" "$CLOUDBUILD_FILE"

# Map Secret Manager secrets
sed -i "s|DATABASE_URL=wellness-foods-database-url:latest|DATABASE_URL=brand-${BRAND_ID}-database-url:latest|g" "$CLOUDBUILD_FILE"
sed -i "s|SESSION_SECRET=wellness-foods-session-secret:latest|SESSION_SECRET=brand-${BRAND_ID}-session-secret:latest,ADMIN_SESSION_SECRET=brand-${BRAND_ID}-admin-session-secret:latest|g" "$CLOUDBUILD_FILE"

# Remove hardcoded ADMIN_SESSION_SECRET from env-vars
sed -i -E "s|ADMIN_SESSION_SECRET=[a-zA-Z0-9]+,||g" "$CLOUDBUILD_FILE"

# Map Cloud SQL instance
sed -i "s|--add-cloudsql-instances=\S+|--add-cloudsql-instances=${PROJECT_ID}:${REGION}:${DB_INSTANCE_NAME}|g" "$CLOUDBUILD_FILE"

# Map corporate API key and Redis URL
sed -i "s|GOOGLE_API_KEY=\S+|GOOGLE_API_KEY=${FRESH_API_KEY}|g" "$CLOUDBUILD_FILE"
sed -i "s|REDIS_URL=\S+|REDIS_URL=${REDIS_URL}|g" "$CLOUDBUILD_FILE"

echo "Submitting Cloud Build job..."
gcloud builds submit --config="$CLOUDBUILD_FILE" --project="$PROJECT_ID" --substitutions=COMMIT_SHA=latest --quiet "$TEMP_DIR"
echo "Cloud Build job completed successfully."

echo "Starting database schema migration..."
if [ ! -f "$PROXY_PATH" ]; then
    echo "Downloading Cloud SQL Auth Proxy..."
    curl -o "$PROXY_PATH" https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64
    chmod +x "$PROXY_PATH"
fi

# Run proxy in background
echo "Starting Cloud SQL Proxy..."
"$PROXY_PATH" "${PROJECT_ID}:${REGION}:${DB_INSTANCE_NAME}" --port=5432 &
PROXY_PID=$!
trap 'echo "Killing proxy..."; kill "$PROXY_PID" || true; rm -rf "$TEMP_DIR"' EXIT
sleep 5

echo "Patching package.json catalog dependencies for npm compatibility..."
python3 -c "
import json, os
db_pkg_path = '$TEMP_DIR/lib/db/package.json'
if os.path.exists(db_pkg_path):
    with open(db_pkg_path, 'r') as f:
        pkg = json.load(f)
    for section in ['dependencies', 'devDependencies']:
        if section in pkg:
            for k, v in list(pkg[section].items()):
                if v == 'catalog:':
                    if k == 'drizzle-orm':
                        pkg[section][k] = '0.45.2'
                    elif k == 'zod':
                        pkg[section][k] = '^3.25.76'
                    elif k == '@types/node':
                        pkg[section][k] = '^25.3.3'
    with open(db_pkg_path, 'w') as f:
        json.dump(pkg, f, indent=2)
    print('Successfully patched package.json')
else:
    print('Warning: package.json not found at', db_pkg_path)
"

echo "Installing schema migration dependencies..."
npm install --prefix "$TEMP_DIR/lib/db"

echo "Running drizzle-kit push..."
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}" npm run push --prefix "$TEMP_DIR/lib/db"

echo "Database schema migration completed successfully."
echo "=== Post-Apply Deployment Actions Complete ==="
