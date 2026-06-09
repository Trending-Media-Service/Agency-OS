# Agency OS Web Application

This directory contains the frontend and backend for the Agency OS Control Panel.

## Structure

- `app.py`: Flask backend exposing API endpoints and serving the static frontend.
- `static/index.html`: Tailwind CSS + JS frontend for monitoring and controlling Agency OS.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: Dockerfile for local container builds.
- `Dockerfile.deploy`: Dockerfile optimized for GCP Cloud Run deployment.
- `deploy.sh`: Script to package and deploy the application to Cloud Run.

## Running Locally

1.  **Install dependencies**:
    ```bash
    pip install Flask
    ```

2.  **Set PYTHONPATH**:
    Ensure the `google3` directory is in your python path.
    ```bash
    export PYTHONPATH=/path/to/your/workspace/google3
    ```

3.  **Run the app**:
    ```bash
    python3 google3/learning/gemini/agents/projects/agency_os/webapp/app.py
    ```
    Open `http://localhost:8080` in your browser.

## Deploying to GCP Cloud Run

The `deploy.sh` script automates the deployment. It creates a temporary directory with the correct structure to allow `google3` imports to work in the container, and then runs `gcloud run deploy`.

### Prerequisites

Ensure you are authenticated with `gcloud` and have access to your target project.
If you need to switch accounts:
```bash
gcloud config set account YOUR_ACCOUNT@google.com
```

### Deploy Command

Run the script from the `google3` directory:
```bash
./learning/gemini/agents/projects/agency_os/webapp/deploy.sh [PROJECT_ID] [REGION]
```

- `PROJECT_ID`: Your GCP Project ID (defaults to `omnianalytix-master-platform` if not specified).
- `REGION`: GCP Region (defaults to `us-central1`).

Example:
```bash
./learning/gemini/agents/projects/agency_os/webapp/deploy.sh my-gcp-project us-east1
```
