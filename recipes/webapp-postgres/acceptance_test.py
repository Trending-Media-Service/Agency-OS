#!/usr/bin/env python3
import sys
import os
import subprocess
import json
import time
import urllib.request

def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return res.returncode, res.stdout, res.stderr

def http_get(url: str) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode()
    except Exception as e:
        return 500, str(e)

def main():
    verify_slug = "tanmatra-app-verify"
    verify_project = f"brand-{verify_slug}-tmg"

    print("=== Running Acceptance Test for webapp-postgres ===")

    # 1. Ensure clean slate by running delete commands
    print("Ensuring clean slate...")
    run_cmd(["python3", "webapp_postgres_provision.py", "--project", verify_project, "--api-service", "wellness-foods", "--frontend-service", "tanmatra", "--repo", "https://github.com/chan8822/Wellness-Foods.git", "--delete"])
    run_cmd(["python3", "../brand-baseline/brand_baseline_provision.py", "--slug", verify_slug, "--delete"])

    # 2. Provision baseline project
    print("\n1. Running brand-baseline for verify slug...")
    code, out, err = run_cmd(["python3", "../brand-baseline/brand_baseline_provision.py", "--slug", verify_slug, "--budget-inr", "2000"])
    print(out)
    if code != 0:
        print(f"brand-baseline failed: {err}")
        sys.exit(1)

    # 3. Provision Node/Postgres web app
    print("\n2. Running webapp-postgres provisioning...")
    # Using allow-degraded-redis to bypass external Redis requirement for testing
    code, out, err = run_cmd([
        "python3", "webapp_postgres_provision.py",
        f"--project={verify_project}",
        "--api-service=wellness-foods",
        "--frontend-service=tanmatra",
        "--repo=https://github.com/chan8822/Wellness-Foods.git",
        "--allow-degraded-redis"
    ])
    print(out)
    if code != 0:
        print(f"webapp-postgres failed with exit code {code}. Stderr:\n{err}")
        sys.exit(1)

    # 4. Extract URLs
    # Look for Frontend URL and API Endpoint in output
    frontend_url = None
    api_url = None
    for line in out.splitlines():
        if "Frontend URL:" in line:
            frontend_url = line.split("Frontend URL:")[-1].strip()
        elif "API Endpoint:" in line:
            api_url = line.split("API Endpoint:")[-1].strip()

    if not frontend_url or not api_url:
        print(f"Error: Failed to parse Frontend/API URLs from script output.")
        sys.exit(1)

    print(f"\nExtracted URLs:\n  Frontend: {frontend_url}\n  API: {api_url}")

    success = True
    
    # 5. Assertions
    print("\n--- Running Live Endpoint Verification ---")
    
    # Assert 5.1: API Liveness Probe
    livez_url = api_url.replace("/health", "/livez")
    print(f"Querying liveness endpoint: {livez_url} ...")
    code_h, body_h = http_get(livez_url)
    if code_h == 200 and "ok" in body_h:
        print("[PASS] API liveness probe (/livez) returned 200 OK")
    else:
        print(f"[FAIL] API liveness probe returned status {code_h}, body: {body_h}")
        success = False

    # Assert 5.2: API Readiness Probe (deep DB health check)
    healthz_url = api_url.replace("/health", "/healthz")
    print(f"Querying readiness endpoint: {healthz_url} ...")
    # Wait up to 10 seconds for initial container cold startup to complete
    time.sleep(5)
    code_h, body_h = http_get(healthz_url)
    if code_h == 200 and "ok" in body_h:
        print("[PASS] API readiness probe (/healthz) returned 200 OK (DB connected successfully)")
    else:
        print(f"[FAIL] API readiness probe returned status {code_h}, body: {body_h}")
        success = False

    # Assert 5.3: Frontend Load
    print(f"Querying frontend homepage: {frontend_url} ...")
    code_f, body_f = http_get(frontend_url)
    if code_f == 200 and "<html" in body_f.lower():
        print("[PASS] Frontend loads homepage shell successfully (status 200)")
    else:
        print(f"[FAIL] Frontend failed to load, status {code_f}, body: {body_f[:300]}")
        success = False

    # 6. Tear down resources
    print("\nStarting teardown of resources...")
    code_del, out_del, err_del = run_cmd([
        "python3", "webapp_postgres_provision.py",
        f"--project={verify_project}",
        "--api-service=wellness-foods",
        "--frontend-service=tanmatra",
        "--repo=https://github.com/chan8822/Wellness-Foods.git",
        "--delete"
    ])
    print(out_del)
    
    code_base_del, out_base_del, err_base_del = run_cmd(["python3", "../brand-baseline/brand_baseline_provision.py", "--slug", verify_slug, "--delete"])
    print(out_base_del)

    print("Teardown complete.")

    if success:
        print("\n[SUCCESS] webapp-postgres recipe has successfully passed the acceptance test!")
        sys.exit(0)
    else:
        print("\n[FAILURE] webapp-postgres recipe failed live end-to-end verification.")
        sys.exit(1)

if __name__ == "__main__":
    main()
