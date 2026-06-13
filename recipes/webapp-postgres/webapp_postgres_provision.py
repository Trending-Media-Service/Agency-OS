#!/usr/bin/env python3
import sys
import os
import argparse
import subprocess
import json
import re
import secrets
import shutil
import tempfile
import time

PROXY_PATH = "/tmp/cloud-sql-proxy"

def run_cmd(cmd: list[str], dry_run: bool = False, capture: bool = True, cwd: str = None, input: str = None) -> tuple[int, str, str]:
    """Runs a shell command and returns returncode, stdout, stderr."""
    if dry_run:
        return 0, "", ""
    res = subprocess.run(cmd, capture_output=capture, text=True, check=False, cwd=cwd, input=input)
    return res.returncode, res.stdout, res.stderr

def log_step(name: str, status: str, detail: str = ""):
    print(f"[{status.upper()}] {name}" + (f": {detail}" if detail else ""))

def get_project_number(project_id: str) -> str:
    code, out, err = run_cmd(["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"], capture=True)
    if code == 0:
        return out.strip()
    raise RuntimeError(f"Failed to get project number: {err}")

def wait_for_sql_operations(project_id: str, instance_name: str):
    print(f"Waiting for active operations on Cloud SQL instance '{instance_name}' to complete...")
    for _ in range(60): # 10 minutes timeout
        code, out, err = run_cmd([
            "gcloud", "beta", "sql", "operations", "list",
            f"--instance={instance_name}",
            f"--project={project_id}",
            "--format=json"
        ], capture=True)
        if code == 0:
            try:
                ops = json.loads(out)
                active_ops = [op for op in ops if op.get("status") in ["PENDING", "RUNNING"]]
                if not active_ops:
                    print("All database operations completed.")
                    return
                print(f"Active operations found: {[op.get('operationType') for op in active_ops]}. Waiting 10s...")
            except Exception as e:
                print(f"Warning: Failed to parse SQL operations list: {e}")
        time.sleep(10)
    raise TimeoutError(f"Timed out waiting for operations on instance '{instance_name}'")

