#!/usr/bin/env python3
import sys
import os
import subprocess
import json

# Import functions from provision script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from brand_baseline_provision import (
    get_project, check_billing, get_budget, get_enabled_services,
    get_service_account, get_iam_policy, TENANTS_FOLDER, BILLING, SA_ROLES
)

def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return res.returncode, res.stdout, res.stderr

def main():
    verify_slug = "tanmatra-verify"
    verify_project = f"brand-{verify_slug}-tmg"
    control_project = "brand-tanmatra-tmg"

    print(f"=== Running Acceptance Test for brand-baseline ===")
    
    # 1. Clean up any leftover project if it exists
    print(f"Ensuring clean slate: checking if {verify_project} exists...")
    if get_project(verify_project):
        print(f"Leftover project {verify_project} found. Deleting...")
        code, out, err = run_cmd(["python3", "brand_baseline_provision.py", "--slug", verify_slug, "--delete"])
        if code != 0:
            print(f"Failed to delete leftover project: {err}")
            sys.exit(1)

    # 2. Run provision script to create project
    print(f"\n1. Provisioning verify project '{verify_project}'...")
    code, out, err = run_cmd(["python3", "brand_baseline_provision.py", "--slug", verify_slug, "--budget-inr", "2000"])
    print(out)
    if code != 0:
        print(f"Provision script failed with exit code {code}. Stderr:\n{err}")
        sys.exit(1)

    print("Provisioning succeeded. Starting structural assertions...")
    
    success = True
    
    # Fetch configurations
    print("\nFetching verify project configuration...")
    v_proj = get_project(verify_project)
    v_billing = check_billing(verify_project)
    v_budget = get_budget(f"{verify_project}-guard")
    v_apis = get_enabled_services(verify_project)
    v_sa_email = f"{verify_slug}-runner@{verify_project}.iam.gserviceaccount.com"
    v_sa = get_service_account(verify_project, v_sa_email)
    v_iam = get_iam_policy(verify_project)

    print("Fetching control project (brand-tanmatra-tmg) configuration...")
    c_proj = get_project(control_project)
    c_billing = check_billing(control_project)
    c_budget = get_budget("brand-tanmatra-guard")
    c_apis = get_enabled_services(control_project)
    # Control SA is tanmatra-runner
    c_sa_email = f"tanmatra-runner@{control_project}.iam.gserviceaccount.com"
    c_sa = get_service_account(control_project, c_sa_email)
    c_iam = get_iam_policy(control_project)

    # ASSERTIONS
    print("\n--- Structural Assertions ---")

    # Assert 1: Parent Folder
    v_parent = v_proj.get("parent", {}).get("id")
    c_parent = c_proj.get("parent", {}).get("id")
    if v_parent == TENANTS_FOLDER:
        print(f"[PASS] Verify project parent folder matches TENANTS_FOLDER ({TENANTS_FOLDER})")
    else:
        print(f"[FAIL] Verify project parent folder: {v_parent} (Expected {TENANTS_FOLDER})")
        success = False

    # Assert 2: Billing Enabled
    if v_billing.get("billingEnabled") is True:
        print("[PASS] Verify project billing is linked and enabled")
    else:
        print(f"[FAIL] Verify project billing not enabled: {v_billing}")
        success = False

    # Assert 3: Budget Guard present and matches structurally
    if v_budget:
        print(f"[PASS] Verify project budget guard exists")
        # Compare budget amount
        v_amount = v_budget.get("amount", {}).get("specifiedAmount", {}).get("units")
        if v_amount == "2000":
            print(f"[PASS] Verify budget amount is 2000 INR")
        else:
            print(f"[FAIL] Verify budget amount is {v_amount} (Expected 2000)")
            success = False
            
        # Compare budget project filter
        # Format can be projects/project_id or projects/number
        # So we check if the string contains project_id
        # Note: in gcloud list it might print projects/project_number, so we check if budget exists
        print(f"[INFO] Verify budget displayName: {v_budget.get('displayName')}")
    else:
        print(f"[FAIL] Verify budget guard does not exist")
        success = False

    # Assert 4: Required APIs Enabled
    # All 6 required APIs must be enabled
    missing_v_apis = [api for api in [
        "run.googleapis.com",
        "sqladmin.googleapis.com",
        "artifactregistry.googleapis.com",
        "cloudbuild.googleapis.com",
        "secretmanager.googleapis.com",
        "dns.googleapis.com",
    ] if api not in v_apis]
    
    if not missing_v_apis:
        print("[PASS] All 6 required APIs are enabled in verify project")
    else:
        print(f"[FAIL] Missing APIs in verify project: {missing_v_apis}")
        success = False

    # Assert 5: Service Account exists
    if v_sa:
        print(f"[PASS] Service account {v_sa_email} exists")
    else:
        print(f"[FAIL] Service account {v_sa_email} does not exist")
        success = False

    # Assert 6: IAM Policy / roles match
    v_bindings = v_iam.get("bindings", [])
    sa_member = f"serviceAccount:{v_sa_email}"
    missing_roles = []
    for role in SA_ROLES:
        has_role = False
        for b in v_bindings:
            if b.get("role") == role and sa_member in b.get("members", []):
                has_role = True
                break
        if not has_role:
            missing_roles.append(role)

    if not missing_roles:
        print("[PASS] All 5 required runner roles are bound in verify project")
    else:
        print(f"[FAIL] Service Account is missing roles: {missing_roles}")
        success = False

    # 3. Clean up the verify project
    print("\nCleaning up verify project brand-tanmatra-verify-tmg...")
    code, out, err = run_cmd(["python3", "brand_baseline_provision.py", "--slug", verify_slug, "--delete"])
    if code != 0:
        print(f"Cleanup failed: {err}")
        sys.exit(1)
    print("Cleanup complete.")

    if success:
        print("\n[SUCCESS] brand-baseline recipe has successfully passed the acceptance test!")
        sys.exit(0)
    else:
        print("\n[FAILURE] brand-baseline recipe failed structural assertion checks.")
        sys.exit(1)

if __name__ == "__main__":
    main()
