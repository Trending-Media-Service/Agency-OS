#!/usr/bin/env python3
import sys
import os
import argparse
import subprocess
import json
import re

ORG_ID = "57417030394"
TENANTS_FOLDER = "338402544084"
BILLING = "012E0F-7A4F33-26EDD8"
DEFAULT_REGION = "asia-south2"

APIS_TO_ENABLE = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "dns.googleapis.com",
]

SA_ROLES = [
    "roles/run.admin",
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
    "roles/storage.admin",
]

def run_cmd(cmd: list[str], dry_run: bool = False, capture: bool = True) -> tuple[int, str, str]:
    """Runs a shell command and returns returncode, stdout, stderr."""
    if dry_run:
        return 0, "", ""
    res = subprocess.run(cmd, capture_output=capture, text=True, check=False)
    return res.returncode, res.stdout, res.stderr

def log_step(name: str, status: str, detail: str = ""):
    print(f"[{status.upper()}] {name}" + (f": {detail}" if detail else ""))

def get_project(project_id: str) -> dict:
    """Gets project metadata or returns None if not found."""
    code, out, err = run_cmd(["gcloud", "projects", "describe", project_id, "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            return {}
    return {}

def check_billing(project_id: str) -> dict:
    """Gets project billing info."""
    code, out, err = run_cmd(["gcloud", "billing", "projects", "describe", project_id, "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            return {}
    return {}

def get_budget(display_name: str) -> dict:
    """Gets budget info by display name."""
    code, out, err = run_cmd(["gcloud", "billing", "budgets", "list", f"--billing-account={BILLING}", "--format=json"], capture=True)
    if code == 0:
        try:
            budgets = json.loads(out)
            for budget in budgets:
                if budget.get("displayName") == display_name:
                    return budget
        except Exception:
            pass
    return {}

def get_enabled_services(project_id: str) -> list[str]:
    """Gets enabled services for project."""
    code, out, err = run_cmd(["gcloud", "services", "list", f"--project={project_id}", "--enabled", "--format=json"], capture=True)
    if code == 0:
        try:
            services = json.loads(out)
            return [s.get("config", {}).get("name") for s in services]
        except Exception:
            pass
    return []

def get_service_account(project_id: str, email: str) -> dict:
    """Gets SA metadata."""
    code, out, err = run_cmd(["gcloud", "iam", "service-accounts", "describe", email, f"--project={project_id}", "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            return {}
    return {}

def get_iam_policy(project_id: str) -> dict:
    """Gets project IAM policy."""
    code, out, err = run_cmd(["gcloud", "projects", "get-iam-policy", project_id, "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            return {}
    return {}

def main():
    parser = argparse.ArgumentParser(description="Brand baseline provisioning script.")
    parser.add_argument("--slug", required=True, help="Brand slug (lowercase, alphanumeric + hyphen).")
    parser.add_argument("--budget-inr", type=int, default=2000, help="Budget limit in INR (default: 2000).")
    parser.add_argument("--display-name", help="Display name for the GCP project.")
    parser.add_argument("--suffix", help="Suffix to append to project ID in case of collision.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing changes.")
    parser.add_argument("--delete", action="store_true", help="Delete the brand project and clean up.")

    args = parser.parse_args()

    slug = args.slug.lower()
    if not re.match(r"^[a-z0-9-]+$", slug):
        print(f"Error: Slug '{slug}' must only contain lowercase alphanumeric characters and hyphens.")
        sys.exit(1)

    project_id = f"brand-{slug}-tmg"
    display_name = args.display_name or f"Brand {slug.capitalize()}"
    if ":" in display_name:
        print("Error: Display name cannot contain colons (GCP rejects them).")
        sys.exit(1)

    # If delete flag is passed, clean up the resources
    if args.delete:
        print(f"Starting cleanup for brand '{slug}' (Project: {project_id})...")
        proj_meta = get_project(project_id)
        if proj_meta:
            # Delete budget
            budget_name = f"{project_id}-guard"
            budget = get_budget(budget_name)
            if budget:
                budget_id = budget["name"].split("/")[-1]
                log_step("Delete Budget Guard", "pending", f"Deleting budget ID {budget_id}")
                if not args.dry_run:
                    code, out, err = run_cmd(["gcloud", "billing", "budgets", "delete", budget_id, f"--billing-account={BILLING}", "--quiet"])
                    if code != 0:
                        log_step("Delete Budget Guard", "failed", err)
                    else:
                        log_step("Delete Budget Guard", "success")
                else:
                    log_step("Delete Budget Guard", "plan", f"Would delete budget ID {budget_id}")

            # Delete project
            log_step("Delete Project", "pending", f"Deleting project {project_id}")
            if not args.dry_run:
                code, out, err = run_cmd(["gcloud", "projects", "delete", project_id, "--quiet"])
                if code != 0:
                    log_step("Delete Project", "failed", err)
                    sys.exit(1)
                else:
                    log_step("Delete Project", "success")
            else:
                log_step("Delete Project", "plan", f"Would delete project {project_id}")
        else:
            print(f"Project {project_id} does not exist. Cleanup complete.")
        sys.exit(0)

    # Creation / update pipeline
    print(f"Planning brand-baseline for slug '{slug}'...")

    # Step 1: Collision check and project ID resolution
    proj_meta = get_project(project_id)
    project_created_this_run = False
    
    if proj_meta:
        # Check if project folder belongs to tenants folder
        parent_id = proj_meta.get("parent", {}).get("id")
        parent_type = proj_meta.get("parent", {}).get("type")
        if parent_type == "folder" and parent_id == TENANTS_FOLDER:
            print(f"Project '{project_id}' already exists under the correct folder. Proceeding with update/idempotent checks.")
        else:
            # Collision: exists but in wrong folder/org!
            print(f"Error: Collision! Project ID '{project_id}' exists but belongs to folder/parent: {parent_type}/{parent_id} (Expected folder/{TENANTS_FOLDER}).")
            if args.suffix:
                project_id = f"brand-{slug}-{args.suffix}-tmg"
                print(f"Suffix provided. Resolving project ID to: {project_id}")
                # Re-check updated project ID
                proj_meta = get_project(project_id)
                if proj_meta:
                    parent_id = proj_meta.get("parent", {}).get("id")
                    parent_type = proj_meta.get("parent", {}).get("type")
                    if parent_type == "folder" and parent_id == TENANTS_FOLDER:
                        print(f"Suffix project '{project_id}' already exists. Proceeding.")
                    else:
                        print(f"Error: Suffix project ID '{project_id}' also collides with wrong parent: {parent_type}/{parent_id}.")
                        sys.exit(1)
            else:
                print("Fail: Specify --suffix to resolve or resolve manually.")
                sys.exit(1)

    steps_to_run = []
    
    # Check Project Creation
    if not proj_meta:
        steps_to_run.append(("create_project", f"Create project {project_id} under folder {TENANTS_FOLDER}"))
    else:
        log_step("Project Creation", "skipped", "Project already exists")

    # Check Billing Link
    if proj_meta:
        billing_info = check_billing(project_id)
        if billing_info.get("billingEnabled"):
            log_step("Billing Link", "skipped", f"Already linked to {billing_info.get('billingAccountName')}")
        else:
            steps_to_run.append(("link_billing", f"Link billing to account {BILLING}"))
    else:
        steps_to_run.append(("link_billing", f"Link billing to account {BILLING}"))

    # Check Budget Guard
    budget_name = f"{project_id}-guard"
    budget = get_budget(budget_name)
    if budget:
        log_step("Budget Guard", "skipped", f"Budget '{budget_name}' already exists (Amount: {budget.get('amount', {}).get('specifiedAmount', {}).get('units')} INR)")
    else:
        steps_to_run.append(("create_budget", f"Create budget guard of {args.budget_inr} INR"))

    # Check Service Enablement
    enabled_apis = []
    if proj_meta:
        enabled_apis = get_enabled_services(project_id)
    
    missing_apis = [api for api in APIS_TO_ENABLE if api not in enabled_apis]
    if not missing_apis:
        log_step("Enable APIs", "skipped", "All 6 required APIs are enabled")
    else:
        steps_to_run.append(("enable_apis", f"Enable APIs: {', '.join(missing_apis)}"))

    # Check Service Account
    sa_email = f"{slug}-runner@{project_id}.iam.gserviceaccount.com"
    sa_meta = None
    if proj_meta:
        sa_meta = get_service_account(project_id, sa_email)
    
    if sa_meta:
        log_step("Create Service Account", "skipped", f"SA '{sa_email}' already exists")
    else:
        steps_to_run.append(("create_sa", f"Create service account '{slug}-runner'"))

    # Check IAM bindings
    iam_policy = {}
    if proj_meta:
        iam_policy = get_iam_policy(project_id)
    
    # Helper to check if role exists for member
    bindings = iam_policy.get("bindings", [])
    sa_member = f"serviceAccount:{sa_email}"
    missing_roles = []
    for role in SA_ROLES:
        has_role = False
        for b in bindings:
            if b.get("role") == role and sa_member in b.get("members", []):
                has_role = True
                break
        if not has_role:
            missing_roles.append(role)

    if not missing_roles:
        log_step("Grant SA Roles", "skipped", "All 5 required roles already bound")
    else:
        steps_to_run.append(("grant_roles", f"Grant roles on project to SA: {', '.join(missing_roles)}"))

    # If dry run, print plan and exit
    if args.dry_run:
        print("\n=== PROVISIONING PLAN ===")
        if not steps_to_run:
            print("No changes needed. Infrastructure is fully up-to-date and matches specification.")
        for name, desc in steps_to_run:
            print(f"- [PLAN] {desc}")
        print("=========================")
        sys.exit(0)

    # EXECUTION WITH ROLLBACK ON FAILURE
    if not steps_to_run:
        print("No changes needed. Success.")
        sys.exit(0)

    print("\nStarting execution...")
    try:
        # 1. Create Project
        if ("create_project", f"Create project {project_id} under folder {TENANTS_FOLDER}") in steps_to_run:
            log_step("Create Project", "pending")
            code, out, err = run_cmd(["gcloud", "projects", "create", project_id, f"--folder={TENANTS_FOLDER}", f"--name={display_name}"])
            if code != 0:
                raise RuntimeError(f"Project creation failed: {err}")
            project_created_this_run = True
            log_step("Create Project", "success")

        # 2. Link Billing
        if ("link_billing", f"Link billing to account {BILLING}") in steps_to_run:
            log_step("Link Billing", "pending")
            code, out, err = run_cmd(["gcloud", "billing", "projects", "link", project_id, f"--billing-account={BILLING}"])
            if code != 0:
                raise RuntimeError(f"Billing link failed: {err}")
            log_step("Link Billing", "success")

        # 3. Create Budget
        if ("create_budget", f"Create budget guard of {args.budget_inr} INR") in steps_to_run:
            log_step("Create Budget Guard", "pending")
            # We filter budget to only track this project's costs
            code, out, err = run_cmd([
                "gcloud", "billing", "budgets", "create",
                f"--billing-account={BILLING}",
                f"--display-name={budget_name}",
                f"--budget-amount={args.budget_inr}INR",
                f"--filter-projects=projects/{project_id}",
                "--threshold-rule=percent=0.5",
                "--threshold-rule=percent=0.9",
                "--threshold-rule=percent=1.0"
            ])
            if code != 0:
                raise RuntimeError(f"Budget creation failed: {err}")
            log_step("Create Budget Guard", "success")

        # 4. Enable APIs
        if ("enable_apis", f"Enable APIs: {', '.join(missing_apis)}") in steps_to_run:
            log_step("Enable APIs", "pending")
            code, out, err = run_cmd(["gcloud", "services", "enable"] + missing_apis + [f"--project={project_id}"])
            if code != 0:
                raise RuntimeError(f"API enablement failed: {err}")
            log_step("Enable APIs", "success")

        # 5. Create Service Account
        if ("create_sa", f"Create service account '{slug}-runner'") in steps_to_run:
            log_step("Create Service Account", "pending")
            code, out, err = run_cmd(["gcloud", "iam", "service-accounts", "create", f"{slug}-runner", f"--project={project_id}", f"--display-name={slug} runner"])
            if code != 0:
                raise RuntimeError(f"SA creation failed: {err}")
            log_step("Create Service Account", "success")

        # 6. Grant roles to Service Account
        if ("grant_roles", f"Grant roles on project to SA: {', '.join(missing_roles)}") in steps_to_run:
            import time
            for role in missing_roles:
                log_step("Grant Role", "pending", f"Granting {role} to SA")
                success_grant = False
                last_err = ""
                for attempt in range(6):
                    code, out, err = run_cmd([
                        "gcloud", "projects", "add-iam-policy-binding", project_id,
                        f"--member=serviceAccount:{sa_email}",
                        f"--role={role}"
                    ])
                    if code == 0:
                        success_grant = True
                        break
                    else:
                        last_err = err
                        if "does not exist" in err.lower() or "invalid" in err.lower():
                            print(f"[INFO] IAM eventual consistency delay. Retrying role grant in 5s (attempt {attempt+1}/6)...")
                            time.sleep(5)
                        else:
                            break
                if not success_grant:
                    raise RuntimeError(f"Failed to grant role {role}: {last_err}")
                log_step("Grant Role", "success", f"Granted {role} to SA")

        print("\nProvisioning completed successfully.")
        sys.exit(0)

    except Exception as e:
        print(f"\nExecution failed: {e}")
        # If the project was created in this run, perform rollback to prevent orphan state
        if project_created_this_run:
            print(f"Rolling back: Deleting half-built project '{project_id}'...")
            code, out, err = run_cmd(["gcloud", "projects", "delete", project_id, "--quiet"])
            if code != 0:
                print(f"Error during rollback: Failed to delete project: {err}")
            else:
                print("Rollback complete. Project deleted.")
        sys.exit(1)

if __name__ == "__main__":
    main()
