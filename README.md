# Agency OS

This repository contains the Agency OS project codebase, containing the governance control plane and infrastructure recipes.

## Project Structure

*   `control-plane/`: The FastAPI backend control plane containing the governance kernel, safety primitives, trust engine, and adapters.
*   `recipes/`: Parameterized, idempotent infrastructure provisioning blueprints (e.g., `brand-baseline`, `webapp-postgres`, `web-host`).
*   `docs/archive/`: Legacy design reference guides (archived).

## Running the Control Plane Locally

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Trending-Media-Service/Agency-OS.git
   cd Agency-OS
   ```

2. **Install dependencies**:
   Ensure you have Python 3 installed. Navigate to the `control-plane` directory and install the requirements:
   ```bash
   cd control-plane
   pip install -r requirements.txt
   ```

3. **Run the test suite**:
   ```bash
   pytest
   ```

4. **Start the application**:
   ```bash
   uvicorn app.main:app --reload
   ```
   The control plane API will be serving at `http://127.0.0.1:8000`.

## Configuration

The control plane runs SQLite by default. To override with an external Postgres database, specify `AOS_DB_URL`.
