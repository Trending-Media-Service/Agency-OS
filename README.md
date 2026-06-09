# Agency OS Codebase

This repository contains the Agency OS project codebase. The structure preserves the `google3` namespace to ensure internal import paths remain compatible.

## Project Structure

*   `google3/learning/gemini/agents/projects/agency_os/`: The core Agency OS codebase.
    *   `webapp/`: The control panel web application (Flask backend + Tailwind CSS frontend).
    *   `*engine.py` / `*worker.py`: Individual optimization and analysis modules (LTV, MMM, Sentiment, etc.).

## Running the Web Application Locally

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/tanmatra6-wq/Agency-OS.git
    cd Agency-OS
    ```

2.  **Install dependencies**:
    Ensure you have Python 3 installed. Navigate to the webapp directory and install Flask:
    ```bash
    cd google3/learning/gemini/agents/projects/agency_os/webapp
    pip install -r requirements.txt
    ```

3.  **Set PYTHONPATH**:
    You must set `PYTHONPATH` to the root of the cloned repository (the directory containing `google3`) so the imports can resolve correctly:
    ```bash
    # From the 'Agency-OS' root directory:
    export PYTHONPATH=$(pwd)
    
    # Or specify the absolute path:
    export PYTHONPATH=/path/to/Agency-OS
    ```

4.  **Run the application**:
    ```bash
    python3 google3/learning/gemini/agents/projects/agency_os/webapp/app.py
    ```
    Open `http://localhost:8080` in your web browser.

## Deploying to GCP Cloud Run

The webapp is containerized and ready to deploy to Google Cloud Run.
See the deployment instructions in [google3/learning/gemini/agents/projects/agency_os/webapp/README.md](google3/learning/gemini/agents/projects/agency_os/webapp/README.md).