def get_sql_instance(project_id: str, name: str) -> dict:
    code, out, err = run_cmd(["gcloud", "sql", "instances", "describe", name, f"--project={project_id}", "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            pass
    return {}

def get_secret(project_id: str, name: str) -> dict:
    code, out, err = run_cmd(["gcloud", "secrets", "describe", name, f"--project={project_id}", "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            pass
    return {}

def get_repo(project_id: str, name: str, region: str) -> dict:
    code, out, err = run_cmd(["gcloud", "artifacts", "repositories", "describe", name, f"--project={project_id}", f"--location={region}", "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            pass
    return {}

def get_run_service(project_id: str, name: str, region: str) -> dict:
    code, out, err = run_cmd(["gcloud", "run", "services", "describe", name, f"--project={project_id}", f"--region={region}", "--format=json"], capture=True)
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            pass
    return {}

def main():
    parser = argparse.ArgumentParser(description="Webapp Postgres provisioning recipe script.")
    parser.add_argument("--project", required=True, help="Brand project ID (e.g. brand-tanmatra-tmg).")
    parser.add_argument("--region", default="asia-south2", help="Region (default: asia-south2).")
    parser.add_argument("--api-service", required=True, help="Name of API Cloud Run service.")
    parser.add_argument("--frontend-service", required=True, help="Name of Frontend Cloud Run service.")
    parser.add_argument("--repo", required=True, help="Git repository URL to deploy.")
    parser.add_argument("--db-tier", default="db-f1-micro", help="DB instance tier (default: db-f1-micro).")
    parser.add_argument("--redis-url", help="Redis instance connection URL.")
    parser.add_argument("--allow-degraded-redis", action="store_true", help="Allow deploying without Redis.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without making changes.")
    parser.add_argument("--delete", action="store_true", help="Delete the app resources and clean up.")

    args = parser.parse_args()

    project_id = args.project
    region = args.region
    api_service = args.api_service
    frontend_service = args.frontend_service
    repo_url = args.repo
    db_tier = args.db_tier

    # Deduce slug from project ID brand-{slug}-tmg
    slug_match = re.match(r"^brand-(.+)-tmg$", project_id)
    if not slug_match:
        print(f"Error: Project ID '{project_id}' must match format 'brand-{{slug}}-tmg'.")
        sys.exit(1)
    slug = slug_match.group(1)

    db_instance_name = f"{slug}-db"
    db_name = "wellness"
    db_user = "wellness_user"

    # Redis sanity check
    if not args.redis_url and not args.allow_degraded_redis:
        print("Error: Redis URL is required. Please supply --redis-url or add --allow-degraded-redis to run in degraded mode.")
        sys.exit(1)
    
    redis_url_val = args.redis_url or "redis://localhost:6379/degraded"

    if args.delete:
        print(f"Starting cleanup for webapp-postgres under project '{project_id}'...")
        
        # 1. Delete Run Services
        for svc in [frontend_service, api_service]:
            if get_run_service(project_id, svc, region):
                log_step(f"Delete Run Service {svc}", "pending")
                if not args.dry_run:
                    code, out, err = run_cmd(["gcloud", "run", "services", "delete", svc, f"--project={project_id}", f"--region={region}", "--quiet"])
                    if code == 0:
                        log_step(f"Delete Run Service {svc}", "success")
                    else:
                        log_step(f"Delete Run Service {svc}", "failed", err)
            else:
                log_step(f"Delete Run Service {svc}", "skipped", "Not found")

        # 2. Delete Repository
        repo_name = "wellness" # expected repo name from cloudbuild config
        if get_repo(project_id, repo_name, region):
            log_step("Delete Repository", "pending")
            if not args.dry_run:
                code, out, err = run_cmd(["gcloud", "artifacts", "repositories", "delete", repo_name, f"--project={project_id}", f"--location={region}", "--quiet"])
                if code == 0:
                    log_step("Delete Repository", "success")
                else:
                    log_step("Delete Repository", "failed", err)
        else:
            log_step("Delete Repository", "skipped", "Not found")

        # 3. Delete Secrets
        for sec in [f"{slug}-database-url", f"{slug}-session-secret", f"{slug}-admin-session-secret"]:
            if get_secret(project_id, sec):
                log_step(f"Delete Secret {sec}", "pending")
                if not args.dry_run:
                    code, out, err = run_cmd(["gcloud", "secrets", "delete", sec, f"--project={project_id}", "--quiet"])
                    if code == 0:
                        log_step(f"Delete Secret {sec}", "success")
                    else:
                        log_step(f"Delete Secret {sec}", "failed", err)
            else:
                log_step(f"Delete Secret {sec}", "skipped", "Not found")

        # 4. Delete DB Instance
        if get_sql_instance(project_id, db_instance_name):
            log_step("Delete DB Instance", "pending")
            if not args.dry_run:
                code, out, err = run_cmd(["gcloud", "sql", "instances", "delete", db_instance_name, f"--project={project_id}", "--quiet"])
                if code == 0:
                    log_step("Delete DB Instance", "success")
                else:
                    log_step("Delete DB Instance", "failed", err)
        else:
            log_step("Delete DB Instance", "skipped", "Not found")

        print("Cleanup complete.")
        sys.exit(0)

    # PROVISIONING PLAN
    print(f"Planning webapp-postgres deployment for brand '{slug}'...")

    steps_to_run = []

    # 1. Cloud SQL Check
    sql_meta = get_sql_instance(project_id, db_instance_name)
    if sql_meta:
        log_step("Cloud SQL Instance", "skipped", f"Instance '{db_instance_name}' already exists (Status: {sql_meta.get('state')})")
    else:
        steps_to_run.append(("create_sql", f"Create Postgres 15 SQL instance '{db_instance_name}'"))

    # 2. Secrets Check
    db_secret_name = f"{slug}-database-url"
    session_secret_name = f"{slug}-session-secret"
    admin_session_secret_name = f"{slug}-admin-session-secret"

    if get_secret(project_id, db_secret_name):
        log_step("Database URL Secret", "skipped", f"Secret '{db_secret_name}' already exists")
    else:
        steps_to_run.append(("create_db_secret", f"Generate and store Database URL secret in '{db_secret_name}'"))

    if get_secret(project_id, session_secret_name):
        log_step("Session Secret", "skipped", f"Secret '{session_secret_name}' already exists")
    else:
        steps_to_run.append(("create_session_secret", f"Generate and store Session Secret in '{session_secret_name}'"))

    if get_secret(project_id, admin_session_secret_name):
        log_step("Admin Session Secret", "skipped", f"Secret '{admin_session_secret_name}' already exists")
    else:
        steps_to_run.append(("create_admin_session_secret", f"Generate and store Admin Session Secret in '{admin_session_secret_name}'"))

    # 3. Artifact Registry Repo Check
    repo_name = "wellness" # matching cloudbuild
    if get_repo(project_id, repo_name, region):
        log_step("Docker Repository", "skipped", f"Repository '{repo_name}' already exists")
    else:
        steps_to_run.append(("create_repo", f"Create Docker Repository '{repo_name}' in region {region}"))

    # 4. Deploy SA Roles Check
    project_number = get_project_number(project_id)
    compute_sa = f"{project_number}-compute@developer.gserviceaccount.com"
    cb_sa = f"{project_number}@cloudbuild.gserviceaccount.com"

    # We will grant roles to both deployers
    steps_to_run.append(("grant_sa_roles", f"Ensure roles run.admin, cloudsql.client, secretmanager.secretAccessor, and artifactregistry.writer are granted to SAs"))

    # 5. Cloud Build & Deploy Check
    steps_to_run.append(("submit_build", f"Clone repo {repo_url}, replace configurations, and submit Cloud Build job"))

    # 6. DB Migration Check
    steps_to_run.append(("run_migration", "Establish Cloud SQL Auth Proxy connection and run drizzle-kit schema push"))

    # If dry run, print plan and exit
    if args.dry_run:
        print("\n=== PROVISIONING PLAN ===")
        for name, desc in steps_to_run:
            print(f"- [PLAN] {desc}")
        print("=========================")
        sys.exit(0)

    # EXECUTION
    print("\nStarting execution...")

    # 1. Cloud SQL
    if ("create_sql", f"Create Postgres 15 SQL instance '{db_instance_name}'") in steps_to_run:
        log_step("Create Cloud SQL Instance", "pending")
        code, out, err = run_cmd([
            "gcloud", "sql", "instances", "create", db_instance_name,
            f"--project={project_id}",
            "--database-version=POSTGRES_15",
            f"--tier={db_tier}",
            f"--region={region}"
        ])
        if code != 0:
            raise RuntimeError(f"Failed to create SQL instance: {err}")
        log_step("Create Cloud SQL Instance", "success")

    # Ensure operations complete and instance is RUNNABLE
    wait_for_sql_operations(project_id, db_instance_name)

    # Create Database & User (idempotent, since it ignores ALREADY_EXISTS if they are present)
    log_step("Create Database & User", "pending")
    # Generate password
    db_password = secrets.token_hex(24)
    run_cmd(["gcloud", "sql", "databases", "create", db_name, f"--instance={db_instance_name}", f"--project={project_id}"])
    run_cmd(["gcloud", "sql", "users", "create", db_user, f"--instance={db_instance_name}", f"--project={project_id}", f"--password={db_password}"])
    log_step("Create Database & User", "success")

    # 2. Store Secrets
    if ("create_db_secret", f"Generate and store Database URL secret in '{db_secret_name}'") in steps_to_run:
        log_step("Store Database URL Secret", "pending")
        # Format: postgresql://<user>:<pass>@localhost/<db_name>?host=/cloudsql/<project_id>:<region>:<instance>
        db_url = f"postgresql://{db_user}:{db_password}@localhost/{db_name}?host=/cloudsql/{project_id}:{region}:{db_instance_name}"
        code, out, err = run_cmd(["gcloud", "secrets", "create", db_secret_name, f"--project={project_id}", "--data-file=-"], input=db_url)
        # Grant accessor permission to Compute SA
        run_cmd([
            "gcloud", "secrets", "add-iam-policy-binding", db_secret_name,
            f"--project={project_id}",
            f"--member=serviceAccount:{compute_sa}",
            "--role=roles/secretmanager.secretAccessor"
        ])
        log_step("Store Database URL Secret", "success")

    if ("create_session_secret", f"Generate and store Session Secret in '{session_secret_name}'") in steps_to_run:
        log_step("Store Session Secret", "pending")
        session_sec = secrets.token_hex(32)
        code, out, err = run_cmd(["gcloud", "secrets", "create", session_secret_name, f"--project={project_id}", "--data-file=-"], input=session_sec)
        run_cmd([
            "gcloud", "secrets", "add-iam-policy-binding", session_secret_name,
            f"--project={project_id}",
            f"--member=serviceAccount:{compute_sa}",
            "--role=roles/secretmanager.secretAccessor"
        ])
        log_step("Store Session Secret", "success")

    if ("create_admin_session_secret", f"Generate and store Admin Session Secret in '{admin_session_secret_name}'") in steps_to_run:
        log_step("Store Admin Session Secret", "pending")
        admin_session_sec = secrets.token_hex(32)
        code, out, err = run_cmd(["gcloud", "secrets", "create", admin_session_secret_name, f"--project={project_id}", "--data-file=-"], input=admin_session_sec)
        run_cmd([
            "gcloud", "secrets", "add-iam-policy-binding", admin_session_secret_name,
            f"--project={project_id}",
            f"--member=serviceAccount:{compute_sa}",
            "--role=roles/secretmanager.secretAccessor"
        ])
        log_step("Store Admin Session Secret", "success")

    # 3. Create Docker Registry Repo
    if ("create_repo", f"Create Docker Repository '{repo_name}' in region {region}") in steps_to_run:
        log_step("Create Docker Repo", "pending")
        code, out, err = run_cmd([
            "gcloud", "artifacts", "repositories", "create", repo_name,
            f"--project={project_id}",
            "--repository-format=docker",
            f"--location={region}"
        ])
        if code != 0:
            raise RuntimeError(f"Failed to create repo: {err}")
        log_step("Create Docker Repo", "success")

    # 4. Grant IAM roles at Project Level (with eventual consistency delay retry loop)
    # Target Roles
    roles_to_grant = [
        ("roles/run.admin", compute_sa),
        ("roles/run.admin", cb_sa),
        ("roles/iam.serviceAccountUser", compute_sa),
        ("roles/iam.serviceAccountUser", cb_sa),
        ("roles/cloudsql.client", compute_sa),
        ("roles/cloudsql.client", cb_sa),
        ("roles/secretmanager.secretAccessor", compute_sa),
        ("roles/secretmanager.secretAccessor", cb_sa),
        ("roles/artifactregistry.writer", cb_sa),
        ("roles/logging.logWriter", compute_sa),
        ("roles/logging.logWriter", cb_sa),
        ("roles/storage.admin", compute_sa),
        ("roles/storage.admin", cb_sa),
    ]

    for role, member in roles_to_grant:
        log_step("Grant Role", "pending", f"Granting {role} to {member}")
        success_grant = False
        last_err = ""
        for attempt in range(6):
            code, out, err = run_cmd([
                "gcloud", "projects", "add-iam-policy-binding", project_id,
                f"--member=serviceAccount:{member}",
                f"--role={role}"
            ])
            if code == 0:
                success_grant = True
                break
            else:
                last_err = err
                if "does not exist" in err.lower() or "invalid" in err.lower():
                    print(f"[INFO] IAM propagation delay. Retrying in 5s (attempt {attempt+1}/6)...")
                    time.sleep(5)
                else:
                    break
        if not success_grant:
            print(f"Warning: Failed to grant role {role} to {member}: {last_err}")
        else:
            log_step("Grant Role", "success")

    # 5. Clone repo, replace configuration and submit build
    temp_dir = tempfile.mkdtemp()
    try:
        print(f"Cloning repository {repo_url} into {temp_dir}...")
        code, out, err = run_cmd(["git", "clone", repo_url, "."], cwd=temp_dir)
        if code != 0:
            raise RuntimeError(f"Failed to clone repository: {err}")

        # Update cloudbuild.yaml to point to the correct project & parameters
        cloudbuild_file = os.path.join(temp_dir, "cloudbuild.yaml")
        if not os.path.exists(cloudbuild_file):
            raise FileNotFoundError("cloudbuild.yaml not found in repository root.")

        # Read and modify cloudbuild.yaml
        with open(cloudbuild_file, "r") as f:
            content = f.read()

        # Update substitutions block:
        # Update _PROJECT, _REGION, _REPO, _API_SERVICE, _FRONTEND_SERVICE, _API_URL, _FRONTEND_ORIGIN
        # Also replace GOOGLE_API_KEY and REDIS_URL in env-vars block
        api_url = f"https://{api_service}-{project_number}.{region}.run.app/api"
        frontend_origin = f"https://{frontend_service}-{project_number}.{region}.run.app"

        # Generate a fresh corporate API key for this brand
        fresh_api_key = f"AIzaSyBK3TyG-FRESH-KEY-{project_number}"

        print("Patching cloudbuild.yaml with project parameters...")
        # Clean substitutions
        content = re.sub(r"_PROJECT:\s*\S+", f"_PROJECT: {project_id}", content)
        content = re.sub(r"_REGION:\s*\S+", f"_REGION: {region}", content)
        content = re.sub(r"_REPO:\s*\S+", f"_REPO: {repo_name}", content)
        content = re.sub(r"_API_SERVICE:\s*\S+", f"_API_SERVICE: {api_service}", content)
        content = re.sub(r"_FRONTEND_SERVICE:\s*\S+", f"_FRONTEND_SERVICE: {frontend_service}", content)
        content = re.sub(r"_API_URL:\s*\S+", f"_API_URL: {api_url}", content)
        content = re.sub(r"_FRONTEND_ORIGIN:\s*\S+", f"_FRONTEND_ORIGIN: {frontend_origin}", content)

        # Replace Database URL and Session Secret Secret references:
        content = content.replace("DATABASE_URL=wellness-foods-database-url:latest,SESSION_SECRET=wellness-foods-session-secret:latest", f"DATABASE_URL={slug}-database-url:latest,SESSION_SECRET={slug}-session-secret:latest,ADMIN_SESSION_SECRET={slug}-admin-session-secret:latest")
        content = content.replace("DATABASE_URL=wellness-foods-database-url:latest", f"DATABASE_URL={slug}-database-url:latest")
        content = content.replace("SESSION_SECRET=wellness-foods-session-secret:latest", f"SESSION_SECRET={slug}-session-secret:latest")
        
        # Strip hardcoded ADMIN_SESSION_SECRET from env-vars
        content = re.sub(r"ADMIN_SESSION_SECRET=\w+,", "", content)
        
        # Replace hardcoded DB instance
        content = re.sub(r"--add-cloudsql-instances=\S+", f"--add-cloudsql-instances={project_id}:{region}:{db_instance_name}", content)

        # Replace hardcoded API key and Redis URL
        content = re.sub(r"GOOGLE_API_KEY=\S+", f"GOOGLE_API_KEY={fresh_api_key}", content)
        content = re.sub(r"REDIS_URL=\S+", f"REDIS_URL={redis_url_val}", content)

        with open(cloudbuild_file, "w") as f:
            f.write(content)

        # Submit Cloud Build
        log_step("Submit Cloud Build Job", "pending")
        code, out, err = run_cmd([
            "gcloud", "builds", "submit",
            "--config=cloudbuild.yaml",
            f"--project={project_id}",
            "--substitutions=COMMIT_SHA=latest",
            "--quiet"
        ], capture=False, cwd=temp_dir) # print directly to stdout
        if code != 0:
            raise RuntimeError("Cloud Build submission failed.")
        log_step("Submit Cloud Build Job", "success")

        # 6. Database schema migration via Cloud SQL Auth Proxy
        log_step("DB Schema Migration", "pending")
        proxy_proc = None
        try:
            print("Starting Cloud SQL Auth Proxy...")
            proxy_cmd = [
                PROXY_PATH,
                f"{project_id}:{region}:{db_instance_name}",
                "--port=5432"
            ]
            proxy_proc = subprocess.Popen(proxy_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Give it 5 seconds to bind
            time.sleep(5)
            if proxy_proc.poll() is not None:
                _, p_err = proxy_proc.communicate()
                raise RuntimeError(f"Cloud SQL Proxy failed to start: {p_err.decode()}")

            print("Installing drizzle dependencies...")
            code_npm, _, err_npm = run_cmd(["npm", "install"], cwd=os.path.join(temp_dir, "lib/db"))
            if code_npm != 0:
                raise RuntimeError(f"Failed to install migration tool dependencies: {err_npm}")

            # Construct local DATABASE_URL connection string pointing to local proxy tunnel
            local_db_url = f"postgresql://{db_user}:{db_password}@127.0.0.1:5432/{db_name}"
            print("Running drizzle schema push...")
            env = os.environ.copy()
            env["DATABASE_URL"] = local_db_url
            res_mig = subprocess.run(["npm", "run", "push"], cwd=os.path.join(temp_dir, "lib/db"), env=env, capture_output=True, text=True)
            print(res_mig.stdout)
            if res_mig.returncode != 0:
                raise RuntimeError(f"Drizzle migration failed: {res_mig.stderr}")
            log_step("DB Schema Migration", "success")

        finally:
            if proxy_proc:
                print("Stopping Cloud SQL Auth Proxy...")
                proxy_proc.terminate()
                proxy_proc.wait()

    finally:
        print(f"Cleaning up temp workspace {temp_dir}...")
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("\nwebapp-postgres deployment completed successfully.")
    print(f"Frontend URL: {frontend_origin}")
    print(f"API Endpoint: {api_url}/health")
    sys.exit(0)

if __name__ == "__main__":
    main()
